"""
HAL-like TCP server for the simulator. Communicates newline-delimited JSON.
"""

import asyncio
import json
import time
import traceback
from typing import Dict, List

from .fault_injector import inject_from_message

class HALServer:
    def __init__(self, board, pr_controller, host: str = "127.0.0.1", port: int = 9000, hb_interval: float = 0.1):
        self.board = board
        self.pr = pr_controller
        self.host = host
        self.port = port
        self.server = None
        self.clients: List = []
        self.hb_interval = hb_interval
        self._hb_task = None

    async def start(self):
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self._hb_task = asyncio.create_task(self._hb_loop())
        print(f"HALServer listening on {self.host}:{self.port}")

    async def stop(self):
        if self._hb_task:
            self._hb_task.cancel()
            await asyncio.gather(self._hb_task, return_exceptions=True)
            self._hb_task = None
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        # close client writers
        for reader, writer in list(self.clients):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self.clients.clear()

    async def _hb_loop(self):
        try:
            while True:
                # tick physics first
                self.board.tick_all()
                snapshot = self.board.get_snapshot()
                text = json.dumps(snapshot) + "\n"
                # broadcast
                for _, writer in list(self.clients):
                    try:
                        writer.write(text.encode())
                        await writer.drain()
                    except Exception:
                        # ignore broken client - cleanup on next read
                        pass
                await asyncio.sleep(self.hb_interval)
        except asyncio.CancelledError:
            return
        except Exception as e:
            print("HB loop error:", e)
            traceback.print_exc()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        print(f"Client connected: {addr}")
        self.clients.append((reader, writer))
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    text = line.decode().strip()
                    if not text:
                        continue
                    msg = json.loads(text)
                except Exception:
                    # ignore malformed
                    continue

                mtype = msg.get("msg_type", "")
                if mtype == "fault_event":
                    # inject into board
                    inject_from_message(self.board, msg)
                elif mtype == "status_request":
                    # immediate reply
                    snapshot = self.board.get_snapshot()
                    writer.write((json.dumps(snapshot) + "\n").encode())
                    await writer.drain()
                elif mtype == "cmd_reconfigure":
                    # immediate ack
                    ack = {"msg_type": "cmd_ack", "cmd_id": msg.get("cmd_id"), "status": "accepted"}
                    writer.write((json.dumps(ack) + "\n").encode())
                    await writer.drain()
                    # schedule PR execution and later send cmd_result
                    asyncio.create_task(self._exec_reconfig(msg, writer))
                else:
                    # ignore unknown types
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print("client read error", e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            try:
                self.clients.remove((reader, writer))
            except Exception:
                pass
            print(f"Client disconnected: {addr}")

    async def _exec_reconfig(self, msg: Dict, writer: asyncio.StreamWriter):
        try:
            res = await self.pr.handle_reconfigure(msg)
            # send result
            writer.write((json.dumps(res) + "\n").encode())
            await writer.drain()
        except Exception as e:
            try:
                writer.write((json.dumps({"msg_type": "cmd_result", "cmd_id": msg.get("cmd_id"), "status": "failed", "duration_ms": 0}) + "\n").encode())
                await writer.drain()
            except Exception:
                pass
