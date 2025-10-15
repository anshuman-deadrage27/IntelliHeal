"""
Small helper to provide a periodic ticking environment.
We keep this code simple and asyncio-based (no SimPy dependency).
"""

import asyncio

class SimEnv:
    def __init__(self, board, tick_interval: float = 0.05):
        self.board = board
        self.tick_interval = tick_interval
        self._task = None
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self):
        try:
            while self._running:
                # perform physics tick
                self.board.tick_all()
                await asyncio.sleep(self.tick_interval)
        except asyncio.CancelledError:
            return
