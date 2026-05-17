#!/usr/bin/env python3
"""
Command Validator — every parsed command passes through here before execution.
Checks no-go zones, flight path, IFF, impossible actions, and state feasibility.
"""

import json
import os
import sys
from dataclasses import dataclass, field

from pathfinder import path_clear_2d, plan_path, segment_intersects_circle, ThreatZone, zones_from_config

# challenge package lives at the project root (two levels up from this file)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from challenge.config import distance_2d, NO_GO_ZONES

# Build threat model once from config
_THREATS: list[ThreatZone] = zones_from_config(NO_GO_ZONES)


@dataclass
class ValidationResult:
    approved: bool
    reason: str
    suggestion: str
    # Populated when ARA* reroutes around a blocked direct path.
    # Each tuple is (x, y, alt) in ENU metres.
    waypoints: list[tuple[float, float, float]] = field(default_factory=list)
    path_quality: str = ""   # e.g. "≤2.0× optimal (time-bounded)"


# ── Location Resolution ─────────────────────────────────────────────────

@dataclass
class LocationInfo:
    name: str
    x: float
    y: float
    default_alt: float


# All named locations in the compound, mapping natural-language names to ENU coords
# Coordinates come from challenge/config.py waypoints and CLAUDE.md compound layout
LOCATIONS = {
    # Waypoints from config.py
    "landing pad":              LocationInfo("Landing Pad", -40, 0, 10),
    "launch pad":               LocationInfo("Landing Pad", -40, 0, 10),
    "pad":                      LocationInfo("Landing Pad", -40, 0, 10),
    "home":                     LocationInfo("Landing Pad", -40, 0, 10),
    "west gate":                LocationInfo("West Gate", -60, 0, 3),
    "gate":                     LocationInfo("West Gate", -60, 0, 3),
    "northwest tower":          LocationInfo("NW Tower", -57, 37, 12),
    "northwest watch tower":    LocationInfo("NW Tower", -57, 37, 12),
    "nw tower":                 LocationInfo("NW Tower", -57, 37, 12),
    "northeast tower":          LocationInfo("NE Tower", 57, 37, 12),
    "northeast watch tower":    LocationInfo("NE Tower", 57, 37, 12),
    "ne tower":                 LocationInfo("NE Tower", 57, 37, 12),
    "southeast tower":          LocationInfo("SE Tower", 57, -37, 12),
    "southeast watch tower":    LocationInfo("SE Tower", 57, -37, 12),
    "se tower":                 LocationInfo("SE Tower", 57, -37, 12),
    "southwest tower":          LocationInfo("SW Tower", -57, -37, 12),
    "southwest watch tower":    LocationInfo("SW Tower", -57, -37, 12),
    "sw tower":                 LocationInfo("SW Tower", -57, -37, 12),
    "command building":         LocationInfo("Command Building", 20, 10, 12),
    "command center":           LocationInfo("Command Building", 20, 10, 12),
    "rooftop":                  LocationInfo("Rooftop", 25, 14, 12),
    "roof":                     LocationInfo("Rooftop", 25, 14, 12),
    "barracks 1":               LocationInfo("Barracks 1", -20, 25, 8),
    "barracks one":             LocationInfo("Barracks 1", -20, 25, 8),
    "north barracks":           LocationInfo("Barracks 1", -20, 25, 8),
    "barracks 2":               LocationInfo("Barracks 2", -20, -25, 8),
    "barracks two":             LocationInfo("Barracks 2", -20, -25, 8),
    "south barracks":           LocationInfo("Barracks 2", -20, -25, 8),
    "barracks":                 LocationInfo("Barracks 1", -20, 25, 8),
    "motor pool":               LocationInfo("Motor Pool", 38, -20, 3),
    "container":                LocationInfo("Containers", 1.5, -16.5, 8),
    "containers":               LocationInfo("Containers", 1.5, -16.5, 8),
    "shipping containers":      LocationInfo("Containers", 1.5, -16.5, 8),
    "comms tower":              LocationInfo("Comms Tower", 40, 30, 30),
    "communications tower":     LocationInfo("Comms Tower", 40, 30, 30),
    "comm tower":               LocationInfo("Comms Tower", 40, 30, 30),
    "fuel depot":               LocationInfo("Fuel Depot", -27, -32, 10),
    # Missile rack / weapons
    "missile rack":             LocationInfo("Missile Rack", 42, -18, 8),
    "hellfire rack":            LocationInfo("Missile Rack", 42, -18, 8),
    "weapons depot":            LocationInfo("Missile Rack", 42, -18, 8),
    "weapons rack":             LocationInfo("Missile Rack", 42, -18, 8),
    # Ground vehicle positions
    "cobra-6":                  LocationInfo("Cobra-6 Position", 35, -22, 8),
    "cobra 6":                  LocationInfo("Cobra-6 Position", 35, -22, 8),
    "ghost-7":                  LocationInfo("Ghost-7 Position", -55, 5, 8),
    "ghost 7":                  LocationInfo("Ghost-7 Position", -55, 5, 8),
}


