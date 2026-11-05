from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from Backend.app.config import settings
from Backend.app.services.geo import distance_km

INDIA_TZ = ZoneInfo("Asia/Kolkata")
STATIONARY_RADIUS_KM = 0.015  # 15 metres; GPS jitter below this is treated as stationary.
DEFAULT_PROLONGED_STOP_SECONDS = 300

def expected_speed_kmh(when: datetime | None = None) -> float:
    when = when or datetime.now(INDIA_TZ)
    if when.tzinfo is None:
        when = when.replace(tzinfo=INDIA_TZ)
    local = when.astimezone(INDIA_TZ)
    if 8 <= local.hour < 11:
        return 25.0
    if 17 <= local.hour < 21:
        return 20.0
    return 40.0

async def evaluate_delay(redis, vehicle_id: str, speed: float, expected: float,
                         latitude: float | None = None, longitude: float | None = None,
                         recorded_at: datetime | None = None) -> dict | None:
    """Classify slow telemetry. Repeated speeds alone never establish a breakdown.

    Three low-speed readings may open a delay suspicion. A prolonged stop requires
    low speed AND negligible GPS displacement over the configured duration. A
    breakdown is only confirmed for explicitly configured demo vehicles after that
    prolonged-stop condition; other vehicles remain STOPPED/PROLONGED_STOPPAGE.
    """
    now = recorded_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_ts = now.timestamp()
    key = f"movement:state:{vehicle_id}"
    state = await redis.hgetall(key)
    ratio = speed / expected if expected > 0 else 1.0
    low = ratio <= float(getattr(settings, "delay_threshold_ratio", 0.5))
    prev_lat = state.get("latitude")
    prev_lon = state.get("longitude")
    prev_ts = float(state.get("timestamp", now_ts))
    displacement = None
    if latitude is not None and longitude is not None and prev_lat is not None and prev_lon is not None:
        displacement = distance_km(float(prev_lat), float(prev_lon), latitude, longitude)
    stationary = speed <= 1.0 and (displacement is None or displacement <= STATIONARY_RADIUS_KM)
    stopped_since = float(state.get("stopped_since") or now_ts) if stationary else None
    if stationary and not state.get("stopped_since"):
        stopped_since = prev_ts
    stopped_seconds = max(0.0, now_ts - stopped_since) if stopped_since is not None else 0.0
    prolonged_after = int(getattr(settings, "prolonged_stop_seconds", DEFAULT_PROLONGED_STOP_SECONDS))
    breakdown_ids = set(getattr(settings, "breakdown_vehicle_ids", []) or [])
    breakdown_confirmed = vehicle_id in breakdown_ids and stopped_seconds >= prolonged_after

    count = int(state.get("low_count", "0")) + 1 if low else 0
    was_active = state.get("delay_active") == "1"
    event = None
    if was_active and ratio >= float(getattr(settings, "delay_recovery_ratio", 0.75)):
        event = {"transition": "recovered", "vehicle_id": vehicle_id, "speed": speed,
                 "expected_speed": expected, "movement_classification": "MOVING"}
        was_active = False
        count = 0
    elif low and not was_active and count >= int(getattr(settings, "delay_consecutive_limit", 3)):
        if stationary and stopped_seconds >= prolonged_after:
            classification = "BREAKDOWN" if breakdown_confirmed else "PROLONGED_STOPPAGE"
        elif displacement is not None and displacement > STATIONARY_RADIUS_KM:
            classification = "TRAFFIC_CONGESTION"
        elif speed > 1:
            classification = "SLOW_MOVEMENT"
        else:
            classification = "STOPPAGE_SUSPECTED"
        event = {"transition": "started", "vehicle_id": vehicle_id, "speed": speed,
                 "expected_speed": expected, "ratio": round(ratio, 3),
                 "consecutive_readings": count, "movement_classification": classification,
                 "displacement_km": round(displacement, 5) if displacement is not None else None,
                 "stopped_seconds": round(stopped_seconds, 1),
                 "breakdown_confirmed": breakdown_confirmed}
        was_active = True

    # Persist detector state even when there is no alert.
    mapping = {"low_count": count, "delay_active": int(was_active), "timestamp": now_ts,
               "last_speed": speed, "stopped_since": stopped_since or ""}
    if latitude is not None: mapping["latitude"] = latitude
    if longitude is not None: mapping["longitude"] = longitude
    classification = ("BREAKDOWN" if breakdown_confirmed else
                      ("PROLONGED_STOPPAGE" if stopped_seconds >= prolonged_after and stationary else
                       ("TRAFFIC_CONGESTION" if displacement is not None and displacement > STATIONARY_RADIUS_KM and low else
                        ("SLOW_MOVEMENT" if low and speed > 1 else
                         ("STOPPAGE_SUSPECTED" if speed <= 1 else "MOVING")))))
    mapping["movement_classification"] = classification
    mapping["breakdown_confirmed"] = int(breakdown_confirmed)
    await redis.hset(key, mapping={k: str(v) for k, v in mapping.items()})
    await redis.expire(key, 86400)
    return event
