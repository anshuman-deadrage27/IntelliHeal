"""
Utility helpers
"""

import time
import json

def now_ts():
    return time.time()

def pretty_ts(ts=None):
    if ts is None:
        ts = now_ts()
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

def dump_json(obj):
    return json.dumps(obj, indent=2, default=str)
