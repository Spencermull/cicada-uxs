"""
UxS Hackathon — Challenge Configuration

Single source of truth for waypoints, no-go zones, NPC patrols, and coordinate math.
"""

import math
from dataclasses import dataclass

# ── Coordinate Origin (matches compound_ops.sdf <spherical_coordinates>) ────

ORIGIN_LAT = 32.990
ORIGIN_LON = -106.975
ORIGIN_ALT = 1400.0  # meters above sea level

# Meters per degree at this latitude
M_PER_DEG_LAT = 111132.92
M_PER_DEG_LON = 111132.92 * math.cos(math.radians(ORIGIN_LAT))  # ~93,214 m


def local_to_latlon(x_east: float, y_north: float) -> tuple[float, float]:
    """Convert local ENU coordinates (meters) to (lat, lon).

    Gazebo SDF uses ENU: x=east, y=north.
    """
    lat = ORIGIN_LAT + (y_north / M_PER_DEG_LAT)
    lon = ORIGIN_LON + (x_east / M_PER_DEG_LON)
    return lat, lon


def latlon_to_local(lat: float, lon: float) -> tuple[float, float]:
    """Convert (lat, lon) to local ENU coordinates (x_east, y_north) in meters."""
    y_north = (lat - ORIGIN_LAT) * M_PER_DEG_LAT
    x_east = (lon - ORIGIN_LON) * M_PER_DEG_LON
    return x_east, y_north


def distance_2d(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


# ── Waypoints ────────────────────────────────────────────────────────────────

@dataclass
class Waypoint:
    name: str
    x: float           # local East (SDF x), meters
    y: float           # local North (SDF y), meters
    alt_agl: float     # target altitude above ground level, meters
    radius: float      # horizontal acceptance radius, meters
    alt_tolerance: float  # vertical acceptance tolerance, meters
    points: int         # score value
    description: str


WAYPOINTS = [
    # Phase 1: Takeoff & Basic Nav
    Waypoint("LAUNCH", -40, 0, 10, 5.0, 5.0, 10,
             "Take off from landing pad to 10m AGL"),
    Waypoint("GATE", -60, 0, 3, 5.0, 3.0, 25,
             "Fly through west gate below wall height (4m)"),

    # Phase 2: Perimeter Recon
    Waypoint("TOWER_NW", -57, 37, 12, 5.0, 5.0, 15,
             "Overfly NW watch tower"),
    Waypoint("TOWER_NE", 57, 37, 12, 5.0, 5.0, 15,
             "Overfly NE watch tower"),
    Waypoint("TOWER_SE", 57, -37, 12, 5.0, 5.0, 15,
             "Overfly SE watch tower"),
    Waypoint("TOWER_SW", -57, -37, 12, 5.0, 5.0, 15,
             "Overfly SW watch tower"),

    # Phase 3: Interior Operations
    Waypoint("CMD_ROOF", 25, 14, 12, 4.0, 4.0, 30,
             "Hover over command building rooftop structure"),
    Waypoint("CONTAINERS", 1.5, -16.5, 8, 4.0, 4.0, 20,
             "Fly over stacked shipping containers"),
    Waypoint("MOTOR_POOL", 38, -20, 3, 5.0, 3.0, 35,
             "Fly into motor pool bay (under 5m AGL)"),

    # Phase 4: Return
    Waypoint("LAND", -40, 0, 0, 3.0, 2.0, 20,
             "Return and land on the pad"),
]

WAYPOINTS_BY_NAME = {wp.name: wp for wp in WAYPOINTS}
MAX_WAYPOINT_POINTS = sum(wp.points for wp in WAYPOINTS)  # 200


# ── No-Go Zones ──────────────────────────────────────────────────────────────

@dataclass
class NoGoZone:
    name: str
    x: float            # center East, meters
    y: float            # center North, meters
    radius: float       # horizontal exclusion radius, meters
    alt_ceil: float     # safe if above this AGL (float('inf') = never safe)
    penalty_per_sec: int  # points deducted per second inside


NO_GO_ZONES = [
    NoGoZone("FUEL_DEPOT", -27, -32, 10, float("inf"), 50),
    NoGoZone("COMMS_TOWER", 40, 30, 8, 25.0, 30),
]


# ── Scoring Constants ────────────────────────────────────────────────────────

TIME_LIMIT_SECS = 600       # 10 minute mission window
TIME_BONUS_THRESHOLD = 300  # bonus if completed under 5 min
TIME_BONUS_RATE = 0.5       # points per second under threshold
MAX_TIME_BONUS = 150.0
MULTI_VEHICLE_BONUS = 50    # stretch goal bonus



# ── SITL Connection ──────────────────────────────────────────────────────────

# pymavlink multicast — unlimited simultaneous clients
PYMAVLINK_CONNECTION = "mcast:"
