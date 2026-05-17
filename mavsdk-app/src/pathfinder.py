#!/usr/bin/env python3
"""
ARA* (Anytime Repairing A*) Path Planner — military-grade drone routing.

Features:
  - Analytic line-circle intersection (exact, not sampled)
  - Risk-weighted cost function (Gaussian threat envelopes)
  - ARA* with epsilon annealing: returns ε-suboptimal path immediately,
    improves toward optimal within a fixed time budget
  - String-pulling smoothing to reduce unnecessary intermediate waypoints
  - 3D altitude selection: chooses minimum safe altitude to clear all threats

Quality guarantee: any returned path costs ≤ ε × optimal_path_cost.
"""

import heapq
import math
import time
from dataclasses import dataclass

# ── Grid Parameters ──────────────────────────────────────────────────────────

GRID_RES = 2.0          # metres per cell
X_MIN, X_MAX = -75, 75  # ENU East bounds (metres)
Y_MIN, Y_MAX = -55, 55  # ENU North bounds (metres)

COLS = int((X_MAX - X_MIN) / GRID_RES)   # 75
ROWS = int((Y_MAX - Y_MIN) / GRID_RES)   # 55

# ── Planner Parameters ───────────────────────────────────────────────────────

RISK_WEIGHT    = 40.0   # penalty weight for Gaussian threat exposure per cell
EPS_INIT       = 3.0    # initial suboptimality bound (fast, ≤3× optimal)
EPS_FINAL      = 1.0    # terminal bound (optimal)
EPS_STEP       = 0.5    # decrement per ARA* iteration
TIME_BUDGET    = 0.20   # seconds total planning time budget
ALT_MARGIN     = 5.0    # metres added above a zone's alt_ceil when going over
SAFETY_MARGIN  = 3.0    # metres added to zone radius for flight dynamics buffer


# ── Threat Model ─────────────────────────────────────────────────────────────

@dataclass
class ThreatZone:
    name: str
    x: float        # ENU East centre
    y: float        # ENU North centre
    radius: float   # hard exclusion radius (metres)
    alt_ceil: float # safe if alt ≥ alt_ceil; float('inf') = never safe


def zones_from_config(no_go_zones) -> list[ThreatZone]:
    """Convert challenge.config NoGoZone objects to ThreatZone dataclasses."""
    return [
        ThreatZone(z.name, z.x, z.y, z.radius, z.alt_ceil)
        for z in no_go_zones
    ]


# ── Coordinate Helpers ────────────────────────────────────────────────────────

def _w2g(wx: float, wy: float) -> tuple[int, int]:
    """World (metres) → grid cell, clamped to grid bounds."""
    gx = int((wx - X_MIN) / GRID_RES)
    gy = int((wy - Y_MIN) / GRID_RES)
    return max(0, min(COLS - 1, gx)), max(0, min(ROWS - 1, gy))


def _g2w(gx: int, gy: int) -> tuple[float, float]:
    """Grid cell centre → world (metres)."""
    return X_MIN + (gx + 0.5) * GRID_RES, Y_MIN + (gy + 0.5) * GRID_RES


# ── Altitude Selection ────────────────────────────────────────────────────────

def choose_safe_altitude(
    start_alt: float,
    goal_alt: float,
    threats: list[ThreatZone],
    start_x: float = 0.0, start_y: float = 0.0,
    goal_x: float = 0.0, goal_y: float = 0.0,
) -> float:
    """
    Choose the minimum altitude that clears finite-ceiling threat zones
    that are actually near the flight corridor.  Only bumps altitude for
    zones whose centre is within (radius + corridor_margin) of the
    start→goal line segment.  Zones with alt_ceil=inf must be navigated
    around, not over.
    """
    alt = max(start_alt, goal_alt)
    corridor_margin = 30.0  # metres — how close a zone must be to matter
    for t in threats:
        if t.alt_ceil == float("inf"):
            continue
        # Only bump altitude if this zone is near the flight corridor
        if segment_intersects_circle(
            start_x, start_y, goal_x, goal_y,
            t.x, t.y, t.radius + corridor_margin,
        ):
            alt = max(alt, t.alt_ceil + ALT_MARGIN)
    return alt


# ── Threat Cost ───────────────────────────────────────────────────────────────

def _threat_cost(wx: float, wy: float, alt: float, threats: list[ThreatZone]) -> float:
    """
    Per-cell risk cost.  Returns inf for hard-blocked cells (inside exclusion
    radius and below alt_ceil).  Otherwise returns a Gaussian soft-cost that
    penalises proximity to threat centres — simulating a radar detection envelope.
    """
    cost = 0.0
    for t in threats:
        d = math.hypot(wx - t.x, wy - t.y)
        # Hard block — includes safety margin for flight dynamics buffer
        if d < t.radius + SAFETY_MARGIN and alt < t.alt_ceil:
            return float("inf")
        # Soft Gaussian envelope — effective range ≈ 3× radius
        sigma = t.radius * 1.5
        cost += RISK_WEIGHT * math.exp(-0.5 * (d / sigma) ** 2)
    return cost


