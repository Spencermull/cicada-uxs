#!/usr/bin/env python3
"""
Intent Parser — maps natural language commands to structured JSON actions
using Groq AI, with a regex-based fallback.
"""

import json
import os
import re

from dotenv import load_dotenv

from drone_control import DIRECTION_MAP

# Load .env from this directory (mavsdk-app/src/.env)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

SYSTEM_PROMPT = """You are a military drone command interpreter. You parse spoken commands into structured JSON actions for a drone operating in a military compound.

Available actions:
- takeoff: {"action": "takeoff", "altitude": <meters>}
- land: {"action": "land"}
- goto: {"action": "goto", "location": "<name>", "altitude": <meters or null>}
- move_relative: {"action": "move_relative", "direction": "<north|south|east|west|northeast|northwest|southeast|southwest>", "distance": <meters>, "altitude": <meters or null>}
- change_altitude: {"action": "change_altitude", "altitude": <meters>}
- hover: {"action": "hover"}
- report_status: {"action": "report_status"}
- identify: {"action": "identify", "target": "<entity name>"}
- fire_missile: {"action": "fire_missile", "target": "<callsign or location>"}
- reject_impossible: {"action": "reject_impossible", "reason": "<why this is impossible>"}

Known locations in the compound:
- landing pad (spawn point, also called "home", "launch pad")
- west gate (10m gap in perimeter wall)
- northwest tower / NW tower / northwest watch tower
- northeast tower / NE tower / northeast watch tower
- southeast tower / SE tower / southeast watch tower
- southwest tower / SW tower / southwest watch tower
- command building (main structure)
- rooftop (on top of command building)
- barracks 1 (north barracks)
- barracks 2 (south barracks)
- motor pool (covered bay)
- shipping containers / containers
- comms tower / communications tower (tall antenna mast)
- fuel depot (two cylindrical tanks)
- missile rack / hellfire rack / weapons depot (near motor pool)
- Cobra-6 position (hostile vehicle at motor pool)
- Ghost-7 position (unknown vehicle near gate)

Rules:
1. If the command names a known location, use "goto" with the location name.
2. If the command specifies a relative direction and distance (e.g. "fly north 50 meters"), use "move_relative".
3. If the command only changes altitude (descend, climb, ascend, drop to X meters), use "change_altitude".
4. If the command is physically impossible for a drone (self-destruct, turn off engines mid-flight, eject, kamikaze), use "reject_impossible". NOTE: "fire missile" or "fire at <target>" is a valid fire_missile action — do NOT reject it.
5. If the command asks to fire, launch, or engage a target by callsign, use "fire_missile" with that target.
6. If the command asks for position, status, altitude, or a report, use "report_status".
7. If altitude is mentioned, always extract it as a number. If not mentioned, set altitude to null.
8. Modifier compounds that describe a SINGLE destination with extra detail should be ONE action. Example: "climb to 12 meters and hover over the rooftop" = single goto rooftop at 12m. "Drop to 3 meters and enter the motor pool" = single goto motor pool at 3m.
9. Sequential commands joined by "then", "and then", "after that", "next", or commas listing distinct actions should be MULTIPLE actions in a "commands" array. Example: "go to barracks, then go to command center, then land" = {"commands": [goto barracks, goto command center, land]}.
9. "Head back to", "return to", "go back to" the landing pad means goto landing pad.
10. "Enter the motor pool" or "go into" means goto that location.
11. DO NOT validate whether a command is safe — that is handled separately. Just parse the intent.

Response format:
- Single command: return a JSON object with an "action" key, e.g. {"action": "goto", "location": "barracks 1", "altitude": null}
- Multiple sequential commands: return {"commands": [action1, action2, ...]} where each element is an action object.

Respond with ONLY valid JSON. No markdown, no explanation, no code fences."""


def parse_command(text: str) -> list[dict]:
    """Parse a natural language command into a list of structured intent dicts.

    Always returns a list (length 1 for single commands, >1 for sequences).
    """
    result = _parse_with_groq(text)
    if result is not None:
        intents = _normalize_to_list(result)
        # Groq sometimes ignores the multi-command format and returns a
        # single action for sequential input.  When the text clearly
        # contains sequential keywords but Groq collapsed it into one
        # action, discard its result and let the fallback splitter handle it.
        if len(intents) <= 1 and _has_sequential_keywords(text):
            result = None

    if result is None:
        result = _fallback_parse(text)
    elif isinstance(result, dict) and result.get("action") == "reject_impossible":
        fallback = _fallback_parse(text)
        fb_list = _normalize_to_list(fallback)
        if fb_list and fb_list[0].get("action") == "fire_missile":
            result = fallback

    intents = _normalize_to_list(result)
    for intent in intents:
        intent["original_text"] = text
    return intents


def _normalize_to_list(parsed: dict | list) -> list[dict]:
    """Convert any parser output into a flat list of intent dicts."""
    if isinstance(parsed, list):
        return parsed if parsed else [{"action": "hover"}]
    if "commands" in parsed and isinstance(parsed["commands"], list):
        return parsed["commands"] if parsed["commands"] else [{"action": "hover"}]
    return [parsed]


