"""
Simple test-vector emulator used by sandbox verification (optional).
We expose a small function that runs a few checks on a tile and returns pass/fail.
"""

import asyncio
import random

async def run_test_vectors_for_tile(tile, timeout_s: float = 0.1):
    """
    Simulate running a few functional checks on the tile.
    Returns dict: {"passed": bool, "details": {...}, "duration_ms": int}
    """
    start = asyncio.get_event_loop().time()
    # simulate running a few tests
    await asyncio.sleep(timeout_s * random.uniform(0.5, 1.2))
    # simplistic pass/fail: small chance of failure
    passed = random.random() > 0.03
    duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)
    details = {
        "temp_c": tile.metrics.get("temp_c"),
        "error_count": tile.metrics.get("error_count"),
        "crc": tile.metrics.get("last_output_crc")
    }
    return {"passed": passed, "details": details, "duration_ms": duration_ms}
