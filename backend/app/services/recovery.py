from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from Backend.app.models import Delivery, Package, RecoveryPlan, Telemetry, Vehicle
from Backend.app.redis_client import redis_client
from Backend.app.config import settings
from Backend.app.services.geo import distance_km
from Backend.app.services.packing import pack_packages
from Backend.app.services.routing import optimize_route

async def latest_position(db: AsyncSession, vehicle_id: str) -> tuple[float, float] | None:
    row = (await db.execute(select(Telemetry).where(Telemetry.vehicle_id == vehicle_id).order_by(Telemetry.recorded_at.desc(), Telemetry.id.desc()).limit(1))).scalar_one_or_none()
    if row:
        return row.latitude, row.longitude
    try:
        pos = await redis_client.geopos(settings.vehicle_geo_key, vehicle_id)
        if pos and pos[0]:
            lon, lat = pos[0]
            return float(lat), float(lon)
    except Exception:
        pass
    return None

async def analyze_recovery(db: AsyncSession, delayed_vehicle_id: str, package_ids: list[str], delivery_ids: list[str], radius_km: float, max_candidates: int, origin_latitude: float | None = None, origin_longitude: float | None = None, apply_accessibility: bool = True) -> dict:
    delayed = await db.get(Vehicle, delayed_vehicle_id)
    if not delayed:
        raise ValueError(f"Delayed vehicle '{delayed_vehicle_id}' was not found.")
    origin = None
    if origin_latitude is not None and origin_longitude is not None:
        origin = (origin_latitude, origin_longitude)
    else:
        origin = await latest_position(db, delayed_vehicle_id)
    if not origin:
        raise ValueError("No current position is available for the delayed vehicle. Send telemetry or provide origin coordinates.")
    if not package_ids and delivery_ids:
        rows = (await db.execute(select(Package).where(Package.delivery_id.in_(delivery_ids)))).scalars().all()
        packages = rows
    elif package_ids:
        rows = (await db.execute(select(Package).where(Package.id.in_(package_ids)))).scalars().all()
        packages = rows
    else:
        stmt = select(Package).where(Package.assigned_vehicle_id == delayed_vehicle_id, Package.status.in_(["PENDING", "IN_TRANSIT"]))
        rows = (await db.execute(stmt)).scalars().all()
        packages = rows
    found_ids = {p.id for p in packages}
    missing = sorted(set(package_ids) - found_ids)
    if missing:
        raise ValueError("Unknown package IDs: " + ", ".join(missing))
    if not packages:
        raise ValueError("No packages were found for this recovery request. Provide package_ids/delivery_ids or assign pending packages to the delayed vehicle.")
    incorrectly_assigned = [p.id for p in packages if p.assigned_vehicle_id not in (None, delayed_vehicle_id)]
    if incorrectly_assigned:
        raise ValueError("Packages are not assigned to the delayed vehicle: " + ", ".join(incorrectly_assigned))
    delivery_rows = (await db.execute(select(Delivery).where(Delivery.id.in_(delivery_ids or [p.delivery_id for p in packages if p.delivery_id])))).scalars().all()
    delivery_by_id = {d.id: d for d in delivery_rows}
    for p in packages:
        if p.delivery_id and p.delivery_id not in delivery_by_id:
            d = await db.get(Delivery, p.delivery_id)
            if d:
                delivery_by_id[d.id] = d
    delivery_order = {d.id: i for i, d in enumerate(sorted(delivery_by_id.values(), key=lambda d: (-d.priority, d.time_window_end or datetime.max.replace(tzinfo=timezone.utc), d.id)))}
    busy_statuses = {"ASSIGNED", "EN_ROUTE_TO_INCIDENT", "ARRIVED_AT_INCIDENT",
                     "HANDOVER_IN_PROGRESS", "HANDOVER_COMPLETED",
                     "IN_TRANSIT_TO_DESTINATION"}
    busy_rows = (await db.execute(
        select(RecoveryPlan.helper_vehicle_id).where(
            RecoveryPlan.status.in_(busy_statuses),
            RecoveryPlan.helper_vehicle_id.is_not(None)
        )
    )).all()
    busy_vehicle_ids = {row[0] for row in busy_rows}
    candidates = (await db.execute(select(Vehicle).where(
        Vehicle.active.is_(True), Vehicle.id != delayed_vehicle_id,
        Vehicle.status.not_in(["BREAKDOWN", "INACTIVE", "UNAVAILABLE", "OFFLINE"])
    ))).scalars().all()
    evaluated = []
    for v in candidates:
        if v.id in busy_vehicle_ids:
            continue
        pos = await latest_position(db, v.id)
        if not pos:
            continue
        distance = distance_km(origin[0], origin[1], pos[0], pos[1])
        if distance > radius_km:
            continue
        # Existing cargo consumes both payload and physical cargo-bay space.
        existing_stmt = select(Package).where(Package.assigned_vehicle_id == v.id, Package.status.in_(["PENDING", "IN_TRANSIT", "REASSIGNED"]))
        if found_ids:
            existing_stmt = existing_stmt.where(Package.id.not_in(found_ids))
        existing = (await db.execute(existing_stmt)).scalars().all()
        existing_weight = sum(p.weight_kg for p in existing)
        vehicle_dict = {"id": v.id, "cargo_length_cm": v.cargo_length_cm, "cargo_width_cm": v.cargo_width_cm,
                        "cargo_height_cm": v.cargo_height_cm, "capacity_kg": v.capacity_kg,
                        "max_payload_kg": v.max_payload_kg}
        # Pack existing cargo and proposed transfer cargo together. This prevents a helper
        # from being accepted merely because the new packages fit in an already-occupied bay.
        all_cargo = list(existing) + list(packages)
        package_dicts = [{"id": p.id, "delivery_id": p.delivery_id, "length_cm": p.length_cm, "width_cm": p.width_cm,
                          "height_cm": p.height_cm, "weight_kg": p.weight_kg, "allowed_rotations": p.allowed_rotations} for p in all_cargo]
        candidate_delivery_by_id = dict(delivery_by_id)
        candidate_delivery_order = dict(delivery_order)
        all_delivery_ids = {p.delivery_id for p in all_cargo if p.delivery_id}
        missing_delivery_ids = all_delivery_ids - set(candidate_delivery_by_id)
        if missing_delivery_ids:
            extra_deliveries = (await db.execute(select(Delivery).where(Delivery.id.in_(missing_delivery_ids)))).scalars().all()
            for d in extra_deliveries:
                candidate_delivery_by_id[d.id] = d
                candidate_delivery_order[d.id] = len(candidate_delivery_order)
        packing = pack_packages(vehicle_dict, package_dicts, candidate_delivery_order, apply_accessibility)
        route_deliveries = [d for d in candidate_delivery_by_id.values()]
        route = optimize_route(pos, [{"id": d.id, "customer_name": d.customer_name, "latitude": d.latitude, "longitude": d.longitude,
                                      "priority": d.priority, "service_minutes": d.service_minutes, "time_window_start": d.time_window_start, "time_window_end": d.time_window_end} for d in route_deliveries])
        # Direction is reported only when a heading is available; coordinates alone
        # cannot prove the candidate is travelling toward the affected destination.
        latest = (await db.execute(select(Telemetry).where(
            Telemetry.vehicle_id == v.id
        ).order_by(Telemetry.recorded_at.desc(), Telemetry.id.desc()).limit(1))).scalar_one_or_none()
        heading_available = latest is not None and latest.heading is not None
        destination_compatible = bool(route_deliveries)
        evaluated.append({"vehicle_id": v.id, "vehicle_type": v.vehicle_type, "distance_km": round(distance, 3),
                          "position": {"latitude": pos[0], "longitude": pos[1]},
                          "existing_payload_kg": round(existing_weight, 2),
                          "available_payload_kg": round(max(0, v.max_payload_kg-existing_weight), 2),
                          "existing_package_ids": [p.id for p in existing], "transfer_package_ids": [p.id for p in packages],
                          "direction_compatible": None if not heading_available else "not_route_verified",
                          "destination_compatible": destination_compatible,
                          "route_compatibility": "UNCERTAIN" if not heading_available else "DESTINATION_ROUTE_ESTIMATED",
                          "packing": packing, "route": route, "feasible": packing["feasible"],
                          "recommendation": "SUITABLE" if packing["feasible"] else "UNSUITABLE",
                          "rejection_reason": packing.get("failure_reason")})
    evaluated.sort(key=lambda c: (not c["feasible"], c["distance_km"], c["route"]["total_distance_km"]))
    return {"delayed_vehicle_id": delayed_vehicle_id, "origin": {"latitude": origin[0], "longitude": origin[1]},
            "radius_km": radius_km, "package_ids": [p.id for p in packages], "delivery_ids": list(delivery_by_id),
            "candidate_count": len(evaluated), "recommended_candidate": next((c for c in evaluated if c["feasible"]), None),
            "candidates": evaluated[:max_candidates], "generated_at": datetime.now(timezone.utc).isoformat(),
            "notes": ["3D packing uses a deterministic heuristic; feasibility is checked, global optimality is not guaranteed.",
                      "Route distance uses great-circle distances; road-network travel times are not included."]}