# Cache risk values — grid and safe_alt are fixed within one planning call.
_risk_cache: dict = {}
_risk_cache_alt: float = -999.0


def _get_risk(gx: int, gy: int, alt: float, threats: list[ThreatZone]) -> float:
    global _risk_cache, _risk_cache_alt
    if alt != _risk_cache_alt:
        _risk_cache = {}
        _risk_cache_alt = alt
    key = (gx, gy)
    if key not in _risk_cache:
        wx, wy = _g2w(gx, gy)
        _risk_cache[key] = _threat_cost(wx, wy, alt, threats)
    return _risk_cache[key]


# ── A* Helpers ────────────────────────────────────────────────────────────────

_MOVES = (
    (-1,  0, 1.0),  (1,  0, 1.0),   # cardinal
    ( 0, -1, 1.0),  (0,  1, 1.0),
    (-1, -1, 1.414), (-1, 1, 1.414), # diagonal
    ( 1, -1, 1.414), ( 1, 1, 1.414),
)


def _neighbours(gx: int, gy: int):
    for dx, dy, cost in _MOVES:
        nx, ny = gx + dx, gy + dy
        if 0 <= nx < COLS and 0 <= ny < ROWS:
            yield nx, ny, cost * GRID_RES


def _heuristic(gx: int, gy: int, ex: int, ey: int) -> float:
    """Octile distance heuristic — admissible for 8-connected grid."""
    dx, dy = abs(gx - ex), abs(gy - ey)
    return GRID_RES * (max(dx, dy) + (1.414 - 1.0) * min(dx, dy))


def _extract_path(came_from: dict, start, goal) -> list:
    path = []
    cur = goal
    while cur in came_from:
        path.append(cur)
        cur = came_from[cur]
    path.append(start)
    path.reverse()
    return path


# ── ARA* Core ─────────────────────────────────────────────────────────────────

def _weighted_astar(
    sg: tuple[int, int],
    gg: tuple[int, int],
    alt: float,
    threats: list[ThreatZone],
    eps: float,
    g_init: dict,
    deadline: float,
) -> tuple[dict | None, dict]:
    """
    Single weighted A* pass with inflation factor eps.
    Warm-starts from g_init (g-values from previous ARA* iteration).
    Returns (came_from, g) where came_from is None if goal not reached.
    """
    g = dict(g_init)
    g.setdefault(sg, 0.0)
    came_from: dict = {}

    counter = 0  # tiebreaker to avoid comparing tuples

    def push(node):
        nonlocal counter
        f = g[node] + eps * _heuristic(node[0], node[1], gg[0], gg[1])
        heapq.heappush(heap, (f, counter, node))
        counter += 1

    heap: list = []
    push(sg)
    in_open = {sg}
    closed: set = set()

    while heap:
        if time.monotonic() >= deadline:
            break
        _, _, cur = heapq.heappop(heap)
        if cur in closed:
            continue
        in_open.discard(cur)
        closed.add(cur)

        if cur == gg:
            return came_from, g

        for nx, ny, step in _neighbours(cur[0], cur[1]):
            nb = (nx, ny)
            if nb in closed:
                continue
            risk = _get_risk(nx, ny, alt, threats)
            if risk == float("inf"):
                continue
            new_g = g[cur] + step + risk
            if new_g < g.get(nb, float("inf")):
                g[nb] = new_g
                came_from[nb] = cur
                push(nb)

    return None, g


def ara_star(
    start_x: float, start_y: float, start_alt: float,
    goal_x: float,  goal_y: float,  goal_alt: float,
    threats: List[ThreatZone],
    time_budget: float = TIME_BUDGET,
) -> tuple[list[tuple[float, float, float]] | None, float]:
    """
    ARA*: run weighted A* with decreasing ε, improving the path each iteration.

    Returns:
        (waypoints, eps_achieved) where:
          - waypoints is a list of (x, y, alt) world-space tuples, or None
          - eps_achieved is the suboptimality bound of the returned path
            (path_cost ≤ eps_achieved × optimal_cost)
    """
    # Clear risk cache from any previous planning call
    global _risk_cache, _risk_cache_alt
    _risk_cache = {}
    _risk_cache_alt = -999.0

    sg = _w2g(start_x, start_y)
    gg = _w2g(goal_x, goal_y)
    alt = choose_safe_altitude(
        start_alt, goal_alt, threats,
        start_x, start_y, goal_x, goal_y,
    )

    deadline = time.monotonic() + time_budget
    best_path: list | None = None
    best_eps: float = float("inf")
    g_warm: dict = {}

    eps = EPS_INIT
    while eps >= EPS_FINAL - 1e-9:
        if time.monotonic() >= deadline:
            break

        came_from, g_warm = _weighted_astar(sg, gg, alt, threats, eps, g_warm, deadline)

        if came_from is not None:
            grid_path = _extract_path(came_from, sg, gg)
            best_path = [(*_g2w(gx, gy), alt) for gx, gy in grid_path]
            best_eps = eps

        eps = round(eps - EPS_STEP, 6)

    if best_path is not None and len(best_path) >= 2:
        # Replace first and last waypoints with exact coordinates
        # (grid quantization shifts them by up to GRID_RES/2)
        best_path[0] = (start_x, start_y, alt)
        best_path[-1] = (goal_x, goal_y, alt)

    return best_path, best_eps


