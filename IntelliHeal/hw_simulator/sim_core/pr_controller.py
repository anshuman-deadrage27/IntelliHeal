"""
Partial reconfiguration controller simulator.
Provides async handle_reconfigure that returns cmd_result dict.
"""

import asyncio
import time
import random
from typing import Dict

class PRController:
    def __init__(self, board, warm_swap_ms: float = 5.0, cold_pr_ms_per_kb: float = 2.0, failure_rate: float = 0.02):
        self.board = board
        self.warm_swap_ms = warm_swap_ms
        self.cold_pr_ms_per_kb = cold_pr_ms_per_kb
        self.failure_rate = failure_rate

    async def handle_reconfigure(self, cmd: Dict):
        """
        cmd: dict with keys {cmd_id, target_node, action, spare_id, delta_state}
        Returns a result dict with msg_type cmd_result.
        """
        cmd_id = cmd.get("cmd_id")
        action = cmd.get("action")
        target = cmd.get("target_node")
        spare = cmd.get("spare_id")
        start = time.time()

        # Fast swap path
        if action == "fast_swap" and spare:
            dur = (self.warm_swap_ms / 1000.0) + random.uniform(0.001, 0.01)
            await asyncio.sleep(dur)
            # perform swap
            res = self.board.perform_fast_swap(target, spare)
        elif action == "partial_reconfig":
            # estimate size from board map
            try:
                binfo = self.board.region_map.get(target, {})
                kb = max(1, int(binfo.get("bitstream_kb", 50)))
            except Exception:
                kb = 50
            dur = (kb * self.cold_pr_ms_per_kb) / 1000.0 + random.uniform(0.01, 0.05)
            await asyncio.sleep(dur)
            # apply: clear fault as part of PR emulation
            try:
                self.board.clear_fault(target)
            except Exception:
                pass
            res = {"status": "reconfigured"}
        elif action == "isolate":
            await asyncio.sleep(0.01)
            try:
                self.board.tiles[target].status = "isolated"
            except Exception:
                pass
            res = {"status": "isolated"}
        else:
            # unsupported action - small delay
            await asyncio.sleep(0.02)
            res = {"status": "noop"}

        failed = random.random() < self.failure_rate
        duration_ms = int((time.time() - start) * 1000)
        if failed:
            return {"msg_type": "cmd_result", "cmd_id": cmd_id, "status": "failed", "duration_ms": duration_ms, "sandbox_passed": False}
        else:
            return {"msg_type": "cmd_result", "cmd_id": cmd_id, "status": "success", "duration_ms": duration_ms, "sandbox_passed": True}
