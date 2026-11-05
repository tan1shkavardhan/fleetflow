from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from Backend.app.database import get_db
from Backend.app.models import AlertRecord

router = APIRouter(prefix="/alerts", tags=["alerts"])

@router.get("/")
async def list_alerts(vehicle_id: str | None = None, alert_type: str | None = None, limit: int = Query(100, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
    stmt = select(AlertRecord).order_by(AlertRecord.created_at.desc()).limit(limit)
    if vehicle_id: stmt = stmt.where(AlertRecord.vehicle_id == vehicle_id)
    if alert_type: stmt = stmt.where(AlertRecord.alert_type == alert_type)
    rows = (await db.execute(stmt)).scalars().all()
    return {"count": len(rows), "alerts": [{"id": r.id, "vehicle_id": r.vehicle_id, "type": r.alert_type, "message": r.message,
        "details": r.details, "timestamp": r.created_at.isoformat()} for r in rows]}
