from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from Backend.app.database import Base

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    vehicle_type: Mapped[str] = mapped_column(String(50), default="van")
    capacity_kg: Mapped[float] = mapped_column(Float, default=500.0)
    cargo_length_cm: Mapped[float] = mapped_column(Float, default=250.0)
    cargo_width_cm: Mapped[float] = mapped_column(Float, default=160.0)
    cargo_height_cm: Mapped[float] = mapped_column(Float, default=140.0)
    max_payload_kg: Mapped[float] = mapped_column(Float, default=500.0)
    status: Mapped[str] = mapped_column(String(30), default="MOVING")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Telemetry(Base):
    __tablename__ = "telemetry_history"
    __table_args__ = (Index("ix_telemetry_vehicle_time", "vehicle_id", "recorded_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    speed: Mapped[float] = mapped_column(Float)
    heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

class Geofence(Base):
    __tablename__ = "geofences"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    demo_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Package(Base):
    __tablename__ = "packages"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    description: Mapped[str] = mapped_column(String(240), default="")
    length_cm: Mapped[float] = mapped_column(Float)
    width_cm: Mapped[float] = mapped_column(Float)
    height_cm: Mapped[float] = mapped_column(Float)
    weight_kg: Mapped[float] = mapped_column(Float)
    delivery_id: Mapped[str | None] = mapped_column(ForeignKey("deliveries.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    allowed_rotations: Mapped[str] = mapped_column(String(30), default="ALL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Delivery(Base):
    __tablename__ = "deliveries"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(160), default="Customer")
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    service_minutes: Mapped[int] = mapped_column(Integer, default=5)
    time_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class RecoveryPlan(Base):
    __tablename__ = "recovery_plans"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    delayed_vehicle_id: Mapped[str] = mapped_column(String(80), index=True)
    helper_vehicle_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="PROPOSED")
    radius_km: Mapped[float] = mapped_column(Float)
    plan_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class AlertRecord(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(String(80), index=True)
    alert_type: Mapped[str] = mapped_column(String(40), index=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecoveryStatusHistory(Base):
    __tablename__ = "recovery_status_history"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    recovery_plan_id: Mapped[str] = mapped_column(
        ForeignKey("recovery_plans.id", ondelete="CASCADE"), index=True
    )
    previous_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_status: Mapped[str] = mapped_column(String(40), index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
