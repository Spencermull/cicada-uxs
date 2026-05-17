#!/usr/bin/env python3
"""
Drone Controller — wraps pymavlink into a thread-safe class with
background telemetry streaming and non-blocking command execution.
"""

import math
import threading
import time
from dataclasses import dataclass, field

from pymavlink import mavutil

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from challenge.config import (
    PYMAVLINK_CONNECTION, latlon_to_local, local_to_latlon, distance_2d,
)

# SITL HOME is at compound center (0, 0) per launch_sitl.sh -l flag.
# LOCAL_NED origin = compound center, so ENU coords map directly to NED.


@dataclass
class CommandResult:
    success: bool
    message: str
    action: str = ""


class DroneController:
    """Thread-safe pymavlink drone controller with background telemetry."""

    def __init__(self, connection_string: str = PYMAVLINK_CONNECTION, drone_id: str = "Alpha",
                 sysid: int = None):
        self.connection_string = connection_string
        self.drone_id = drone_id
        self.sysid = sysid  # MAVLink system ID — used to filter the right SITL on multicast
        self.mav = None
        self._lock = threading.Lock()
        self._telem_thread: threading.Thread | None = None
        self._running = False

        # Current state (updated by telemetry thread)
        self._position = {"x": -40.0, "y": 0.0, "alt": 0.0,
                          "lat": 0.0, "lon": 0.0, "heading": 0.0}
        self._state = {"armed": False, "mode": "UNKNOWN", "battery": 100,
                       "gps_fix": False, "connected": False}

        # Target tracking
        self._target = None  # {"x": ..., "y": ..., "alt": ...}
        self._target_reached = threading.Event()
        self._arrival_radius = 5.0
        self._arrival_alt_tolerance = 3.0

        # Command log
        self.command_log = []

    # ── Connection ──────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Connect to SITL via pymavlink multicast."""
        try:
            self.mav = mavutil.mavlink_connection(self.connection_string)

            if self.sysid is not None:
                # Multicast: wait for heartbeat from the specific SITL instance
                deadline = time.time() + 15
                found = False
                while time.time() < deadline:
                    msg = self.mav.recv_match(type="HEARTBEAT", blocking=True, timeout=2)
                    if msg and msg.get_srcSystem() == self.sysid:
                        self.mav.target_system    = self.sysid
                        self.mav.target_component = msg.get_srcComponent()
                        found = True
                        break
                if not found:
                    return False
            else:
                self.mav.wait_heartbeat(timeout=15)

            self._state["connected"] = True

            # Request telemetry streams
            self.mav.mav.request_data_stream_send(
                self.mav.target_system, self.mav.target_component,
                mavutil.mavlink.MAV_DATA_STREAM_ALL, 4, 1)

            # Wait for GPS fix
            self._wait_gps()

            # Start background telemetry
            self._running = True
            self._telem_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
            self._telem_thread.start()

            return True
        except Exception as e:
            self._state["connected"] = False
            return False

    def _wait_gps(self):
        """Block until GPS has a 3D fix from our target system."""
        for _ in range(30):
            msg = self.mav.recv_match(type="GPS_RAW_INT", blocking=True, timeout=5)
            if msg and msg.get_srcSystem() == self.mav.target_system and msg.fix_type >= 3:
                self._state["gps_fix"] = True
                return
        self._state["gps_fix"] = False

    def disconnect(self):
        self._running = False
        if self._telem_thread:
            self._telem_thread.join(timeout=3)
        self._state["connected"] = False

    # ── Telemetry Thread ────────────────────────────────────────────────

    def _telemetry_loop(self):
        """Background thread: continuously read position and state."""
        while self._running:
            try:
                msg = self.mav.recv_match(
                    type=["GLOBAL_POSITION_INT", "HEARTBEAT", "SYS_STATUS"],
                    blocking=True, timeout=1)
                if not msg:
                    continue

                mtype = msg.get_type()

                if mtype == "GLOBAL_POSITION_INT":
                    if msg.get_srcSystem() != self.mav.target_system:
                        continue
                    lat = msg.lat / 1e7
                    lon = msg.lon / 1e7
                    alt = msg.relative_alt / 1000.0
                    heading = msg.hdg / 100.0
                    x_enu, y_enu = latlon_to_local(lat, lon)

                    with self._lock:
                        self._position.update({
                            "x": round(x_enu, 2), "y": round(y_enu, 2),
                            "alt": round(alt, 2),
                            "lat": round(lat, 7), "lon": round(lon, 7),
                            "heading": round(heading, 1),
                        })

                    # Check if we've arrived at target
                    if self._target and not self._target_reached.is_set():
                        dx = x_enu - self._target["x"]
                        dy = y_enu - self._target["y"]
                        hdist = math.sqrt(dx*dx + dy*dy)
                        vdist = abs(alt - self._target["alt"])
                        if hdist < self._arrival_radius and vdist < self._arrival_alt_tolerance:
                            self._target_reached.set()

                elif mtype == "HEARTBEAT" and msg.get_srcSystem() == self.mav.target_system:
                    mode = mavutil.mode_string_v10(msg)
                    armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                    with self._lock:
                        self._state["mode"] = mode
                        self._state["armed"] = armed

                elif mtype == "SYS_STATUS":
                    if msg.get_srcSystem() != self.mav.target_system:
                        continue
                    with self._lock:
                        self._state["battery"] = msg.battery_remaining

            except Exception:
                time.sleep(0.1)

    # ── State Getters ───────────────────────────────────────────────────

    def get_position(self) -> dict:
        with self._lock:
            return dict(self._position)

    def get_state(self) -> dict:
        with self._lock:
            return dict(self._state)

    def is_connected(self) -> bool:
        return self._state.get("connected", False)

    # ── ENU ↔ NED Conversion ───────────────────────────────────────────

    @staticmethod
    def enu_to_ned(target_x_enu: float, target_y_enu: float, altitude: float):
        """Convert compound ENU target to NED. Origin = compound center for both frames."""
        north = target_y_enu   # ENU y = NED north
        east = target_x_enu    # ENU x = NED east
        down = -altitude        # NED down = negative altitude
        return north, east, down

    # ── Commands ────────────────────────────────────────────────────────

    def _send_goto_ned(self, north: float, east: float, down: float):
        """Send a position target in local NED frame. Thread-safe."""
        with self._lock:
            self.mav.mav.set_position_target_local_ned_send(
                0, self.mav.target_system, self.mav.target_component,
                mavutil.mavlink.MAV_FRAME_LOCAL_NED,
                0b0000111111111000,  # position only
                north, east, down,
                0, 0, 0, 0, 0, 0, 0, 0)

    def _set_yaw_toward(self, target_x_enu: float, target_y_enu: float):
        """Command the drone to face toward a target ENU position."""
        pos = self.get_position()
        dx = target_x_enu - pos["x"]
        dy = target_y_enu - pos["y"]
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            return  # too close, skip yaw
        # atan2 gives angle from East axis; convert to compass heading (from North, CW)
        heading_deg = (90.0 - math.degrees(math.atan2(dy, dx))) % 360.0
        with self._lock:
            self.mav.mav.command_long_send(
                self.mav.target_system, self.mav.target_component,
                mavutil.mavlink.MAV_CMD_CONDITION_YAW,
                0,
                heading_deg,  # target heading in degrees
                25,           # degrees/sec rotation speed
                1,            # 1 = clockwise, -1 = counter-clockwise
                0,            # 0 = absolute angle
                0, 0, 0)

    def _wait_for_arrival(self, timeout: float = 60.0) -> bool:
        """Block until the drone reaches the current target or timeout."""
        return self._target_reached.wait(timeout=timeout)

    def takeoff(self, altitude: float = 10.0) -> CommandResult:
        """Arm, set GUIDED mode, and take off to altitude."""
        try:
            # Set GUIDED mode
            mode_id = self.mav.mode_mapping().get("GUIDED")
            if mode_id is None:
                return CommandResult(False, "GUIDED mode not available", "takeoff")
            with self._lock:
                self.mav.set_mode(mode_id)
            time.sleep(0.5)

            # Arm
            with self._lock:
                self.mav.arducopter_arm()
                self.mav.motors_armed_wait()
            time.sleep(0.5)

            # Takeoff command
            with self._lock:
                self.mav.mav.command_long_send(
                    self.mav.target_system, self.mav.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                    0, 0, 0, 0, 0, 0, 0, altitude)

            # Set target for arrival monitoring
            pos = self.get_position()
            self._target = {"x": pos["x"], "y": pos["y"], "alt": altitude}
            self._target_reached.clear()

            return CommandResult(True, f"Taking off to {altitude}m", "takeoff")
        except Exception as e:
            return CommandResult(False, f"Takeoff failed: {e}", "takeoff")

    def goto_location(self, x_enu: float, y_enu: float, altitude: float,
                      wait: bool = False) -> CommandResult:
        """Fly to absolute ENU coordinates at given altitude."""
        try:
            # Point the nose toward the target
            self._set_yaw_toward(x_enu, y_enu)
            time.sleep(0.3)

            north, east, down = self.enu_to_ned(x_enu, y_enu, altitude)
            self._send_goto_ned(north, east, down)

            # Set target for arrival monitoring
            self._target = {"x": x_enu, "y": y_enu, "alt": altitude}
            self._target_reached.clear()

            # Start re-send thread to keep the command active
            threading.Thread(
                target=self._resend_loop, args=(north, east, down),
                daemon=True
            ).start()

            if wait:
                self._wait_for_arrival(timeout=120)

            return CommandResult(
                True,
                f"Flying to ({x_enu:.1f}, {y_enu:.1f}) at {altitude:.0f}m",
                "goto"
            )
        except Exception as e:
            return CommandResult(False, f"Goto failed: {e}", "goto")

    def fly_waypoints(self, waypoints: list) -> CommandResult:
        """
        Fly through a sequence of (x, y, alt) waypoints, waiting for
        arrival at each before proceeding to the next.
        """
        if not waypoints:
            return CommandResult(False, "No waypoints provided", "waypoints")

        for i, (wx, wy, walt) in enumerate(waypoints):
            result = self.goto_location(wx, wy, walt, wait=True)
            if not result.success:
                result.message = f"Waypoint {i+1}/{len(waypoints)} failed: {result.message}"
                return result

        return CommandResult(
            True,
            f"Completed {len(waypoints)}-waypoint route",
            "waypoints"
        )

    def goto_relative(self, direction: str, distance: float,
                      altitude: float | None = None) -> CommandResult:
        """Fly a relative direction/distance from current position."""
        pos = self.get_position()
        cur_x, cur_y = pos["x"], pos["y"]
        alt = altitude if altitude is not None else pos["alt"]

        direction_map = {
            "north": (0, 1), "south": (0, -1),
            "east": (1, 0), "west": (-1, 0),
            "northeast": (0.707, 0.707), "northwest": (-0.707, 0.707),
            "southeast": (0.707, -0.707), "southwest": (-0.707, -0.707),
        }
        dx, dy = direction_map.get(direction.lower(), (0, 0))
        target_x = cur_x + dx * distance
        target_y = cur_y + dy * distance

        return self.goto_location(target_x, target_y, alt)

    def change_altitude(self, new_alt: float) -> CommandResult:
        """Change altitude while maintaining current horizontal position."""
        pos = self.get_position()
        return self.goto_location(pos["x"], pos["y"], new_alt)

    def land(self) -> CommandResult:
        """Switch to LAND mode."""
        try:
            mode_id = self.mav.mode_mapping().get("LAND")
            if mode_id is None:
                return CommandResult(False, "LAND mode not available", "land")
            with self._lock:
                self.mav.set_mode(mode_id)

            self._target = None
            return CommandResult(True, "Landing", "land")
        except Exception as e:
            return CommandResult(False, f"Land failed: {e}", "land")

    def hover(self) -> CommandResult:
        """Hold current position (re-send current pos as target)."""
        pos = self.get_position()
        return self.goto_location(pos["x"], pos["y"], pos["alt"])

    def fire_missile(self, target: str) -> CommandResult:
        """Simulate a missile fire event (logged, no physical effect in sim)."""
        return CommandResult(True, f"Missile fired at {target} [SIMULATED]", "fire_missile")

    def report_status(self) -> CommandResult:
        """Return current position and state as feedback."""
        pos = self.get_position()
        state = self.get_state()
        msg = (f"Position: ({pos['x']:.1f}, {pos['y']:.1f}) at {pos['alt']:.1f}m AGL. "
               f"Heading {pos['heading']:.0f}°. Mode: {state['mode']}. "
               f"{'Armed' if state['armed'] else 'Disarmed'}. "
               f"Battery: {state['battery']}%.")
        return CommandResult(True, msg, "report_status")

    # ── Re-send Loop ────────────────────────────────────────────────────

    def _resend_loop(self, north: float, east: float, down: float):
        """Re-send position target every 2s until arrival or new command."""
        target_ref = self._target
        for _ in range(60):  # Max 2 minutes
            if self._target_reached.is_set() or self._target is not target_ref:
                return
            time.sleep(2)
            try:
                self._send_goto_ned(north, east, down)
            except Exception:
                return
