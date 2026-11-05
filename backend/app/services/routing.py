"""Dependency-free route optimizer: nearest-neighbour construction + 2-opt improvement.

Distances are great-circle estimates. Optional delivery time windows are considered using
an explicit configurable-average-speed estimate; this is not road-network navigation.
"""
from datetime import datetime, timezone
from Backend.app.services.geo import distance_km

AVERAGE_SPEED_KMH = 30.0

def _as_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None

def _schedule(start, stops, departure):
    clock_ts = departure.timestamp()
    prev = start
    rows = []
    total_distance = 0.0
    total_late = 0.0
    total_wait = 0.0
    for idx, stop in enumerate(stops, 1):
        leg = distance_km(prev[0], prev[1], stop["latitude"], stop["longitude"])
        total_distance += leg
        clock_ts += (leg / AVERAGE_SPEED_KMH) * 3600
        arrival = datetime.fromtimestamp(clock_ts, tz=timezone.utc)
        window_start = _as_datetime(stop.get("time_window_start"))
        window_end = _as_datetime(stop.get("time_window_end"))
        wait = max(0.0, (window_start - arrival).total_seconds() / 60) if window_start and arrival < window_start else 0.0
        if wait:
            clock_ts += wait * 60
            arrival = datetime.fromtimestamp(clock_ts, tz=timezone.utc)
        late = max(0.0, (arrival - window_end).total_seconds() / 60) if window_end else 0.0
        total_late += late
        total_wait += wait
        stop_out = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in stop.items()}
        rows.append({**stop_out, "sequence": idx, "leg_distance_km": round(leg, 3), "estimated_arrival": arrival.isoformat(),
                     "waiting_minutes": round(wait, 1), "late_by_minutes": round(late, 1)})
        service = max(0, float(stop.get("service_minutes", 0)))
        clock_ts += service * 60
        prev = (stop["latitude"], stop["longitude"])
    duration = max(0.0, (clock_ts - departure.timestamp()) / 60)
    return rows, total_distance, total_late, total_wait, duration

def optimize_route(start: tuple[float, float], stops: list[dict], departure_time: datetime | None = None) -> dict:
    departure = departure_time or datetime.now(timezone.utc)
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=timezone.utc)
    else:
        departure = departure.astimezone(timezone.utc)
    remaining = list(stops)
    route, current, clock = [], start, departure
    # Greedy selection balances short legs with missed time windows and delivery priority.
    while remaining:
        def candidate_score(stop):
            leg = distance_km(current[0], current[1], stop["latitude"], stop["longitude"])
            eta = clock.timestamp() + (leg / AVERAGE_SPEED_KMH) * 3600
            end = _as_datetime(stop.get("time_window_end"))
            late = max(0.0, (eta - end.timestamp()) / 60) if end else 0.0
            priority = float(stop.get("priority", 3))
            return leg + late * (0.15 + priority * 0.05)
        nxt = min(remaining, key=candidate_score)
        leg = distance_km(current[0], current[1], nxt["latitude"], nxt["longitude"])
        eta = clock.timestamp() + (leg / AVERAGE_SPEED_KMH) * 3600
        arrival = datetime.fromtimestamp(eta, tz=timezone.utc)
        window_start = _as_datetime(nxt.get("time_window_start"))
        if window_start and arrival < window_start:
            arrival = window_start
        clock = datetime.fromtimestamp(arrival.timestamp() + max(0, float(nxt.get("service_minutes", 0))) * 60, tz=timezone.utc)
        route.append(nxt)
        remaining.remove(nxt)
        current = (nxt["latitude"], nxt["longitude"])

    def score(items):
        rows, dist, late, wait, duration = _schedule(start, items, departure)
        priority_late_penalty = sum(float(row.get("priority", 3)) * row["late_by_minutes"] for row in rows)
        return dist + 0.2 * late + 0.05 * priority_late_penalty, rows, dist, late, wait, duration

    improved = True
    while improved and len(route) >= 3:
        improved = False
        best_score = score(route)[0]
        best_route = route
        for i in range(len(route) - 1):
            for j in range(i + 1, len(route)):
                candidate = route[:i] + list(reversed(route[i:j + 1])) + route[j + 1:]
                candidate_score_value = score(candidate)[0]
                if candidate_score_value + 1e-9 < best_score:
                    best_route, best_score, improved = candidate, candidate_score_value, True
        route = best_route
    rows, total_distance, total_late, total_wait, duration = score(route)[1:]
    return {"stops": rows, "total_distance_km": round(total_distance, 3),
            "estimated_total_duration_minutes": round(duration, 1), "total_late_minutes": round(total_late, 1),
            "total_waiting_minutes": round(total_wait, 1), "time_windows_considered": any(s.get("time_window_start") or s.get("time_window_end") for s in stops),
            "average_speed_assumption_kmh": AVERAGE_SPEED_KMH,
            "algorithm": "nearest-neighbour + 2-opt with time-window penalties",
            "optimality": "heuristic; not guaranteed globally optimal"}
