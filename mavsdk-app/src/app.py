#!/usr/bin/env python3
"""
Flask Application — REST API + SSE telemetry stream + static frontend.
Bridges the voice/UI frontend to the Python drone backend.
"""

import json
import os
import sys
import threading
import time
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Ensure both the challenge package and voice_input module are importable
_project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, _project_root)

from voice_input import listen_and_transcribe

from drone_control import CommandResult, DIRECTION_MAP, DroneController
from intent_parser import parse_command
from validator import resolve_location, validate
from voice_io import VoiceFeedback
from challenge.config import PYMAVLINK_CONNECTION

app = Flask(__name__, static_folder="static")
voice = VoiceFeedback(use_server_tts=False)


# Multi-drone controllers: drone_id -> DroneController
drones: dict[str, DroneController] = {}
command_log: list[dict] = []
_listen_stop = threading.Event()

# ── Command Queue State ──────────────────────────────────────────────────

_queue_cancel = threading.Event()
_queue_thread: threading.Thread | None = None
_queue_status: dict = {"state": "idle", "total": 0, "current": 0, "commands": []}
_queue_lock = threading.Lock()


def _set_queue_status(**kwargs):
    with _queue_lock:
        _queue_status.update(kwargs)


def _cancel_active_queue():
    """Signal any running queue to stop after its current command."""
    global _queue_thread
    _queue_cancel.set()
    if _queue_thread and _queue_thread.is_alive():
        _queue_thread.join(timeout=5)
    _queue_thread = None
    _queue_cancel.clear()


# ── Single-Intent Processing ─────────────────────────────────────────────

def _process_single_intent(intent: dict, ctrl: DroneController,
                           wait_for_move: bool = False) -> dict:
    """Run one intent through resolve → validate → execute.

    Returns a log-entry dict. When *wait_for_move* is True, goto/move
    commands block until the drone arrives (used by the queue worker).
    """
    timestamp = datetime.now().isoformat()
    action = intent.get("action", "")

    # Resolve named location
    if action == "goto" and "location" in intent:
        loc = resolve_location(intent["location"])
        if loc:
            intent["x"] = loc.x
            intent["y"] = loc.y
            if intent.get("altitude") is None:
                intent["altitude"] = loc.default_alt
            intent["resolved_name"] = loc.name
        else:
            entry = {
                "timestamp": timestamp, "intent": _clean_intent(intent),
                "status": "rejected",
                "reason": f"Unknown location: {intent['location']}",
                "feedback": f"Unknown location: {intent['location']}. Please specify a known compound location.",
            }
            command_log.append(entry)
            return entry

    # Compute relative target coords
    if action == "move_relative":
        pos = ctrl.get_position()
        d = intent.get("direction", "north").lower()
        dx, dy = DIRECTION_MAP.get(d, (0, 0))
        dist = intent.get("distance", 0)
        intent["x"] = pos["x"] + dx * dist
        intent["y"] = pos["y"] + dy * dist
        if intent.get("altitude") is None:
            intent["altitude"] = pos["alt"]

    if action == "change_altitude":
        pos = ctrl.get_position()
        intent["x"] = pos["x"]
        intent["y"] = pos["y"]

    # Validate
    current_pos = ctrl.get_position()
    validation = validate(intent, current_pos)

    entry: dict = {
        "timestamp": timestamp,
        "intent": _clean_intent(intent),
        "status": "approved" if validation.approved else "rejected",
        "reason": validation.reason,
    }
    if validation.waypoints:
        entry["rerouted"] = True
        entry["waypoint_count"] = len(validation.waypoints)
        entry["path_quality"] = validation.path_quality

    if not validation.approved:
        entry["feedback"] = voice.generate_feedback("rejected", intent, reason=validation.reason)
        entry["suggestion"] = validation.suggestion
        command_log.append(entry)
        return entry

    # Execute
    result = _execute_action(intent, validation, ctrl, wait_for_move)

    if result and result.success:
        feedback = voice.generate_feedback("approved", intent, drone_pos=current_pos)
        if action == "report_status":
            feedback = result.message
        entry["feedback"] = feedback
        entry["execution"] = result.message
    elif result:
        entry["status"] = "error"
        entry["feedback"] = f"Execution failed: {result.message}"
    else:
        entry["feedback"] = "Unknown action."

    command_log.append(entry)
    return entry


def _execute_action(intent: dict, validation, ctrl: DroneController,
                    wait: bool = False) -> CommandResult | None:
    action = intent.get("action")

    if action == "takeoff":
        return ctrl.takeoff(intent.get("altitude", 10))

    if action in ("goto", "move_relative"):
        if validation.waypoints:
            if wait:
                return ctrl.fly_waypoints(validation.waypoints)
            threading.Thread(
                target=ctrl.fly_waypoints,
                args=(validation.waypoints,),
                daemon=True,
            ).start()
            return CommandResult(
                True,
                f"Flying rerouted path via {len(validation.waypoints)} waypoints",
                "waypoints",
            )
        return ctrl.goto_location(
            intent["x"], intent["y"], intent.get("altitude", 10), wait=wait,
        )

    if action == "change_altitude":
        return ctrl.change_altitude(intent["altitude"])
    if action == "land":
        return ctrl.land()
    if action == "hover":
        return ctrl.hover()
    if action == "report_status":
        return ctrl.report_status()
    if action == "fire_missile":
        return ctrl.fire_missile(intent.get("target", "unknown"))
    return None


def _clean_intent(intent: dict) -> dict:
    return {k: v for k, v in intent.items() if k != "original_text"}


