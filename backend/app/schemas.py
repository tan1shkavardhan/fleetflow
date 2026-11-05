from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class VehicleCreate(BaseModel):
    id: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = ""
    vehicle_type: str = "van"
    capacity_kg: float = Field(default=500, gt=0)
    cargo_length_cm: float = Field(default=250, gt=0)
    cargo_width_cm: float = Field(default=160, gt=0)
    cargo_height_cm: float = Field(default=140, gt=0)
    max_payload_kg: float = Field(default=500, gt=0)
    active: bool = True

class VehicleOut(VehicleCreate):
    status: str = "MOVING"
    created_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)

class TelemetryIn(BaseModel):
    vehicle_id: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    speed: float = Field(ge=0, le=250)
    heading: float | None = Field(default=None, ge=0, lt=360)
    timestamp: datetime | None = None

class GeofenceCreate(BaseModel):
    id: str | None = Field(default=None, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: float = Field(gt=0, le=100000)
    active: bool = True

class GeofenceOut(GeofenceCreate):
    id: str
    demo_seed: bool = False
    model_config = ConfigDict(from_attributes=True)

class PackageCreate(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    description: str = ""
    length_cm: float = Field(gt=0, le=2000)
    width_cm: float = Field(gt=0, le=2000)
    height_cm: float = Field(gt=0, le=2000)
    weight_kg: float = Field(gt=0, le=5000)
    delivery_id: str | None = None
    assigned_vehicle_id: str | None = None
    allowed_rotations: Literal["ALL", "UPRIGHT"] = "ALL"

class PackageOut(PackageCreate):
    status: str = "PENDING"
    model_config = ConfigDict(from_attributes=True)

class DeliveryCreate(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    customer_name: str = "Customer"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    priority: int = Field(default=3, ge=1, le=5)
    service_minutes: int = Field(default=5, ge=0, le=1440)
    time_window_start: datetime | None = None
    time_window_end: datetime | None = None
    assigned_vehicle_id: str | None = None

    @model_validator(mode="after")
    def validate_time_window(self):
        if self.time_window_start and self.time_window_end and self.time_window_end <= self.time_window_start:
            raise ValueError("time_window_end must be later than time_window_start")
        return self

class DeliveryOut(DeliveryCreate):
    status: str = "PENDING"
    model_config = ConfigDict(from_attributes=True)

class NearbyQuery(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=20, gt=0, le=500)
    exclude_vehicle_id: str | None = None

class RecoveryAnalyzeRequest(BaseModel):
    delayed_vehicle_id: str
    package_ids: list[str] = Field(default_factory=list)
    delivery_ids: list[str] = Field(default_factory=list)
    radius_km: float = Field(default=20, gt=0, le=500)
    max_candidates: int = Field(default=5, ge=1, le=25)
    origin_latitude: float | None = Field(default=None, ge=-90, le=90)
    origin_longitude: float | None = Field(default=None, ge=-180, le=180)
    apply_accessibility: bool = True

class RecoveryExecuteRequest(BaseModel):
    helper_vehicle_id: str
    package_ids: list[str] = Field(default_factory=list)
    delivery_ids: list[str] = Field(default_factory=list)

class RouteOptimizeRequest(BaseModel):
    vehicle_id: str
    delivery_ids: list[str] = Field(default_factory=list)
    start_latitude: float | None = Field(default=None, ge=-90, le=90)
    start_longitude: float | None = Field(default=None, ge=-180, le=180)
