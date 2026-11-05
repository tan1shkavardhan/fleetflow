from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from Backend.app.database import get_db
from Backend.app.models import Delivery, Package, Vehicle
from Backend.app.schemas import DeliveryCreate, DeliveryOut, PackageCreate, PackageOut

router = APIRouter(tags=["cargo and deliveries"])

@router.post("/packages", response_model=PackageOut, status_code=status.HTTP_201_CREATED)
async def create_package(payload: PackageCreate, db: AsyncSession = Depends(get_db)):
    if await db.get(Package, payload.id): raise HTTPException(409, detail="Package ID already exists")
    if payload.delivery_id and not await db.get(Delivery, payload.delivery_id): raise HTTPException(404, detail="Delivery not found")
    if payload.assigned_vehicle_id and not await db.get(Vehicle, payload.assigned_vehicle_id): raise HTTPException(404, detail="Vehicle not found")
    obj = Package(**payload.model_dump()); db.add(obj); await db.commit(); await db.refresh(obj); return obj

@router.get("/packages", response_model=list[PackageOut])
async def list_packages(vehicle_id: str | None = None, status_filter: str | None = None, db: AsyncSession = Depends(get_db)):
    stmt = select(Package).order_by(Package.id)
    if vehicle_id: stmt = stmt.where(Package.assigned_vehicle_id == vehicle_id)
    if status_filter: stmt = stmt.where(Package.status == status_filter.upper())
    return (await db.execute(stmt)).scalars().all()

@router.post("/deliveries", response_model=DeliveryOut, status_code=status.HTTP_201_CREATED)
async def create_delivery(payload: DeliveryCreate, db: AsyncSession = Depends(get_db)):
    if await db.get(Delivery, payload.id): raise HTTPException(409, detail="Delivery ID already exists")
    if payload.assigned_vehicle_id and not await db.get(Vehicle, payload.assigned_vehicle_id): raise HTTPException(404, detail="Vehicle not found")
    obj = Delivery(**payload.model_dump()); db.add(obj); await db.commit(); await db.refresh(obj); return obj

@router.get("/deliveries", response_model=list[DeliveryOut])
async def list_deliveries(vehicle_id: str | None = None, db: AsyncSession = Depends(get_db)):
    stmt = select(Delivery).order_by(Delivery.priority.desc(), Delivery.id)
    if vehicle_id: stmt = stmt.where(Delivery.assigned_vehicle_id == vehicle_id)
    return (await db.execute(stmt)).scalars().all()
