"""
Telemetry Collector
Receives telemetry JSON messages from HAL adapter and forwards them into an asyncio queue.
This module is hardware-agnostic: it only expects JSON messages with node ids and metrics.
"""

import asyncio
import json
from typing import Callable

class TelemetryCollector:
    def __init__(self, hal, queue: asyncio.Queue):
        """
        hal: HAL adapter instance (must implement async read_json())
        queue: asyncio.Queue to which telemetry messages are put
        """
        self.hal = hal
        self.queue = queue
        self._task = None
        self._running = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        if self._task:
            await self._task

    async def _run(self):
        while self._running:
            try:
                msg = await self.hal.read_json()
                if msg is None:
                    await asyncio.sleep(0.01)
                    continue
                # Basic validation - we expect dicts with msg_type or telemetry content
                if isinstance(msg, dict):
                    await self.queue.put(msg)
                else:
                    # ignore malformed
                    continue
            except Exception as e:
                # transient HAL read error: log and continue
                print("TelemetryCollector error:", e)
                await asyncio.sleep(0.1)
