import asyncio
from sqlalchemy import select
from Backend.app.database import SessionLocal, create_schema
from Backend.app.models import Delivery, Geofence, Package, Telemetry, Vehicle

GEOFENCES = [
    ("Indore Warehouse", 22.7196, 75.8577, 450), ("Vijay Nagar Hub", 22.7533, 75.8937, 350),
    ("Rau Distribution Point", 22.6395, 75.8070, 400), ("Dewas Naka Hub", 22.7905, 75.9140, 350),
    ("Palasia Service Zone", 22.7240, 75.8839, 250), ("Super Corridor Hub", 22.7490, 75.8060, 500),
    ("Rajendra Nagar Depot", 22.6760, 75.8390, 350), ("Bhawarkua Zone", 22.6930, 75.8660, 300),
    ("MR-10 Logistics Zone", 22.7700, 75.9250, 400), ("Pithampur Gate Demo", 22.6100, 75.6900, 500),
]
VEHICLES = [
    ("truck_001", 500, 250, 160, 140), ("truck_002", 700, 300, 180, 160), ("truck_003", 600, 280, 170, 150),
    ("truck_004", 500, 250, 160, 140), ("truck_005", 800, 320, 190, 170), ("truck_006", 500, 250, 160, 140),
    ("van_007", 300, 200, 130, 120), ("van_008", 300, 200, 130, 120), ("van_009", 350, 220, 140, 125),
    ("van_010", 400, 230, 150, 130),
]

async def main():
    await create_schema()
    async with SessionLocal() as db:
        for idx, (name, lat, lon, radius) in enumerate(GEOFENCES, 1):
            gid = f"demo_geo_{idx:02d}"
            # Preserve pre-existing user records and legacy seed records; do not duplicate by name
            # or exact circle even if an older seed used a different ID.
            by_id = await db.get(Geofence, gid)
            by_name = (await db.execute(select(Geofence).where(Geofence.name == name))).scalar_one_or_none()
            same_circle = (await db.execute(select(Geofence).where(Geofence.latitude == lat, Geofence.longitude == lon, Geofence.radius_m == radius))).scalar_one_or_none()
            if not by_id and not by_name and not same_circle:
                db.add(Geofence(id=gid, name=name, latitude=lat, longitude=lon, radius_m=radius, active=True, demo_seed=True))
        for vid, payload, length, width, height in VEHICLES:
            if not await db.get(Vehicle, vid):
                db.add(Vehicle(id=vid, name=vid.replace("_", " ").title(), vehicle_type="truck" if vid.startswith("truck") else "van",
                    capacity_kg=payload, max_payload_kg=payload, cargo_length_cm=length, cargo_width_cm=width, cargo_height_cm=height,
                    status="MOVING", active=True))
        # Demo delivery and parcel records let recovery/packing endpoints be tested immediately.
        deliveries = [
            ("delivery_001", "Customer A", 22.7300, 75.8700, 5), ("delivery_002", "Customer B", 22.7460, 75.8950, 4),
            ("delivery_003", "Customer C", 22.7650, 75.9100, 3), ("delivery_004", "Customer D", 22.7050, 75.8450, 4),
        ]
        for did, customer, lat, lon, priority in deliveries:
            if not await db.get(Delivery, did):
                db.add(Delivery(id=did, customer_name=customer, latitude=lat, longitude=lon, priority=priority, assigned_vehicle_id="truck_001", status="PENDING"))
        await db.flush()
        packages = [
            ("pkg_001", "delivery_001", 40, 30, 20, 5), ("pkg_002", "delivery_002", 50, 40, 30, 8),
            ("pkg_003", "delivery_003", 30, 30, 30, 4), ("pkg_004", "delivery_004", 35, 25, 20, 3),
        ]
        for pid, did, l, w, h, kg in packages:
            if not await db.get(Package, pid):
                db.add(Package(id=pid, description=f"Demo parcel {pid}", delivery_id=did, assigned_vehicle_id="truck_001",
                    length_cm=l, width_cm=w, height_cm=h, weight_kg=kg, status="PENDING", allowed_rotations="ALL"))
        await db.commit()
    print("Seed complete: 10 demo geofences, 10 vehicles, 4 deliveries, 4 packages. Safe to rerun.")

if __name__ == "__main__": asyncio.run(main())
