from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from Backend.app.config import settings
from Backend.app.database import get_db
from Backend.app.models import AlertRecord, Geofence, Telemetry, Vehicle
from Backend.app.redis_client import redis_client
from Backend.app.schemas import TelemetryIn
from Backend.app.services.delay_detector import evaluate_delay, expected_speed_kmh
from Backend.app.services.geo import distance_km
from Backend.app.services.websocket_manager import manager

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

async def _alert(db: AsyncSession, vehicle_id: str, alert_type: str, message: str, details: dict) -> dict:
    event = {"type": alert_type, "alert_id": f"alert_{uuid4().hex[:12]}", "vehicle_id": vehicle_id,
             "message": message, "details": details, "timestamp": datetime.now(timezone.utc).isoformat()}
    db.add(AlertRecord(id=event["alert_id"], vehicle_id=vehicle_id, alert_type=alert_type, message=message, details=details))
    return event

@router.post("/")
async def ingest_telemetry(payload: TelemetryIn, db: AsyncSession = Depends(get_db)):
    vehicle = await db.get(Vehicle, payload.vehicle_id)
    if not vehicle:
        raise HTTPException(404, detail=f"Vehicle '{payload.vehicle_id}' is not registered. Register it first via POST /vehicles/.")
    if not vehicle.active:
        raise HTTPException(409, detail="Vehicle is inactive")
    recorded_at = payload.timestamp or datetime.now(timezone.utc)
    if recorded_at.tzinfo is None: recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    row = Telemetry(vehicle_id=payload.vehicle_id, latitude=payload.latitude, longitude=payload.longitude, speed=payload.speed,
                    heading=payload.heading, recorded_at=recorded_at)
    db.add(row)
    events = []
    try:
        # Persist the authoritative history first; Redis failures are reported rather than silently ignored.
        await db.flush()
        await redis_client.geoadd(settings.vehicle_geo_key,  (payload.longitude, payload.latitude,payload.vehicle_id))
        await redis_client.hset(f"vehicle:latest:{payload.vehicle_id}", mapping={"latitude": payload.latitude, "longitude": payload.longitude,
            "speed": payload.speed, "timestamp": recorded_at.isoformat(), "status": vehicle.status})
        await redis_client.xadd(settings.telemetry_stream_key, {"vehicle_id": payload.vehicle_id, "latitude": payload.latitude,
            "longitude": payload.longitude, "speed": payload.speed, "timestamp": recorded_at.isoformat()}, maxlen=settings.telemetry_stream_maxlen, approximate=True)
        geofences = (await db.execute(select(Geofence).where(Geofence.active.is_(True)))).scalars().all()
        for fence in geofences:
            inside = distance_km(payload.latitude, payload.longitude, fence.latitude, fence.longitude) * 1000 <= fence.radius_m
            key = f"geofence:state:{payload.vehicle_id}:{fence.id}"
            previous = await redis_client.get(key)
            current = "inside" if inside else "outside"
            await redis_client.set(key, current, ex=60*60*24*30)
            if previous is not None and previous != current:
                transition = "ENTER" if current == "inside" else "EXIT"
                events.append(await _alert(db, payload.vehicle_id, "geofence_alert", f"{payload.vehicle_id} {transition.lower()}ed {fence.name}",
                    {"geofence_id": fence.id, "geofence_name": fence.name, "transition": transition, "latitude": payload.latitude,
                     "longitude": payload.longitude, "radius_m": fence.radius_m}))
        expected = expected_speed_kmh(recorded_at)
        movement = await evaluate_delay(
            redis_client, payload.vehicle_id, payload.speed, expected,
            payload.latitude, payload.longitude, recorded_at
        )
        if movement is None:
            detector_state = await redis_client.hgetall(f"movement:state:{payload.vehicle_id}")
            movement = {
                "transition": "none",
                "movement_classification": detector_state.get("movement_classification", "MOVING"),
                "breakdown_confirmed": detector_state.get("breakdown_confirmed") == "1",
                "stopped_seconds": float(detector_state.get("timestamp", recorded_at.timestamp())) -
                                   float(detector_state.get("stopped_since") or recorded_at.timestamp()),
            }
        classification = movement.get("movement_classification", "MOVING")
        if movement and movement.get("transition") == "started":
            alert_type = "breakdown_alert" if movement.get("breakdown_confirmed") else "delay_alert"
            message = (f"Prolonged stationary breakdown confirmed for {payload.vehicle_id}"
                       if movement.get("breakdown_confirmed")
                       else f"Movement anomaly detected for {payload.vehicle_id}: {classification}")
            events.append(await _alert(db, payload.vehicle_id, alert_type, message, movement))
            if movement.get("breakdown_confirmed"):
                vehicle.status = "BREAKDOWN"
        elif movement and movement.get("transition") == "recovered":
            await redis_client.delete(f"breakdown:alerted:{payload.vehicle_id}")
            events.append(await _alert(db, payload.vehicle_id, "delay_recovered",
                                       f"Delay condition cleared for {payload.vehicle_id}", movement))
            if vehicle.status in {"DELAYED", "STOPPED"}:
                vehicle.status = "MOVING"

        # Breakdown is a separate escalation after a sustained stationary interval.
        if movement and movement.get("breakdown_confirmed"):
            breakdown_key = f"breakdown:alerted:{payload.vehicle_id}"
            already_alerted = await redis_client.get(breakdown_key)
            if not already_alerted:
                await redis_client.set(breakdown_key, "1", ex=86400)
                events.append(await _alert(
                    db, payload.vehicle_id, "breakdown_alert",
                    f"Prolonged stationary breakdown confirmed for {payload.vehicle_id}",
                    movement
                ))

        # Status is derived from the classifier, not from one isolated speed sample.
        if classification == "BREAKDOWN":
            vehicle.status = "BREAKDOWN"
        elif classification == "PROLONGED_STOPPAGE":
            vehicle.status = "STOPPED"
        elif classification in {"TRAFFIC_CONGESTION", "SLOW_MOVEMENT"}:
            if vehicle.status != "BREAKDOWN":
                vehicle.status = "DELAYED"
        elif payload.speed > 1 and vehicle.status in {"STOPPED", "DELAYED"}:
            vehicle.status = "MOVING"
        await db.commit()
        for event in events:
            await manager.broadcast(event)
    except HTTPException:
        await db.rollback(); raise
    except Exception as exc:
        await db.rollback()
        import logging
        logging.exception("Telemetry processing failed")
        raise HTTPException(
            503,
            detail=f"Telemetry processing failed: {type(exc).__name__}: {exc}"
        ) from exc
    update = {"type": "vehicle_update", "vehicle": {"vehicle_id": payload.vehicle_id, "latitude": payload.latitude,
        "longitude": payload.longitude, "speed": payload.speed, "heading": payload.heading, "status": vehicle.status,
        "timestamp": recorded_at.isoformat(), "movement_classification": classification}}
    await manager.broadcast(update)
    return {"success": True, "vehicle_id": payload.vehicle_id, "recorded_at": recorded_at.isoformat(), "events_generated": len(events), "events": events}
