from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from Backend.app.database import get_db
from Backend.app.models import Geofence
from Backend.app.schemas import GeofenceCreate, GeofenceOut

router = APIRouter(prefix="/geofences", tags=["geofences"])

@router.post("/", response_model=GeofenceOut, status_code=status.HTTP_201_CREATED)
async def create_geofence(payload: GeofenceCreate, db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(Geofence).where(Geofence.name == payload.name))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, detail=f"Geofence named '{payload.name}' already exists")
    same_circle = (await db.execute(select(Geofence).where(Geofence.latitude == payload.latitude,
        Geofence.longitude == payload.longitude, Geofence.radius_m == payload.radius_m))).scalar_one_or_none()
    if same_circle:
        raise HTTPException(409, detail=f"Geofence duplicates the existing circle '{same_circle.name}'")
    gid = payload.id or f"geo_{uuid4().hex[:12]}"
    if await db.get(Geofence, gid):
        raise HTTPException(409, detail=f"Geofence ID '{gid}' already exists")
    obj = Geofence(id=gid, **payload.model_dump(exclude={"id"}), demo_seed=False)
    db.add(obj); await db.commit(); await db.refresh(obj)
    return obj

@router.get("/", response_model=list[GeofenceOut])
async def list_geofences(active_only: bool = False, db: AsyncSession = Depends(get_db)):
    stmt = select(Geofence).order_by(Geofence.name)
    if active_only: stmt = stmt.where(Geofence.active.is_(True))
    return (await db.execute(stmt)).scalars().all()

@router.get("/{geofence_id}", response_model=GeofenceOut)
async def get_geofence(geofence_id: str, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Geofence, geofence_id)
    if not obj: raise HTTPException(404, detail="Geofence not found")
    return obj

@router.patch("/{geofence_id}", response_model=GeofenceOut)
async def update_geofence(geofence_id: str, payload: GeofenceCreate, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Geofence, geofence_id)
    if not obj: raise HTTPException(404, detail="Geofence not found")
    for key, value in payload.model_dump(exclude={"id"}, exclude_unset=True).items(): setattr(obj, key, value)
    await db.commit(); await db.refresh(obj); return obj

@router.delete("/{geofence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_geofence(geofence_id: str, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Geofence, geofence_id)
    if not obj: raise HTTPException(404, detail="Geofence not found")
    await db.delete(obj); await db.commit()
