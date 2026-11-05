from redis.asyncio import Redis
from Backend.app.config import settings

redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True, health_check_interval=30)

async def check_redis() -> bool:
    await redis_client.ping()
    return True
