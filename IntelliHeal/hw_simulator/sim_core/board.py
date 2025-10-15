"""
Board model - collection of tiles, spare pool, mapping and utility functions.
"""

import time
import json
import os
import random
from typing import Dict, List, Optional

from .tile import Tile


class Board:
    def __init__(self, tiles_count: int = 16, spare_count: int = 3, config_path: Optional[str] = None):
        self.tiles: Dict[str, Tile] = {}
        self.spares: List[str] = []
        self.config_path = config_path
        self.region_map: Dict = {}
        self._init_tiles(tiles_count)
        self._init_spares(spare_count)
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    self.region_map = json.load(f)
            except Exception:
                self.region_map = {}

    def _init_tiles(self, n: int):
        for i in range(n):
            tid = f"tile_{i}"
            t = Tile(tile_id=tid)
            self.tiles[tid] = t

    def _init_spares(self, count: int):
        all_ids = sorted(self.tiles.keys())
        if count <= 0:
            return
        spares = all_ids[-count:]
        for s in spares:
            self.spares.append(s)
            self.tiles[s].is_spare = True
            self.tiles[s].pr_loaded = f"spare_{s}"

    def get_snapshot(self):
        """Return aggregated snapshot used for heartbeats/status."""
        return {
            "msg_type": "status_snapshot",
            "timestamp": time.time(),
            "nodes": {tid: self.tiles[tid].snapshot() for tid in sorted(self.tiles.keys())}
        }

    def tick_all(self):
        for t in self.tiles.values():
            t.tick()

    def inject_fault(self, tile_id: str, fault_type: str, duration_s: Optional[float] = None, params: Optional[dict] = None):
        if tile_id not in self.tiles:
            raise KeyError(tile_id)
        self.tiles[tile_id].apply_fault(fault_type, duration_s=duration_s, params=params or {})
        return {"status": "injected", "tile": tile_id, "fault_type": fault_type}

    def clear_fault(self, tile_id: str):
        if tile_id not in self.tiles:
            raise KeyError(tile_id)
        self.tiles[tile_id].clear_fault()
        return {"status": "cleared", "tile": tile_id}

    def perform_fast_swap(self, target_tile: str, spare_tile: str) -> Dict:
        """
        Simulate swapping target logic to spare tile. This is synchronous state change.
        """
        if spare_tile not in self.spares:
            return {"status": "error", "reason": "not_a_spare"}

        if target_tile not in self.tiles:
            return {"status": "error", "reason": "no_target"}

        # copy logical module association
        src = self.tiles[target_tile]
        dst = self.tiles[spare_tile]

        dst.pr_loaded = src.pr_loaded or f"module_{target_tile}"
        dst.status = "ok"
        dst.metrics = dict(src.metrics)  # copy metrics as snapshot (approx)
        # isolate target
        src.status = "isolated"
        src.metrics["load"] = 0.0
        return {"status": "swapped", "target": target_tile, "spare": spare_tile}

    def find_available_spare(self) -> Optional[str]:
        for s in self.spares:
            if self.tiles[s].status == "ok":
                return s
        return None