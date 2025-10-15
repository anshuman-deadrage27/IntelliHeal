"""
Fault Detector
Consumes telemetry messages and detects faults based on heartbeat/timeouts and metric thresholds.
Emits fault events via a user-registered callback.
"""

import asyncio
import time
from typing import Callable, Dict, Any

class FaultDetector:
    def __init__(self, telemetry_queue: asyncio.Queue, on_fault_callback: Callable[[Dict[str,Any]], None],
                 heartbeat_timeout_ms: int = 50, error_threshold: int = 5):
        """
        telemetry_queue: asyncio.Queue where telemetry JSON messages arrive
        on_fault_callback: function to call when a fault is detected (fault_event)
        heartbeat_timeout_ms: missing heartbeat threshold to mark node suspicious
        error_threshold: metric-based threshold to mark node faulty
        """
        self.telemetry_queue = telemetry_queue
        self.on_fault = on_fault_callback
        self.heartbeat_timeout_ms = heartbeat_timeout_ms
        self.error_threshold = error_threshold

        self.node_last_seen: Dict[str, float] = {}
        self.node_metrics: Dict[str, Dict] = {}
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
                msg = await self.telemetry_queue.get()
                await self._process_msg(msg)
            except Exception as e:
                print("FaultDetector loop error:", e)
                await asyncio.sleep(0.05)

    async def _process_msg(self, msg: dict):
        """
        Expected telemetry message patterns:
        - heartbeat: {"msg_type":"heartbeat","node_id":"tile_A","timestamp":..., "metrics": {...}}
        - status_snapshot or other messages also accepted.
        """
        mtype = msg.get("msg_type", "").lower()
        ts = msg.get("timestamp", time.time())
        if mtype == "heartbeat" or "node_id" in msg:
            node_id = msg.get("node_id") or msg.get("node")
            if not node_id:
                return
            self.node_last_seen[node_id] = ts
            metrics = msg.get("metrics", {})
            self.node_metrics[node_id] = metrics
            # quick checks
            error_count = metrics.get("error_count", 0)
            status_code = msg.get("status_code", 0) or metrics.get("status_code", 0)
            if error_count >= self.error_threshold or status_code != 0:
                # emit fault event
                evt = {
                    "fault_id": f"fault_{node_id}_{int(ts)}",
                    "node_id": node_id,
                    "fault_type": "error_count_exceeded" if error_count >= self.error_threshold else "status_nonzero",
                    "severity": "major" if error_count >= self.error_threshold else "minor",
                    "timestamp": ts,
                    "evidence": {"error_count": error_count, "status_code": status_code}
                }
                await self._emit_fault(evt)
        else:
            # other messages - if they include fault info, pass through
            if mtype == "fault_event":
                await self._emit_fault(msg)

        # After processing message, run heartbeat sweep to detect missing nodes (periodic)
        await self._check_heartbeat_gaps()

    async def _check_heartbeat_gaps(self):
        now = time.time()
        to_report = []
        for node, last in list(self.node_last_seen.items()):
            delta_ms = (now - last) * 1000.0
            if delta_ms > self.heartbeat_timeout_ms:
                # suspicious / fault
                evt = {
                    "fault_id": f"hb_miss_{node}_{int(now)}",
                    "node_id": node,
                    "fault_type": "missing_heartbeat",
                    "severity": "critical" if delta_ms > 5*self.heartbeat_timeout_ms else "major",
                    "timestamp": now,
                    "evidence": {"last_seen_ms_ago": delta_ms}
                }
                to_report.append(evt)
                # delete or keep? keep timestamp but mark we reported once to avoid floods
                # For simplicity, we will set last_seen to now to avoid duplicate immediate reports.
                self.node_last_seen[node] = now
        for evt in to_report:
            await self._emit_fault(evt)

    async def _emit_fault(self, fault_event: dict):
        try:
            self.on_fault(fault_event)
        except Exception as e:
            print("FaultDetector emit error:", e)
