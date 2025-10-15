"""
AI Path Manager (lightweight)
- Maintains a cache of successful recovery paths
- Provides a recommend() method that returns a recovery plan for a given fault_context dict
- Optionally loads a tiny ML model (if present) to propose paths for unknown cases
"""

import os
import json
import hashlib
from typing import Dict, Any, Optional

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "ai_model", "model.json")

class AIPathManager:
    def __init__(self):
        # simple in-memory cache: fingerprint -> plan
        self.cache: Dict[str, Dict[str, Any]] = {}
        # load any prebuilt model if present (lightweight JSON)
        self.model = None
        if os.path.exists(MODEL_PATH):
            try:
                with open(MODEL_PATH, "r") as f:
                    self.model = json.load(f)
                print("AIPathManager: loaded lightweight model.")
            except Exception as e:
                print("AIPathManager: failed to load model:", e)

        # example spare inventory (in real deployment this maps to actual hardware region ids)
        self.spare_pool = ["spare_1", "spare_2", "spare_3"]

    def _fingerprint(self, ctx: Dict[str, Any]) -> str:
        # create deterministic short fingerprint for caching (use node, fault_type, coarse load/temp)
        key = (ctx.get("node_id",""), ctx.get("fault_type",""), str(int(ctx.get("metrics",{}).get("load",0)*10)), str(int(ctx.get("metrics",{}).get("temp_c",0))))
        h = hashlib.sha1(repr(key).encode()).hexdigest()
        return h

    def register_success(self, ctx: Dict[str, Any], plan: Dict[str,Any]):
        """
        Store successful plan in cache for future instant reuse.
        """
        fp = self._fingerprint(ctx)
        self.cache[fp] = plan

    def recommend(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a recommended recovery plan dict:
        { "action": "fast_swap"|"partial_reconfig"|"isolate", "spare_id": "...", "playbook": "...", "confidence": 0.8 }
        """
        fp = self._fingerprint(ctx)
        if fp in self.cache:
            plan = self.cache[fp].copy()
            plan["confidence"] = 0.99
            plan["source"] = "cache"
            return plan

        # if model exists, try to use it (very lightweight JSON-rule based)
        if self.model:
            try:
                # if model is a dict mapping fault_type -> spare_id for simple setups
                fault_type = ctx.get("fault_type", "")
                mapping = self.model.get("mapping", {})
                spare = mapping.get(fault_type)
                if spare:
                    return {"action":"fast_swap","spare_id":spare,"playbook":f"playbook_for_{spare}","confidence":0.85,"source":"model"}
            except Exception:
                pass

        # fallback heuristic: choose first spare that is not the failed node (simple)
        for s in self.spare_pool:
            if s != ctx.get("node_id"):
                return {"action":"fast_swap","spare_id":s,"playbook":f"playbook_for_{s}","confidence":0.5,"source":"heuristic"}

        # final fallback: isolate
        return {"action":"isolate","spare_id":None,"playbook":None,"confidence":0.1,"source":"fallback"}