def resolve_location(name: str) -> LocationInfo | None:
    """Resolve a natural-language location name to coordinates."""
    key = name.lower().strip()
    if key in LOCATIONS:
        return LOCATIONS[key]
    # Fuzzy: check if any key is contained in the input
    for loc_key, loc in LOCATIONS.items():
        if loc_key in key or key in loc_key:
            return loc
    return None


# ── IFF ──────────────────────────────────────────────────────────────────

IFF_CONTACTS = []
_iff_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "iff_contacts.json")
if os.path.exists(_iff_path):
    with open(_iff_path) as f:
        IFF_CONTACTS = json.load(f).get("contacts", [])


def check_iff(target_name: str) -> dict | None:
    """Look up an entity in the IFF list. Returns contact dict or None."""
    for contact in IFF_CONTACTS:
        if contact["callsign"].lower() == target_name.lower():
            return contact
    return None


# ── Impossible Actions ───────────────────────────────────────────────────

IMPOSSIBLE_KEYWORDS = {
    "self-destruct", "self destruct", "selfdestruct",
    "shoot", "eject", "detonate", "bomb", "attack", "destroy",
    "turn off engines", "shut down engines", "kill engines",
    "kamikaze", "ram",
}


# ── Validation ───────────────────────────────────────────────────────────