def _parse_with_groq(text: str) -> dict | None:
    """Call Groq API for intent parsing."""
    if not GROQ_API_KEY:
        return None
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception:
        return None


# ── Regex Fallback Parser ────────────────────────────────────────────────

def _extract_number(text: str) -> float | None:
    """Extract the first number from text."""
    match = re.search(r'(\d+(?:\.\d+)?)\s*(?:meters?|m\b)', text)
    if match:
        return float(match.group(1))
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    if match:
        return float(match.group(1))
    return None


_SEQ_SPLIT = re.compile(
    r',?\s*(?:and\s+then|then|after\s+that|next)\s+',
    re.IGNORECASE,
)


def _has_sequential_keywords(text: str) -> bool:
    return bool(_SEQ_SPLIT.search(text))


def _fallback_parse(text: str) -> dict | list[dict]:
    """Regex-based parser. Splits on sequential keywords first."""
    segments = _SEQ_SPLIT.split(text)
    segments = [s.strip() for s in segments if s.strip()]
    if len(segments) > 1:
        return [_fallback_parse_single(s) for s in segments]
    return _fallback_parse_single(text)


def _fallback_parse_single(text: str) -> dict:
    """Parse a single (non-compound) command segment."""
    t = text.lower().strip()

    # Impossible actions
    impossible = ["self-destruct", "self destruct",
                  "shoot", "eject", "detonate", "bomb", "destroy", "kamikaze"]
    for word in impossible:
        if word in t:
            return {"action": "reject_impossible", "reason": f"'{word}' is not a valid drone action"}

    # Fire missile — must come before impossible / goto checks
    fire_patterns = [
        r'fire\s+(?:missile\s+at\s+|at\s+)?([a-z0-9\-]+(?:\s+[a-z0-9\-]+)?)',
        r'launch\s+(?:missile\s+at\s+|at\s+)?([a-z0-9\-]+(?:\s+[a-z0-9\-]+)?)',
        r'engage\s+([a-z0-9\-]+(?:\s+[a-z0-9\-]+)?)',
    ]
    for pat in fire_patterns:
        m = re.search(pat, t)
        if m:
            return {"action": "fire_missile", "target": m.group(1).strip()}

    # Takeoff
    if "take off" in t or "takeoff" in t:
        alt = _extract_number(t)
        return {"action": "takeoff", "altitude": alt or 10}

    # Land
    if t.startswith("land"):
        return {"action": "land"}

    # Report status
    if any(w in t for w in ["report", "status", "position", "where am i", "altitude"]):
        return {"action": "report_status"}

    # Hover
    if "hover" in t and not any(loc in t for loc in ["over", "above"]):
        return {"action": "hover"}

    # Change altitude only
    alt_only = re.match(
        r'(?:descend|climb|ascend|drop|go up|go down|change altitude)\s+(?:to\s+)?(\d+(?:\.\d+)?)\s*(?:meters?|m)?',
        t
    )
    if alt_only:
        return {"action": "change_altitude", "altitude": float(alt_only.group(1))}

    # Relative movement: "fly north 50 meters"
    for d in DIRECTION_MAP:
        pattern = rf'(?:fly|go|move|head)\s+{d}\s+(\d+(?:\.\d+)?)\s*(?:meters?|m)?'
        match = re.search(pattern, t)
        if match:
            return {"action": "move_relative", "direction": d,
                    "distance": float(match.group(1)), "altitude": None}

    # Named location goto
    location_keywords = [
        "landing pad", "launch pad", "pad", "home",
        "west gate", "gate",
        "northwest tower", "northwest watch tower", "nw tower",
        "northeast tower", "northeast watch tower", "ne tower",
        "southeast tower", "southeast watch tower", "se tower",
        "southwest tower", "southwest watch tower", "sw tower",
        "command building", "command center",
        "rooftop", "roof",
        "barracks 1", "barracks 2", "north barracks", "south barracks", "barracks",
        "motor pool", "container", "containers", "shipping containers",
        "comms tower", "communications tower", "comm tower",
        "fuel depot",
        "missile rack", "hellfire rack", "weapons depot", "weapons rack",
        "cobra-6", "cobra 6", "ghost-7", "ghost 7",
    ]
    alt = _extract_number(t)
    for loc in sorted(location_keywords, key=len, reverse=True):
        if loc in t:
            return {"action": "goto", "location": loc, "altitude": alt}

    # Generic goto with altitude — strip verb prefixes so the location
    # resolver sees a clean name (e.g. "barracks" not "go to barracks")
    _goto_prefixes = ["fly to", "go to", "head to", "return to",
                      "head back to", "go back to", "head back", "go back"]
    for pfx in _goto_prefixes:
        if t.startswith(pfx):
            loc = t[len(pfx):].strip().rstrip(",")
            if loc:
                return {"action": "goto", "location": loc, "altitude": alt}

    # Default: try to interpret as goto
    return {"action": "goto", "location": t, "altitude": alt}
