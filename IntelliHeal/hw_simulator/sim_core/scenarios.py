"""
Pre-built scenario helpers. Each returns configuration data or applies
initial faults / loads to the board for demo purposes.
"""

import random

def light_load_scenario(board):
    # set small loads across tiles
    for i, t in enumerate(board.tiles.values()):
        t.metrics["load"] = 0.05 if not t.is_spare else 0.0

def stress_scenario(board):
    for i, t in enumerate(board.tiles.values()):
        t.metrics["load"] = random.uniform(0.2, 0.9) if not t.is_spare else 0.0

def one_fault_scenario(board, tile_id="tile_3"):
    board.inject_fault(tile_id, "missing_heartbeat", duration_s=30.0)
