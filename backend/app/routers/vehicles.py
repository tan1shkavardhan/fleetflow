from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from Backend.app.database import get_db
from Backend.app.models import Delivery, Package, Telemetry, Vehicle
from Backend.app.schemas import VehicleCreate, VehicleOut
from Backend.app.redis_client import redis_client
from Backend.app.config import settings
from Backend.app.services.geo import distance_km

router = APIRouter(prefix="/vehicles", tags=["vehicles"])

@router.post("/", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
async def register_vehicle(payload: VehicleCreate, db: AsyncSession = Depends(get_db)):
    if await db.get(Vehicle, payload.id):
        raise HTTPException(409, detail=f"Vehicle '{payload.id}' already exists")
    if payload.capacity_kg < payload.max_payload_kg:
        # Capacity is a legacy alias; max_payload is the enforceable payload limit.
        raise HTTPException(422, detail="max_payload_kg cannot exceed capacity_kg")
    obj = Vehicle(**payload.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

@router.get("/", response_model=list[VehicleOut])
async def list_vehicles(active_only: bool = True, db: AsyncSession = Depends(get_db)):
    stmt = select(Vehicle).order_by(Vehicle.id)
    if active_only:
        stmt = stmt.where(Vehicle.active.is_(True))
    return (await db.execute(stmt)).scalars().all()

@router.get("/nearby")
async def nearby_vehicles(latitude: float = Query(..., ge=-90, le=90), longitude: float = Query(..., ge=-180, le=180),
                         radius_km: float = Query(20, gt=0, le=500), exclude_vehicle_id: str | None = None,
                         db: AsyncSession = Depends(get_db)):
    # Redis Geo is primary; DB's latest telemetry is a fallback to keep diagnostics useful.
    results = []
    redis_error = None
    try:
        raw = await redis_client.georadius(settings.vehicle_geo_key, longitude, latitude, radius_km, unit="km", withdist=True, withcoord=True, sort="ASC")
        for item in raw:
            vid = item[0]
            if exclude_vehicle_id and vid == exclude_vehicle_id:
                continue
            results.append({"vehicle_id": vid, "distance_km": round(float(item[1]), 3), "longitude": float(item[2][0]), "latitude": float(item[2][1]), "source": "redis_geo"})
    except Exception as exc:
        redis_error = type(exc).__name__
    fallback_used = bool(redis_error) or not results
    if fallback_used:
        rows = (await db.execute(select(Telemetry).order_by(Telemetry.recorded_at.desc(), Telemetry.id.desc()))).scalars().all()
        latest = {}
        for row in rows:
            latest.setdefault(row.vehicle_id, row)
        for vid, row in latest.items():
            if exclude_vehicle_id and vid == exclude_vehicle_id:
                continue
            d = distance_km(latitude, longitude, row.latitude, row.longitude)
            if d <= radius_km:
                results.append({"vehicle_id": vid, "distance_km": round(d, 3), "longitude": row.longitude, "latitude": row.latitude, "source": "postgres_fallback"})
        results.sort(key=lambda r: r["distance_km"])
    return {"count": len(results), "radius_km": radius_km, "vehicles": results, "fallback_used": fallback_used, "redis_error": redis_error}


@router.get("/{vehicle_id}", response_model=VehicleOut)
async def get_vehicle(vehicle_id: str, db: AsyncSession = Depends(get_db)):
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(404, detail="Vehicle not found")
    return vehicle

@router.get("/{vehicle_id}/history")
async def vehicle_history(vehicle_id: str, limit: int = Query(100, ge=1, le=2000), db: AsyncSession = Depends(get_db)):
    if not await db.get(Vehicle, vehicle_id):
        raise HTTPException(404, detail="Vehicle not found")
    rows = (await db.execute(select(Telemetry).where(Telemetry.vehicle_id == vehicle_id).order_by(Telemetry.recorded_at.desc(), Telemetry.id.desc()).limit(limit))).scalars().all()
    return {"vehicle_id": vehicle_id, "count": len(rows), "history": [{"latitude": r.latitude, "longitude": r.longitude, "speed": r.speed,
            "heading": r.heading, "timestamp": r.recorded_at.isoformat()} for r in rows]}

@router.get("/{vehicle_id}/cargo")
async def vehicle_cargo(vehicle_id: str, db: AsyncSession = Depends(get_db)):
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(404, detail="Vehicle not found")
    packages = (await db.execute(select(Package).where(Package.assigned_vehicle_id == vehicle_id, Package.status.in_(["PENDING", "IN_TRANSIT", "REASSIGNED"])))).scalars().all()
    return {"vehicle_id": vehicle_id, "payload_capacity_kg": vehicle.max_payload_kg, "assigned_weight_kg": round(sum(p.weight_kg for p in packages), 2),
            "remaining_payload_kg": round(vehicle.max_payload_kg-sum(p.weight_kg for p in packages), 2), "packages": [{"id": p.id, "weight_kg": p.weight_kg, "dimensions_cm": [p.length_cm,p.width_cm,p.height_cm], "delivery_id": p.delivery_id} for p in packages]}
