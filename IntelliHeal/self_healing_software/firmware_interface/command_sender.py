"""
Command Sender
Sends high-level reconfiguration commands to hardware via HALAdapter and awaits result messages
"""

import asyncio
import time
from typing import Dict, Any

class CommandSender:
    def __init__(self, hal):
        self.hal = hal
        self._pending = {}  # cmd_id -> Future

    async def send_command(self, cmd: Dict[str,Any], expect_result: bool = True, timeout: float = 2.0) -> Dict[str,Any]:
        """
        Send a command and optionally wait for cmd_result message with matching cmd_id.
        Returns ack/result dict or raises on timeout.
        """
        cmd_id = cmd.get("cmd_id") or f"cmd_{int(time.time()*1000)}"
        cmd["cmd_id"] = cmd_id
        # send
        ok = await self.hal.send_json(cmd)
        if not ok:
            raise RuntimeError("HAL send failed")
        # if not expecting result, return ack
        if not expect_result:
            return {"status":"sent"}
        # wait for result - here we implement a simple pattern: expect hardware to reply with cmd_result
        fut = asyncio.get_event_loop().create_future()
        self._pending[cmd_id] = fut
        try:
            res = await asyncio.wait_for(fut, timeout=timeout)
            return res
        finally:
            self._pending.pop(cmd_id, None)

    def feed_incoming(self, msg: Dict[str,Any]):
        """
        Call this for incoming messages from HALAdapter - it will fulfill pending futures when cmd_result arrives.
        """
        if not isinstance(msg, dict):
            return
        mtype = msg.get("msg_type","")
        if mtype in ("cmd_result","cmd_ack"):
            cid = msg.get("cmd_id")
            fut = self._pending.get(cid)
            if fut and not fut.done():
                fut.set_result(msg)