async def execute_recovery(db: AsyncSession, delayed_vehicle_id: str, helper_vehicle_id: str, package_ids: list[str], delivery_ids: list[str], plan: dict) -> dict:
    helper = (await db.execute(
        select(Vehicle).where(Vehicle.id == helper_vehicle_id).with_for_update()
    )).scalar_one_or_none()
    if not helper or not helper.active or helper.status in {"BREAKDOWN", "INACTIVE", "UNAVAILABLE", "OFFLINE"}:
        raise ValueError("Helper vehicle is missing, inactive, or marked as breakdown.")
    chosen = (await db.execute(
        select(Package).where(Package.id.in_(package_ids)).with_for_update()
    )).scalars().all() if package_ids else []
    if package_ids and {p.id for p in chosen} != set(package_ids):
        raise ValueError("One or more package IDs were not found.")
    if any(p.assigned_vehicle_id not in (None, delayed_vehicle_id) for p in chosen):
        raise ValueError("One or more packages are no longer assigned to the delayed vehicle.")
    delivery_rows = (await db.execute(select(Delivery).where(Delivery.id.in_(delivery_ids)))).scalars().all() if delivery_ids else []
    if delivery_ids and {d.id for d in delivery_rows} != set(delivery_ids):
        raise ValueError("One or more delivery IDs were not found.")
    # Require that the chosen helper was evaluated as feasible in the supplied analysis result.
    candidate = next((c for c in plan.get("candidates", []) if c.get("vehicle_id") == helper_vehicle_id), None)
    if not candidate or not candidate.get("feasible"):
        raise ValueError("The helper vehicle has not been verified as feasible in the recovery analysis.")
    # Revalidate current position and cargo immediately before committing assignments. The
    # analysis may be stale if another workflow changed a helper's cargo after it was generated.
    helper_position = await latest_position(db, helper_vehicle_id)
    origin_obj = plan.get("origin") or {}
    if not helper_position or "latitude" not in origin_obj or "longitude" not in origin_obj:
        raise ValueError("Current helper/delayed vehicle location is unavailable; analyze again after telemetry arrives.")
    if distance_km(float(origin_obj["latitude"]), float(origin_obj["longitude"]), helper_position[0], helper_position[1]) > float(plan.get("radius_km", 20)):
        raise ValueError("The selected helper is no longer within the analyzed radius. Analyze recovery again.")
    existing_stmt = select(Package).where(Package.assigned_vehicle_id == helper_vehicle_id, Package.status.in_(["PENDING", "IN_TRANSIT", "REASSIGNED"]))
    if package_ids:
        existing_stmt = existing_stmt.where(Package.id.not_in(package_ids))
    existing = (await db.execute(existing_stmt)).scalars().all()
    all_cargo = list(existing) + list(chosen)
    delivery_ids_for_order = {p.delivery_id for p in all_cargo if p.delivery_id}
    current_deliveries = (await db.execute(select(Delivery).where(Delivery.id.in_(delivery_ids_for_order)))).scalars().all() if delivery_ids_for_order else []
    order = {d.id: i for i, d in enumerate(sorted(current_deliveries, key=lambda d: (-d.priority, d.time_window_end or datetime.max.replace(tzinfo=timezone.utc), d.id)))}
    current_packing = pack_packages({"id": helper.id, "cargo_length_cm": helper.cargo_length_cm, "cargo_width_cm": helper.cargo_width_cm,
        "cargo_height_cm": helper.cargo_height_cm, "max_payload_kg": helper.max_payload_kg},
        [{"id": p.id, "delivery_id": p.delivery_id, "length_cm": p.length_cm, "width_cm": p.width_cm, "height_cm": p.height_cm,
          "weight_kg": p.weight_kg, "allowed_rotations": p.allowed_rotations} for p in all_cargo], order, True)
    if not current_packing["feasible"]:
        raise ValueError("Helper cargo changed after analysis and the transfer is no longer feasible: " + str(current_packing.get("failure_reason")))
    plan["execution_revalidation"] = {"feasible": True, "packing": current_packing, "checked_at": datetime.now(timezone.utc).isoformat()}
    for p in chosen:
        p.assigned_vehicle_id = helper_vehicle_id
        p.status = "REASSIGNED"
    for d in delivery_rows:
        d.assigned_vehicle_id = helper_vehicle_id
        d.status = "REASSIGNED"
    plan_id = f"recovery_{uuid4().hex[:12]}"
    from Backend.app.models import RecoveryPlan, RecoveryStatusHistory
    record = RecoveryPlan(id=plan_id, delayed_vehicle_id=delayed_vehicle_id, helper_vehicle_id=helper_vehicle_id,
                          status="ASSIGNED", radius_km=float(plan.get("radius_km", 20)), plan_json=plan,
                          executed_at=datetime.now(timezone.utc))
    db.add(record)
    db.add(RecoveryStatusHistory(
        id=f"rsh_{uuid4().hex[:12]}", recovery_plan_id=plan_id,
        previous_status=None, new_status="ASSIGNED",
        notes="Administrator approved recovery assignment.",
        simulated=True
    ))
    await db.commit()
    return {"recovery_plan_id": plan_id, "status": "ASSIGNED", "delayed_vehicle_id": delayed_vehicle_id,
            "helper_vehicle_id": helper_vehicle_id, "reassigned_package_ids": [p.id for p in chosen],
            "reassigned_delivery_ids": [d.id for d in delivery_rows]}