# ── Queue Worker ─────────────────────────────────────────────────────────

def _queue_worker(intents: list[dict], ctrl: DroneController):
    """Background thread: execute a sequence of intents one by one."""
    total = len(intents)
    _set_queue_status(state="running", total=total, current=0)

    for idx, intent in enumerate(intents):
        if _queue_cancel.is_set():
            _set_queue_status(state="cancelled")
            entry = {
                "timestamp": datetime.now().isoformat(),
                "intent": _clean_intent(intent),
                "status": "cancelled",
                "feedback": f"Queue cancelled — skipped command {idx + 1}/{total}.",
            }
            command_log.append(entry)
            return

        _set_queue_status(current=idx + 1)
        _process_single_intent(intent, ctrl, wait_for_move=True)

    _set_queue_status(state="idle", total=0, current=0, commands=[])


# ── Static Frontend ──────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)


# ── API Endpoints ────────────────────────────────────────────────────────

@app.route("/api/listen", methods=["POST"])
def api_listen():
    """Record from the server microphone and return Whisper transcription."""
    _listen_stop.clear()
    try:
        text = listen_and_transcribe(language="en", stop_event=_listen_stop)
        return jsonify({"status": "ok", "text": text})
    except RuntimeError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/listen/stop", methods=["POST"])
def api_listen_stop():
    """Signal an active recording to stop early."""
    _listen_stop.set()
    return jsonify({"status": "ok"})


@app.route("/api/connect", methods=["POST"])
def api_connect():
    """Connect a drone to SITL. Supports multiple drones via drone_id."""
    data = request.json or {}
    connection = data.get("connection", PYMAVLINK_CONNECTION)
    drone_id = data.get("drone_id", "Alpha")
    sysid    = data.get("sysid", None)

    controller = DroneController(connection_string=connection, drone_id=drone_id, sysid=sysid)
    if controller.connect():
        drones[drone_id] = controller
        return jsonify({"status": "connected", "drone_id": drone_id})
    return jsonify({"status": "error", "message": f"Failed to connect drone {drone_id} to SITL"}), 500


@app.route("/api/command", methods=["POST"])
def api_command():
    """Process a voice/text command through the full pipeline.

    Handles both single commands (executed inline) and multi-command
    sequences (queued in a background thread with just-in-time validation).
    Any new command aborts an active queue.
    """
    global _queue_thread

    data = request.json or {}
    drone_id = data.get("drone_id", "Alpha")
    drone = drones.get(drone_id)
    if not drone or not drone.is_connected():
        return jsonify({"status": "error", "message": f"Drone {drone_id} not connected. Connect first."}), 400

    text = data.get("text", "").strip()
    if not text:
        return jsonify({"status": "error", "message": "No command text provided."}), 400

    # Abort any running queue — operator override
    _cancel_active_queue()

    # Parse (now returns a list)
    intents = parse_command(text)

    if len(intents) == 1:
        # Single command — process inline, return result directly
        entry = _process_single_intent(intents[0], drone)
        entry["text"] = text
        return jsonify(entry)

    # Multi-command sequence — queue in background
    summaries = []
    for intent in intents:
        action = intent.get("action", "?")
        loc = intent.get("location", "")
        summaries.append(f"{action}" + (f" {loc}" if loc else ""))

    _set_queue_status(
        state="running",
        total=len(intents),
        current=0,
        commands=summaries,
    )

    _queue_thread = threading.Thread(
        target=_queue_worker,
        args=(intents, drone),
        daemon=True,
    )
    _queue_thread.start()

    return jsonify({
        "status": "queued",
        "text": text,
        "queue_size": len(intents),
        "commands": summaries,
        "feedback": f"Queue started: {len(intents)} commands — "
                    + ", ".join(summaries) + ".",
    })


@app.route("/api/queue")
def api_queue():
    """Current command queue state."""
    with _queue_lock:
        return jsonify(dict(_queue_status))


@app.route("/api/status")
def api_status():
    """Current drone state snapshot. Accepts ?drone=<drone_id> (default: Alpha)."""
    drone_id = request.args.get("drone", "Alpha")
    drone = drones.get(drone_id)
    if not drone or not drone.is_connected():
        return jsonify({"connected": False, "drone_id": drone_id})
    pos = drone.get_position()
    state = drone.get_state()
    return jsonify({**pos, **state, "connected": True, "drone_id": drone_id})


@app.route("/api/telemetry")
def api_telemetry():
    """SSE stream of drone telemetry at ~4Hz. Accepts ?drone=<drone_id> (default: Alpha)."""
    drone_id = request.args.get("drone", "Alpha")

    def generate():
        while True:
            d = drones.get(drone_id)
            if d and d.is_connected():
                pos = d.get_position()
                state = d.get_state()
                data = json.dumps({**pos, **state, "connected": True, "drone_id": drone_id})
            else:
                data = json.dumps({"connected": False, "drone_id": drone_id})
            yield f"data: {data}\n\n"
            time.sleep(0.25)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/command-log")
def api_command_log():
    """Return full command history."""
    return jsonify(command_log)


# ── Main ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Calibrating microphone...")
    try:
        from voice_input.recorder import _calibrate
        _calibrate()  # warm up mic and cache threshold before any user interaction
    except Exception as e:
        print(f"  Mic calibration warning: {e} (will retry on first use)")

    print("╔══════════════════════════════════════════════╗")
    print("║  Voice Drone Operations Command Center       ║")
    print("║  Open http://localhost:5000 in your browser   ║")
    print("╚══════════════════════════════════════════════╝")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
