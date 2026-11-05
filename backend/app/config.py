from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "FleetFlow API"
    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "postgresql+asyncpg://fleetflow:fleetflow@localhost:5432/fleetflow"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    vehicle_geo_key: str = "vehicles:locations"
    telemetry_stream_key: str = "telemetry:stream"
    telemetry_stream_maxlen: int = 100000
    delay_threshold_ratio: float = 0.4
    delay_consecutive_limit: int = 3
    delay_recovery_ratio: float = 0.6
    prolonged_stop_seconds: int = 20  # demo default; use >=300 seconds in production
    default_nearby_radius_km: float = 20.0
    demo_breakdown_vehicles: str = "truck_006"
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def breakdown_vehicle_ids(self) -> set[str]:
        return {x.strip() for x in self.demo_breakdown_vehicles.split(",") if x.strip()}

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
