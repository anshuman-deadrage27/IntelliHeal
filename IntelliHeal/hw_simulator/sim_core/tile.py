"""
Tile model - represents a reconfigurable region on the board.
"""

import time
import random
from typing import Dict, Optional


class Tile:
    def __init__(self, tile_id: str, function: str = "generic", base_temp: float = 40.0):
        self.tile_id = tile_id
        self.function = function
        self.status = "ok"  # ok / degraded / failed / isolated / spare
        self.metrics: Dict[str, float] = {
            "temp_c": base_temp,
            "voltage_v": 1.0,
            "load": 0.0,
            "error_count": 0.0,
            "last_output_crc": "0x0"
        }
        self.last_heartbeat = time.time()
        self.heartbeat_period = 0.005  # internal heartbeat (s)
        self._forced_fault: Optional[Dict] = None
        self._fault_until: Optional[float] = None
        self.pr_loaded: Optional[str] = None
        self.is_spare = False

    def snapshot(self):
        """Return serializable heartbeat/status snapshot."""
        return {
            "msg_type": "heartbeat",
            "node_id": self.tile_id,
            "timestamp": time.time(),
            "metrics": dict(self.metrics),
            "status": self.status
        }

    def apply_fault(self, fault_type: str, duration_s: Optional[float] = None, params: Optional[dict] = None):
        """Inject (simulate) a fault."""
        params = params or {}
        self._forced_fault = {"fault_type": fault_type, "params": params}
        self._fault_until = None if duration_s is None else (time.time() + duration_s)

        if fault_type == "missing_heartbeat":
            # tile will stop heartbeats (status -> failed)
            self.status = "failed"
            self.metrics["error_count"] += params.get("increase", 3)
        elif fault_type == "stuck_output":
            self.metrics["error_count"] += params.get("increase", 5)
            self.status = "degraded"
        elif fault_type == "overheat":
            self.metrics["temp_c"] = self.metrics.get("temp_c", 40.0) + params.get("delta", 15.0)
            self.status = "degraded"
        elif fault_type == "crc_mismatch":
            self.metrics["last_output_crc"] = hex(random.getrandbits(16))
            self.metrics["error_count"] += params.get("increase", 1)
            self.status = "degraded"
        elif fault_type == "telemetry_noise":
            self.metrics["temp_c"] += random.uniform(-5.0, 5.0)
            self.metrics["error_count"] += 0.5
            self.status = "degraded"
        else:
            self.metrics["error_count"] += 1
            self.status = "degraded"

    def clear_fault(self):
        """Clear forced fault and allow recovery."""
        self._forced_fault = None
        self._fault_until = None
        # gentle recovery
        if self.status != "spare":
            self.status = "ok"
        ec = self.metrics.get("error_count", 0.0)
        self.metrics["error_count"] = max(0.0, ec - 1.0)

    def has_heartbeat(self) -> bool:
        """Return whether tile is currently producing heartbeats."""
        # If missing_heartbeat fault is set, treat as no heartbeat
        if self._forced_fault and self._forced_fault.get("fault_type") == "missing_heartbeat":
            # if fault has expired, clear it
            if self._fault_until and time.time() > self._fault_until:
                self.clear_fault()
                return True
            return False
        return True

    def tick(self):
        """Periodic physical model: thermal drift, error decay, fault expiry."""
        # fault expiry
        if self._fault_until and time.time() > self._fault_until:
            self.clear_fault()

        # thermal model - small drift based on load
        base = 40.0
        load = float(self.metrics.get("load", 0.0))
        temp = float(self.metrics.get("temp_c", base))
        # heat from load
        temp += (load * 0.5) * 0.02
        # simple cooling toward base
        temp += (base - temp) * 0.01
        self.metrics["temp_c"] = round(temp, 2)

        # slowly decay error_count if no forced fault
        if not self._forced_fault:
            ec = self.metrics.get("error_count", 0.0)
            if ec > 0:
                self.metrics["error_count"] = max(0.0, ec - 0.05)
