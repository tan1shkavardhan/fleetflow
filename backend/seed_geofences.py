"""Backward-compatible entry point for demo seeding."""
from Backend.scripts.seed_demo import main
import asyncio
if __name__ == "__main__": asyncio.run(main())
