
import argparse
import asyncio
import math
from datetime import datetime, timezone

import httpx

STARTS = {
    "truck_001": (22.7100, 75.8500),
    "truck_002": (22.7480, 75.8900),
    "truck_003": (22.7600, 75.9200),
    "truck_004": (22.7350, 75.8750),
    "truck_005": (22.7800, 75.9000),
    "truck_006": (22.7000, 75.8400),
    "van_007": (22.7200, 75.8800),
    "van_008": (22.7300, 75.9000),
    "van_009": (22.6900, 75.8600),
    "van_010": (22.7500, 75.8400),
}

SPECS = {
    "truck": (700, 300, 180, 160),
    "van": (350, 220, 140, 125),
}

DELAY_TICKS = 20
BREAKDOWN_TICKS = 120


async def run(base_url, count, interval):
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=10
    ) as client:

        ids = list(STARTS)[:count]

        # Register vehicles
        for vid in ids:
            vehicle_type = "truck" if vid.startswith("truck") else "van"
            capacity, length, width, height = SPECS[vehicle_type]

            try:
                response = await client.post(
                    "/vehicles/",
                    json={
                        "id": vid,
                        "name": vid,
                        "vehicle_type": vehicle_type,
                        "capacity_kg": capacity,
                        "max_payload_kg": capacity,
                        "cargo_length_cm": length,
                        "cargo_width_cm": width,
                        "cargo_height_cm": height,
                    },
                )

                if response.status_code not in (201, 409):
                    print(f"Registration error: {vid} - {response.text}")

            except httpx.HTTPError as exc:
                raise SystemExit(f"Backend connection failed: {exc}")

        print("\n========== FLEETFLOW DEMO ==========")
        print("truck_003 : DELAY scenario (40 seconds)")
        print("truck_006 : BREAKDOWN scenario (4 minutes)")
        print("Other vehicles : Normal movement")
        print("====================================\n")

        tick = 0

        try:
            while True:

                for idx, vid in enumerate(ids):
                    lat0, lon0 = STARTS[vid]

                    # BREAKDOWN: truck_006 stays at exactly the same location
                    if vid == "truck_006" and tick < BREAKDOWN_TICKS:
                        lat, lon = lat0, lon0
                        speed = 0.0

                    # NORMAL ROUTE: truck_001 crosses the warehouse geofence
                    elif vid == "truck_001":
                        route = [
                            (22.7100, 75.8500),
                            (22.7196, 75.8577),
                            (22.7300, 75.8700),
                            (22.7100, 75.8500),
                        ]

                        lat, lon = route[tick % len(route)]
                        speed = 25.0

                    else:
                        phase = tick * 0.02 + idx * 0.7

                        lat = lat0 + 0.0018 * math.sin(phase)
                        lon = lon0 + 0.0018 * math.cos(phase)

                        # DELAY: truck_003 temporarily travels slowly
                        if vid == "truck_003":
                            speed = 5.0 if tick < DELAY_TICKS else 32.0

                        # BREAKDOWN RECOVERY: truck_006 resumes after 4 minutes
                        elif vid == "truck_006":
                            speed = 28.0

                        else:
                            speed = 22.0 + (idx % 4) * 5.0

                    payload = {
                        "vehicle_id": vid,
                        "latitude": round(lat, 7),
                        "longitude": round(lon, 7),
                        "speed": speed,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                    try:
                        response = await client.post(
                            "/telemetry/",
                            json=payload
                        )

                        if response.is_error:
                            print(
                                f"ERROR {vid}: "
                                f"{response.status_code} {response.text[:200]}"
                            )

                    except httpx.HTTPError as exc:
                        print(f"Telemetry error for {vid}: {exc}")

                    if vid in ("truck_003", "truck_006"):
                        print(
                            f"Tick {tick:03d} | "
                            f"{vid} | {speed} km/h"
                        )

                tick += 1
                await asyncio.sleep(interval)

        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\nFleetFlow simulation stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000"
    )

    parser.add_argument(
        "--vehicles",
        type=int,
        default=10,
        choices=range(1, 11)
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=2.0
    )

    args = parser.parse_args()

    if args.interval < 0.25:
        parser.error("--interval must be at least 0.25 seconds")

    asyncio.run(run(args.url, args.vehicles, args.interval))