def validate(intent: dict, current_pos: dict) -> ValidationResult:
    """
    Validate a parsed command intent against all safety rules.

    Args:
        intent: Parsed command dict with 'action' key and action-specific fields.
        current_pos: Current drone position dict with 'x', 'y', 'alt' keys.

    Returns:
        ValidationResult with approved/rejected status and reasoning.
    """
    action = intent.get("action", "")

    # 1. LLM already flagged impossible
    if action == "reject_impossible":
        return ValidationResult(
            False,
            intent.get("reason", "Impossible action"),
            "Please issue a valid drone command."
        )

    # 2. Keyword-based impossible action check (backup for LLM)
    original_text = intent.get("original_text", "").lower()
    for keyword in IMPOSSIBLE_KEYWORDS:
        if keyword in original_text:
            return ValidationResult(
                False,
                f"'{keyword}' is not a valid drone action",
                "Available actions: fly, takeoff, land, hover, report status."
            )

    # 3. Report status is always OK
    if action == "report_status":
        return ValidationResult(True, "Status report approved", "")

    # 4. Hover is always OK if airborne
    if action == "hover":
        if current_pos.get("alt", 0) < 0.5:
            return ValidationResult(False, "Drone is on the ground", "Take off first.")
        return ValidationResult(True, "Hover approved", "")

    # 5. Altitude bounds
    alt = intent.get("altitude")
    if alt is not None:
        if alt < 0:
            return ValidationResult(False, "Cannot fly below ground level", "Minimum altitude is 0m.")
        if alt > 120:
            return ValidationResult(False, "Altitude exceeds safe operating ceiling", "Maximum is 120m AGL.")

    # 6. Takeoff checks
    if action == "takeoff":
        if current_pos.get("alt", 0) > 2:
            return ValidationResult(False, "Already airborne", "Use altitude change instead.")
        return ValidationResult(True, "Takeoff approved", "")

    # 7. Land is always OK if airborne
    if action == "land":
        return ValidationResult(True, "Landing approved", "")

    # 8. Must be airborne for movement commands
    if action in ("goto", "move_relative", "change_altitude"):
        if current_pos.get("alt", 0) < 0.5 and action != "change_altitude":
            return ValidationResult(False, "Drone is on the ground", "Take off first.")

    # 9. No-go zone check — destination point (analytic, exact)
    target_x = intent.get("x")
    target_y = intent.get("y")
    if target_x is not None and target_y is not None:
        target_alt = intent.get("altitude") or current_pos.get("alt", 10)

        # Destination check uses the altitude the drone WILL BE at when it arrives
        for zone in NO_GO_ZONES:
            dist = distance_2d(target_x, target_y, zone.x, zone.y)
            if dist < zone.radius and target_alt < zone.alt_ceil:
                if zone.alt_ceil == float("inf"):
                    return ValidationResult(
                        False,
                        f"No-go zone: {zone.name} — destination is inside a permanently restricted area",
                        f"Choose a destination outside the {zone.name} perimeter."
                    )
                else:
                    return ValidationResult(
                        False,
                        f"No-go zone: {zone.name} — destination is inside restricted airspace below {zone.alt_ceil}m AGL",
                        f"Increase altitude above {zone.alt_ceil}m or choose a different destination."
                    )

    # 10. Path check — analytic line-circle intersection + ARA* rerouting
    if target_x is not None and target_y is not None:
        cur_x = current_pos.get("x", -40)
        cur_y = current_pos.get("y", 0)
        cur_alt = current_pos.get("alt", 10)
        target_alt = intent.get("altitude") or cur_alt
        # Conservative: check path at lowest altitude during transit
        flight_alt = min(cur_alt, target_alt)

        direct_clear = path_clear_2d(cur_x, cur_y, target_x, target_y, flight_alt, _THREATS)

        if not direct_clear:
            # Direct path is blocked — invoke ARA* to find a safe route
            result = plan_path(
                cur_x, cur_y, current_pos.get("alt", 10),
                target_x, target_y, target_alt,
                _THREATS,
            )

            if not result.found:
                return ValidationResult(
                    False,
                    "Flight path passes through a no-go zone and no safe alternative route exists",
                    "No navigable path to that destination under current threat conditions."
                )

            # Approved with rerouted waypoints
            return ValidationResult(
                True,
                f"Direct path blocked — ARA* reroute computed ({result.quality})",
                f"Flying via {len(result.waypoints)} waypoints at {result.safe_alt:.0f}m AGL to avoid restricted zones.",
                waypoints=result.waypoints,
                path_quality=result.quality,
            )

    # 11. IFF check for engagement commands
    if action == "identify":
        target_name = intent.get("target", "")
        contact = check_iff(target_name)
        if contact:
            if contact["classification"] == "FRIENDLY":
                return ValidationResult(
                    False,
                    f"{target_name} is classified FRIENDLY — engagement prohibited",
                    "Cannot engage friendly forces."
                )
        return ValidationResult(True, f"IFF check passed for {target_name}", "")

    # 12. fire_missile — IFF-gated weapons release
    if action == "fire_missile":
        target = intent.get("target", "")
        contact = check_iff(target)
        if contact:
            if contact["classification"] == "FRIENDLY":
                return ValidationResult(
                    False,
                    f"IFF: {target} is FRIENDLY — weapons hold",
                    "Cannot engage friendly forces."
                )
            if contact["classification"] == "UNKNOWN":
                return ValidationResult(
                    False,
                    f"IFF: {target} is UNKNOWN — weapons hold pending PID",
                    "Confirm target classification before engaging."
                )
        return ValidationResult(True, f"Weapons free on {target}", "")

    return ValidationResult(True, "Command approved", "")