# ── Analytic Line-Circle Intersection ────────────────────────────────────────

def segment_intersects_circle(
    x1: float, y1: float,
    x2: float, y2: float,
    cx: float, cy: float,
    r: float,
) -> bool:
    """
    Exact test: does the line segment (x1,y1)→(x2,y2) pass within radius r
    of centre (cx,cy)?  Uses vector projection — no sampling required.
    """
    dx, dy = x2 - x1, y2 - y1
    fx, fy = x1 - cx, y1 - cy

    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq < 1e-12:
        # Degenerate segment (point): just check the point
        return fx * fx + fy * fy < r * r

    # Parameter t of the closest point on the infinite line to the circle centre
    t = -(fx * dx + fy * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))  # clamp to segment

    close_x = fx + t * dx
    close_y = fy + t * dy

    return close_x * close_x + close_y * close_y < r * r


def path_clear(
    p1: tuple[float, float, float],
    p2: tuple[float, float, float],
    threats: list[ThreatZone],
) -> bool:
    """
    Return True if the straight line from p1 to p2 does not intersect any
    threat zone (including safety margin) at the altitude of travel.
    Altitude is taken as min(p1.alt, p2.alt) — conservative for climbing/descending.
    """
    x1, y1, alt1 = p1
    x2, y2, alt2 = p2
    alt = min(alt1, alt2)

    for t in threats:
        if alt >= t.alt_ceil:
            continue  # altitude clears this threat
        if segment_intersects_circle(x1, y1, x2, y2, t.x, t.y, t.radius + SAFETY_MARGIN):
            return False
    return True


def path_clear_2d(
    x1: float, y1: float,
    x2: float, y2: float,
    alt: float,
    threats: list[ThreatZone],
) -> bool:
    """2D variant (no altitude tuple) for convenience. Includes safety margin."""
    for t in threats:
        if alt >= t.alt_ceil:
            continue
        if segment_intersects_circle(x1, y1, x2, y2, t.x, t.y, t.radius + SAFETY_MARGIN):
            return False
    return True


# ── String-Pulling Smoother ───────────────────────────────────────────────────

def string_pull(
    path: list[tuple[float, float, float]],
    threats: list[ThreatZone],
) -> list[tuple[float, float, float]]:
    """
    Greedy path shortcutting (string-pulling):
    Walk forward; from each node skip ahead to the furthest node reachable
    via a clear straight line.  Reduces ARA* grid-quantisation waypoints.
    """
    if len(path) <= 2:
        return path

    result = [path[0]]
    i = 0
    while i < len(path) - 1:
        # Find furthest j > i such that path[i] → path[j] is clear
        j = len(path) - 1
        while j > i + 1:
            if path_clear(path[i], path[j], threats):
                break
            j -= 1
        result.append(path[j])
        i = j

    # Ensure goal is always included
    if result[-1] != path[-1]:
        result.append(path[-1])

    return result


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class PlanResult:
    found: bool
    waypoints: list[tuple[float, float, float]]    # (x, y, alt) list
    eps: float                                     # suboptimality bound
    quality: str                                   # human-readable quality label
    safe_alt: float


def plan_path(
    start_x: float, start_y: float, start_alt: float,
    goal_x: float,  goal_y: float,  goal_alt: float,
    threats: list[ThreatZone],
    time_budget: float = TIME_BUDGET,
) -> PlanResult:
    """
    Full pipeline: ARA* + string-pulling.

    Args:
        start_*/goal_*: ENU world coordinates (metres) and altitudes (metres AGL).
        threats:        List of ThreatZone objects from zones_from_config().
        time_budget:    Maximum planning time in seconds (default 200 ms).

    Returns:
        PlanResult with found=True and a smoothed waypoint list on success,
        or found=False with empty waypoints if no path exists.
    """
    safe_alt = choose_safe_altitude(
        start_alt, goal_alt, threats,
        start_x, start_y, goal_x, goal_y,
    )

    path, eps = ara_star(
        start_x, start_y, start_alt,
        goal_x,  goal_y,  goal_alt,
        threats,
        time_budget=time_budget,
    )

    if path is None:
        return PlanResult(
            found=False,
            waypoints=[],
            eps=float("inf"),
            quality="no path found",
            safe_alt=safe_alt,
        )

    smoothed = string_pull(path, threats)

    if eps <= EPS_FINAL + 1e-6:
        quality = "optimal"
    elif eps <= 1.5:
        quality = f"≤{eps:.1f}× optimal (near-optimal)"
    else:
        quality = f"≤{eps:.1f}× optimal (time-bounded)"

    return PlanResult(
        found=True,
        waypoints=smoothed,
        eps=eps,
        quality=quality,
        safe_alt=safe_alt,
    )
