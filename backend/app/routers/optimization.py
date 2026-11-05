
from uuid import uuid4
from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from Backend.app.database import get_db
from Backend.app.models import Delivery, Package, RecoveryPlan, RecoveryStatusHistory, Vehicle
from Backend.app.schemas import (
    RecoveryAnalyzeRequest,
    RecoveryExecuteRequest,
    RouteOptimizeRequest,
)
from Backend.app.services.packing import pack_packages
from Backend.app.services.recovery import (
    analyze_recovery,
    execute_recovery,
    latest_position,
)
from Backend.app.services.routing import optimize_route
from Backend.app.services.websocket_manager import manager

router = APIRouter(tags=["optimization and recovery"])


@router.post("/optimization/pack")
async def pack_cargo(
    vehicle_id: str,
    package_ids: list[str],
    apply_accessibility: bool = True,
    db: AsyncSession = Depends(get_db),
):
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    packages = (
        await db.execute(
            select(Package).where(Package.id.in_(package_ids))
        )
    ).scalars().all()

    if len(packages) != len(set(package_ids)):
        raise HTTPException(
            status_code=404,
            detail="One or more packages not found",
        )

    delivery_ids = {
        package.delivery_id
        for package in packages
        if package.delivery_id
    }

    deliveries = (
        (
            await db.execute(
                select(Delivery).where(Delivery.id.in_(delivery_ids))
            )
        ).scalars().all()
        if delivery_ids
        else []
    )

    delivery_order = {
        delivery.id: index
        for index, delivery in enumerate(
            sorted(
                deliveries,
                key=lambda delivery: (
                    -delivery.priority,
                    delivery.id,
                ),
            )
        )
    }

    result = pack_packages(
        {
            "id": vehicle.id,
            "cargo_length_cm": vehicle.cargo_length_cm,
            "cargo_width_cm": vehicle.cargo_width_cm,
            "cargo_height_cm": vehicle.cargo_height_cm,
            "max_payload_kg": vehicle.max_payload_kg,
        },
        [
            {
                "id": package.id,
                "delivery_id": package.delivery_id,
                "length_cm": package.length_cm,
                "width_cm": package.width_cm,
                "height_cm": package.height_cm,
                "weight_kg": package.weight_kg,
                "allowed_rotations": package.allowed_rotations,
            }
            for package in packages
        ],
        delivery_order,
        apply_accessibility,
    )

    return {"vehicle_id": vehicle_id, **result}


@router.post("/optimization/route")
async def route_optimization(
    payload: RouteOptimizeRequest,
    db: AsyncSession = Depends(get_db),
):
    vehicle = await db.get(Vehicle, payload.vehicle_id)
    if not vehicle:
        raise HTTPException(
            status_code=404,
            detail="Vehicle not found",
        )

    # Resolve the route's starting position.
    if (
        payload.start_latitude is not None
        and payload.start_longitude is not None
    ):
        start = (
            payload.start_latitude,
            payload.start_longitude,
        )
    else:
        start = await latest_position(db, payload.vehicle_id)

    if not start:
        raise HTTPException(
            status_code=400,
            detail=(
                "Vehicle has no known location; send telemetry "
                "or provide start coordinates"
            ),
        )

    if payload.delivery_ids:
        # Explicitly supplied delivery IDs must all exist.
        requested_ids = set(payload.delivery_ids)

        result = await db.execute(
            select(Delivery).where(
                Delivery.id.in_(requested_ids)
            )
        )
        deliveries = result.scalars().all()

        found_ids = {delivery.id for delivery in deliveries}
        missing_ids = sorted(requested_ids - found_ids)

        if missing_ids:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "One or more deliveries were not found",
                    "missing_delivery_ids": missing_ids,
                },
            )
    else:
        # Preserve existing behavior for an empty list:
        # optimize this vehicle's pending/reassigned deliveries.
        result = await db.execute(
            select(Delivery).where(
                Delivery.assigned_vehicle_id == payload.vehicle_id,
                Delivery.status.in_(["PENDING", "REASSIGNED"]),
            )
        )
        deliveries = result.scalars().all()

    route = optimize_route(
        start,
        [
            {
                "id": delivery.id,
                "customer_name": delivery.customer_name,
                "latitude": delivery.latitude,
                "longitude": delivery.longitude,
                "priority": delivery.priority,
                "service_minutes": delivery.service_minutes,
                "time_window_start": delivery.time_window_start,
                "time_window_end": delivery.time_window_end,
            }
            for delivery in deliveries
        ],
    )

    return {"vehicle_id": payload.vehicle_id, **route}


