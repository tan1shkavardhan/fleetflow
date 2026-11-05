from contextlib import asynccontextmanager
from Backend.app.routers import alerts, cargo, geofences, optimization, telemetry, vehicles
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from Backend.app.config import settings
from Backend.app.database import create_schema, engine
from Backend.app.redis_client import redis_client
from Backend.app.routers import websocket

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables for frictionless local testing. Alembic is recommended for production.
    await create_schema()
    try:
        await redis_client.ping()
    except Exception:
        # API starts so /health can explain infrastructure state; dependent routes fail clearly.
        pass
    yield
    await redis_client.aclose()
    await engine.dispose()

app = FastAPI(title=settings.app_name, version="2.0.0", description="Real-time fleet monitoring, 3D cargo packing, helper allocation and route recovery.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(telemetry.router)
app.include_router(vehicles.router)
app.include_router(geofences.router)
app.include_router(cargo.router)
app.include_router(optimization.router)
app.include_router(alerts.router)
app.include_router(websocket.router)

@app.get("/")
async def root():
    return {"name": settings.app_name, "version": "2.0.0", "status": "running", "docs": "/docs"}

@app.get("/health")
async def health():
    import sqlalchemy
    database_ok = False
    redis_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
        database_ok = True
    except Exception:
        pass
    try:
        await redis_client.ping()
        redis_ok = True
    except Exception:
        pass
    return {"status": "healthy" if database_ok and redis_ok else "degraded", "database": database_ok, "redis": redis_ok}
