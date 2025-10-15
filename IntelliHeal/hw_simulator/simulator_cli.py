"""
CLI to start the hardware simulator.

Run from project root:
python -m hw_simulator.tools.simulator_cli --host 127.0.0.1 --port 9000 --tiles 16 --spares 3
"""

import asyncio
import argparse
import os
import sys

# absolute imports work because module is run as package
from sim_core.board import Board
from sim_core.pr_controller import PRController
from sim_core.comms import HALServer
from sim_core.sim_env import SimEnv
from sim_core import scenarios

async def run_sim(host: str, port: int, tiles: int, spares: int, hb_interval: float, tick_interval: float):
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "board_map.json")
    board = Board(tiles_count=tiles, spare_count=spares, config_path=cfg_path)
    pr = PRController(board, warm_swap_ms=5.0, cold_pr_ms_per_kb=2.0, failure_rate=0.02)
    hal = HALServer(board, pr, host=host, port=port, hb_interval=hb_interval)
    env = SimEnv(board, tick_interval=tick_interval)

    await hal.start()
    await env.start()

    # apply light default scenario
    scenarios.light_load_scenario(board)
    print("Simulator ready. Press Ctrl+C to stop.")

    try:
        while True:
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass
    finally:
        print("Shutting down simulator...")
        await env.stop()
        await hal.stop()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=9000, type=int)
    parser.add_argument("--tiles", default=16, type=int)
    parser.add_argument("--spares", default=3, type=int)
    parser.add_argument("--hb", default=0.1, type=float)
    parser.add_argument("--tick", default=0.05, type=float)
    args = parser.parse_args()

    try:
        asyncio.run(run_sim(args.host, args.port, args.tiles, args.spares, args.hb, args.tick))
    except KeyboardInterrupt:
        print("Simulator stopped.")
    except Exception as e:
        print("Simulator error:", e)
        raise

if __name__ == "__main__":
    main()