@router.post("/recovery/analyze")
async def recovery_analysis(
    payload: RecoveryAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await analyze_recovery(
            db,
            payload.delayed_vehicle_id,
            payload.package_ids,
            payload.delivery_ids,
            payload.radius_km,
            payload.max_candidates,
            payload.origin_latitude,
            payload.origin_longitude,
            payload.apply_accessibility,
        )

        # Cache the analysis so execution uses the analyzed plan.
        analysis_id = uuid4().hex[:12]
        key = (
            f"recovery:analysis:"
            f"{payload.delayed_vehicle_id}:{analysis_id}"
        )

        from Backend.app.redis_client import redis_client

        await redis_client.set(
            key,
            json.dumps(result),
            ex=3600,
        )

        result["analysis_id"] = analysis_id
        return result

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@router.post("/recovery/execute")
async def recovery_execution(
    payload: RecoveryExecuteRequest,
    analysis_id: str,
    delayed_vehicle_id: str,
    db: AsyncSession = Depends(get_db),
):
    from Backend.app.redis_client import redis_client

    key = (
        f"recovery:analysis:"
        f"{delayed_vehicle_id}:{analysis_id}"
    )

    raw = await redis_client.get(key)

    if not raw:
        raise HTTPException(
            status_code=404,
            detail=(
                "Recovery analysis was not found or has expired; "
                "analyze again"
            ),
        )

    plan = json.loads(raw)

    if set(payload.package_ids) != set(plan.get("package_ids", [])):
        raise HTTPException(
            status_code=422,
            detail=(
                "Execution package_ids must exactly match the package "
                "set analyzed. Run recovery analysis again if the "
                "transfer set changes."
            ),
        )

    analyzed_deliveries = set(plan.get("delivery_ids", []))

    if (
        payload.delivery_ids
        and set(payload.delivery_ids) != analyzed_deliveries
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Execution delivery_ids must match the "
                "delivery set analyzed."
            ),
        )

    try:
        return await execute_recovery(
            db,
            delayed_vehicle_id,
            payload.helper_vehicle_id,
            payload.package_ids,
            list(analyzed_deliveries),
            plan,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@router.get("/recovery/plans")
async def list_recovery_plans(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(RecoveryPlan)
            .order_by(RecoveryPlan.created_at.desc())
            .limit(min(max(limit, 1), 200))
        )
    ).scalars().all()

    return [
        {
            "id": plan.id,
            "delayed_vehicle_id": plan.delayed_vehicle_id,
            "helper_vehicle_id": plan.helper_vehicle_id,
            "status": plan.status,
            "radius_km": plan.radius_km,
            "created_at": plan.created_at.isoformat(),
            "plan": plan.plan_json,
        }
        for plan in rows
    ]


RECOVERY_TRANSITIONS = {
    "ASSIGNED": {"EN_ROUTE_TO_INCIDENT", "CANCELLED", "FAILED"},
    "EN_ROUTE_TO_INCIDENT": {"ARRIVED_AT_INCIDENT", "CANCELLED", "FAILED"},
    "ARRIVED_AT_INCIDENT": {"HANDOVER_IN_PROGRESS", "CANCELLED", "FAILED"},
    "HANDOVER_IN_PROGRESS": {"HANDOVER_COMPLETED", "FAILED"},
    "HANDOVER_COMPLETED": {"IN_TRANSIT_TO_DESTINATION", "FAILED"},
    "IN_TRANSIT_TO_DESTINATION": {"COMPLETED", "FAILED"},
}

