"""
Main entrypoint: runs FastAPI server, initialises HAL, telemetry collector, detector, AI manager, healing manager.
This version ensures background tasks are registered and cancelled cleanly on shutdown
so CTRL+C causes a graceful shutdown.
"""

import asyncio
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import os, json, time

# backend modules
from backend.telemetry_collector import TelemetryCollector
from backend.fault_detector import FaultDetector
from backend.ai_path_manager import AIPathManager
from backend.healing_manager import HealingManager
from firmware_interface.hal_adapter import HALAdapter
from firmware_interface.command_sender import CommandSender

app = FastAPI()

# mount UI static folder
ui_path = os.path.join(os.path.dirname(__file__), "ui")
app.mount("/ui", StaticFiles(directory=ui_path), name="ui")

# global state containers
state = {
    "nodes": {},        # node_id -> last metrics
    "faults": [],       # recorded fault events
    "healing_history": []
}

# simple websocket manager
class WSManager:
    def __init__(self):
        self._conns = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._conns.append(ws)

    def disconnect(self, ws: WebSocket):
        try:
            self._conns.remove(ws)
        except ValueError:
            pass

    async def broadcast(self, msg: dict):
        text = json.dumps(msg)
        dead = []
        for ws in list(self._conns):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for d in dead:
            self.disconnect(d)

ws_mgr = WSManager()

# create HAL and components (config via env vars or defaults)
HAL_MODE = os.environ.get("HAL_MODE", "tcp")
HAL_HOST = os.environ.get("HAL_HOST", "127.0.0.1")
HAL_PORT = int(os.environ.get("HAL_PORT", "9000"))
hal = HALAdapter(mode=HAL_MODE, tcp_host=HAL_HOST, tcp_port=HAL_PORT)
cmd_sender = CommandSender(hal)
ai_manager = AIPathManager()
healing_mgr = HealingManager(ai_manager, cmd_sender)

# connect healing manager event announcer to ws broadcast and local state
def announce_event(ev):
    t = time.time()
    try:
        if ev.get("type") in ("healing_success","healing_failed"):
            state["healing_history"].append(ev)
    finally:
        # schedule broadcast asynchronously
        asyncio.create_task(ws_mgr.broadcast(ev))

healing_mgr.on_event = announce_event

telemetry_q = asyncio.Queue()
telemetry_collector = TelemetryCollector(hal, telemetry_q)

# fault detector will call on_fault when fault detected
def on_fault(fault_event):
    # log into state and send to ws and handoff to healing manager
    state["faults"].append(fault_event)
    # broadcast fault event (fire-and-forget)
    asyncio.create_task(ws_mgr.broadcast({"type":"fault_event", **fault_event}))
    # ask healing manager to handle it
    asyncio.create_task(healing_mgr.handle_fault(fault_event))

fault_detector = FaultDetector(telemetry_q, on_fault_callback=on_fault,
                               heartbeat_timeout_ms=200, error_threshold=3)

# feed incoming HAL messages to CommandSender so it can fulfill pending commands
async def hal_incoming_dispatcher():
    """
    Continuously read messages from HAL and dispatch:
      - update state (heartbeats)
      - feed messages to command_sender (for awaiting cmd_result)
      - put them on telemetry queue for detector
    This loop is cancellable: it catches CancelledError and exits.
    """
    try:
        while True:
            msg = await hal.read_json(timeout=0.5)
            if msg:
                # update state if heartbeat
                if msg.get("msg_type") == "heartbeat" and msg.get("node_id"):
                    node = msg["node_id"]
                    state["nodes"][node] = msg.get("metrics", {})
                # allow command_sender to fulfill pending futures
                cmd_sender.feed_incoming(msg)
                # push message into telemetry queue for detector as well
                try:
                    await telemetry_q.put(msg)
                except asyncio.CancelledError:
                    break
            else:
                await asyncio.sleep(0.01)
    except asyncio.CancelledError:
        # expected on shutdown: exit the loop
        return
    except Exception as e:
        # log unexpected exception and exit
        print("hal_incoming_dispatcher unexpected error:", e)
        return

# -- Startup and shutdown handlers that properly manage background tasks --

@app.on_event("startup")
async def startup_event():
    """
    Start HAL, telemetry collector, detector, and the hal_incoming_dispatcher background task.
    Store created tasks on app.state['bg_tasks'] so shutdown can cancel them.
    """
    # ensure task list exists
    app.state.bg_tasks = []

    # start HAL adapter
    await hal.start()

    # start hal_incoming_dispatcher as a background task and store it
    hal_task = asyncio.create_task(hal_incoming_dispatcher())
    app.state.bg_tasks.append(hal_task)

    # start telemetry collector and fault detector
    await telemetry_collector.start()
    await fault_detector.start()

    print("Self-healing host started. Background tasks running.")

@app.on_event("shutdown")
async def shutdown_event():
    """
    Cancel background tasks, stop components, and close HAL.
    This ensures the process can exit cleanly on CTRL+C.
    """
    print("Shutdown: cancelling background tasks...")
    tasks = getattr(app.state, "bg_tasks", [])
    # cancel tasks
    for t in tasks:
        t.cancel()
    # wait for tasks to finish
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # stop telemetry collector and detector (they'll exit their loops)
    try:
        await telemetry_collector.stop()
    except Exception as e:
        print("Error stopping telemetry_collector:", e)
    try:
        await fault_detector.stop()
    except Exception as e:
        print("Error stopping fault_detector:", e)

    # finally stop HAL adapter (closes connections)
    try:
        await hal.stop()
    except Exception as e:
        print("Error stopping HAL adapter:", e)

    print("Shutdown complete.")

# API endpoints and websocket similar to previous version

@app.get("/")
async def ui_root():
    return FileResponse(os.path.join(ui_path, "index.html"))

@app.get("/api/status")
async def api_status():
    return {"nodes": state["nodes"], "faults": state["faults"], "healing_history": state["healing_history"]}

@app.post("/api/inject_fault")
async def api_inject_fault(req: Request):
    """
    For demo/testing: inject a fault event into the system.
    Body: {"node_id":"tile_5","fault_type":"manual_inject"}
    """
    body = await req.json()
    node = body.get("node_id","tile_0")
    ft = body.get("fault_type","manual_inject")
    evt = {
        "msg_type":"fault_event",
        "fault_id": f"manual_{node}_{int(time.time()*1000)}",
        "node_id": node,
        "fault_type": ft,
        "severity": "major",
        "timestamp": time.time(),
        "evidence": {"source":"api_inject"}
    }
    # If HAL supports sending JSON back (simulator), do that so hal_incoming_dispatcher will pick it up too.
    await hal.send_json(evt)
    return {"status":"injected", "event": evt}

# websocket endpoint for UI
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_mgr.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            # echo or ignore
            await ws.send_text(json.dumps({"echo":data}))
    except WebSocketDisconnect:
        ws_mgr.disconnect(ws)

if __name__ == "__main__":
    # run uvicorn programmatically so CTRL+C handling by uvicorn will trigger FastAPI shutdown events
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)