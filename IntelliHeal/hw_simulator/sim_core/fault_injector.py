"""
Utilities to inject faults into the board from incoming fault_event messages.
"""

from typing import Dict
import logging

def inject_from_message(board, msg: Dict):
    node = msg.get("node_id")
    ftype = msg.get("fault_type", "manual_inject")
    severity = msg.get("severity", "major")
    if severity == "critical":
        dur = None
    elif severity == "major":
        dur = 60.0
    else:
        dur = 10.0
    params = msg.get("evidence", {}) or {}
    try:
        return board.inject_fault(node, ftype, duration_s=dur, params=params)
    except Exception as e:
        logging.exception("inject_from_message")
        return {"status": "error", "reason": str(e)}