@router.patch("/recovery/plans/{plan_id}/status")
async def update_recovery_status(
    plan_id: str,
    new_status: str = Query(...),
    notes: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    plan = (await db.execute(
        select(RecoveryPlan).where(RecoveryPlan.id == plan_id).with_for_update()
    )).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Recovery plan not found")
    target = new_status.upper()
    current = plan.status.upper()
    if target not in RECOVERY_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid recovery transition: {current} -> {target}",
        )
    plan.status = target
    if target == "COMPLETED":
        package_ids = (plan.plan_json or {}).get("package_ids", [])
        delivery_ids = (plan.plan_json or {}).get("delivery_ids", [])
        if package_ids:
            packages = (await db.execute(
                select(Package).where(Package.id.in_(package_ids)).with_for_update()
            )).scalars().all()
            for package in packages:
                package.status = "DELIVERED"
        if delivery_ids:
            deliveries = (await db.execute(
                select(Delivery).where(Delivery.id.in_(delivery_ids)).with_for_update()
            )).scalars().all()
            for delivery in deliveries:
                delivery.status = "DELIVERED"
    elif target == "CANCELLED":
        # Cancellation is only allowed before handover, so restore original ownership.
        package_ids = (plan.plan_json or {}).get("package_ids", [])
        delivery_ids = (plan.plan_json or {}).get("delivery_ids", [])
        if package_ids:
            packages = (await db.execute(
                select(Package).where(Package.id.in_(package_ids)).with_for_update()
            )).scalars().all()
            for package in packages:
                package.assigned_vehicle_id = plan.delayed_vehicle_id
                package.status = "IN_TRANSIT"
        if delivery_ids:
            deliveries = (await db.execute(
                select(Delivery).where(Delivery.id.in_(delivery_ids)).with_for_update()
            )).scalars().all()
            for delivery in deliveries:
                delivery.assigned_vehicle_id = plan.delayed_vehicle_id
                delivery.status = "IN_TRANSIT"
    if target in {"COMPLETED", "CANCELLED", "FAILED"}:
        plan.executed_at = plan.executed_at or datetime.now(timezone.utc)
    history = RecoveryStatusHistory(
        id=f"rsh_{uuid4().hex[:12]}",
        recovery_plan_id=plan.id,
        previous_status=current,
        new_status=target,
        notes=notes,
        simulated=True,
    )
    db.add(history)
    await db.commit()
    event = {
        "type": "recovery_status_updated",
        "recovery_plan_id": plan.id,
        "delayed_vehicle_id": plan.delayed_vehicle_id,
        "helper_vehicle_id": plan.helper_vehicle_id,
        "previous_status": current,
        "status": target,
        "notes": notes,
        "simulated": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await manager.broadcast(event)
    return event

@router.get("/recovery/plans/{plan_id}/history")
async def recovery_status_history(plan_id: str, db: AsyncSession = Depends(get_db)):
    if not await db.get(RecoveryPlan, plan_id):
        raise HTTPException(status_code=404, detail="Recovery plan not found")
    rows = (await db.execute(
        select(RecoveryStatusHistory)
        .where(RecoveryStatusHistory.recovery_plan_id == plan_id)
        .order_by(RecoveryStatusHistory.changed_at.asc())
    )).scalars().all()
    return {"recovery_plan_id": plan_id, "history": [
        {"previous_status": row.previous_status, "status": row.new_status,
         "notes": row.notes, "simulated": row.simulated,
         "timestamp": row.changed_at.isoformat()} for row in rows
    ]}
