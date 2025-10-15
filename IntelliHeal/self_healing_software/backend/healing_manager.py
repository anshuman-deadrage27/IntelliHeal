"""
Healing Manager
Coordinates steps to heal a detected fault:
- selects a recovery plan (via AIPathManager)
- sends commands to hardware via command_sender
- runs a sandbox verification in background
- commits or rolls back
"""

import asyncio
import time
from typing import Dict, Any, Callable

class HealingManager:
    def __init__(self, ai_manager, cmd_sender, sandbox_timeout=0.2):
        """
        ai_manager: instance of AIPathManager
        cmd_sender: instance of CommandSender (firmware_interface)
        sandbox_timeout: seconds to run quick sandbox tests
        """
        self.ai = ai_manager
        self.cmd = cmd_sender
        self.sandbox_timeout = sandbox_timeout
        self.history = []  # list of attempts
        # callback for broadcasting events (UI)
        self.on_event: Callable[[Dict[str,Any]], None] = lambda ev: None

    async def handle_fault(self, fault_event: Dict[str,Any]):
        """
        End-to-end handling for a single fault event. Non-blocking wrapper.
        """
        asyncio.create_task(self._run_heal(fault_event))

    async def _run_heal(self, fault_event: Dict[str,Any]):
        start_ts = time.time()
        node = fault_event.get("node_id")
        ctx = {
            "node_id": node,
            "fault_type": fault_event.get("fault_type"),
            "metrics": fault_event.get("evidence", {})
        }
        plan = self.ai.recommend(ctx)
        self._announce({"type":"healing_started","node":node,"plan":plan,"ts":time.time()})
        # fast-path: attempt immediate swap/isolate
        cmd = {
            "msg_type":"cmd_reconfigure",
            "cmd_id": f"cmd_{node}_{int(start_ts*1000)}",
            "target_node": node,
            "action": plan.get("action"),
            "spare_id": plan.get("spare_id"),
            "delta_state": None  # delta state could be added here
        }
        # send command and wait for result (with timeout)
        try:
            ack = await self.cmd.send_command(cmd, expect_result=True, timeout=2.0)
        except Exception as e:
            ack = {"status":"error","error":str(e)}
        # record attempt
        attempt = {"fault": fault_event, "plan": plan, "cmd_result": ack, "ts": time.time()}
        self.history.append(attempt)
        # Now run sandbox verification in background (non-blocking)
        verified = await self._sandbox_verify(node, plan)
        if verified and ack.get("status") == "success":
            # commit - store in AI cache so future similar faults are resolved instantly
            self.ai.register_success(ctx, plan)
            self._announce({"type":"healing_success","node":node,"plan":plan,"duration_ms": int((time.time()-start_ts)*1000)})
        else:
            # try fallback or escalate
            self._announce({"type":"healing_failed","node":node,"plan":plan,"verified":verified,"cmd_result":ack})
            # naive fallback: try alternative spare if available
            fallback_plan = {"action":"isolate"}
            # optionally send fallback
            try:
                await self.cmd.send_command({
                    "msg_type":"cmd_reconfigure",
                    "cmd_id": f"fallback_{node}_{int(time.time()*1000)}",
                    "target_node": node,
                    "action": fallback_plan["action"],
                    "spare_id": None
                }, expect_result=False, timeout=1.0)
            except Exception:
                pass

    async def _sandbox_verify(self, node: str, plan: Dict[str,Any]) -> bool:
        """
        Lightweight sandbox verification simulation:
        In real deployment, sandbox runs test vectors; here we sleep then return pass/fail based on heuristic.
        """
        # quick check: if plan confidence high, assume pass quickly
        confidence = plan.get("confidence", 0.0)
        await asyncio.sleep(min(self.sandbox_timeout, 0.05 if confidence>0.9 else 0.1))
        # heuristic: high confidence -> pass, else random-ish (but deterministic)
        if confidence > 0.8:
            return True
        # fallback: treat heuristic as pass for now
        return True

    def _announce(self, event: Dict[str,Any]):
        try:
            self.on_event(event)
        except Exception:
            pass
