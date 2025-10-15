/* app.js - IntelliHeal UI (revised to talk to self_healing_software backend)
   - WebSocket queue + reconnection
   - Sends fault_event, handles cmd_ack & cmd_result
   - Requests status_snapshot and updates SVG & charts
   - Process visualization on ack/result
*/

const WS_URL = `ws://${location.host}/ws`; // same host, path /ws (adjust if backend uses different host/port)
const SVG_OBJECT_ID = "board-object";
const INLINE_SVG_ID = "board-svg";
const TELEMETRY_HISTORY = 60;
const RECONNECT_MS = 2000;

let ws = null;
let wsReady = false;
let wsQueue = [];

const DOM = {};
let componentIds = [];
const chartStore = {}; // { nodeId: { history:{hb:[]}, charts: {hb: Chart} } }

// ------------ WebSocket (queue + reconnect) ------------
function initWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  ws = new WebSocket(WS_URL);

  ws.addEventListener("open", () => {
    console.info("[WS] connected");
    wsReady = true;
    if (DOM.connStatus) DOM.connStatus.textContent = "connected";
    // flush queued messages
    while (wsQueue.length) {
      const m = wsQueue.shift();
      try { ws.send(JSON.stringify(m)); } catch (e) { console.warn("[WS] flush send failed", e); wsQueue.unshift(m); break; }
    }
    // request initial status snapshot
    safeSend({ msg_type: "status_request" });
  });

  ws.addEventListener("message", (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      handleWSMessage(msg);
    } catch (e) {
      console.error("[WS] invalid JSON", e, ev.data);
    }
  });

  ws.addEventListener("close", () => {
    console.warn("[WS] closed, reconnecting in", RECONNECT_MS, "ms");
    wsReady = false;
    if (DOM.connStatus) DOM.connStatus.textContent = "disconnected";
    setTimeout(initWebSocket, RECONNECT_MS);
  });

  ws.addEventListener("error", (err) => {
    console.error("[WS] error", err);
    try { ws.close(); } catch (e) {}
  });
}

function safeSend(obj) {
  if (!obj || typeof obj !== "object") return;
  if (wsReady && ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify(obj));
    } catch (e) {
      console.warn("[WS] send failed, queuing", e);
      wsQueue.push(obj);
    }
  } else {
    wsQueue.push(obj);
  }
}

// ------------ Logging & helpers ------------
function log(msg) {
  if (!DOM.logPanel) return;
  const el = document.createElement("div");
  el.className = "log-entry";
  el.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  DOM.logPanel.prepend(el);
  // trim
  while (DOM.logPanel.childElementCount > 800) DOM.logPanel.removeChild(DOM.logPanel.lastChild);
  console.log(msg);
}

// ------------ SVG loading & interactions ------------
let svgLoadAttempts = 0;
async function loadBoardSVG() {
  // inline SVG
  const inline = document.getElementById(INLINE_SVG_ID);
  if (inline && inline instanceof SVGElement) {
    DOM.svgRoot = inline;
    bindSVGInteractions();
    return;
  }
  // object embed
  const obj = document.getElementById(SVG_OBJECT_ID);
  if (obj && obj.tagName === "OBJECT") {
    return new Promise((resolve) => {
      function tryAccess() {
        const doc = obj.contentDocument;
        if (doc) {
          const svg = doc.querySelector("svg");
          if (svg) { DOM.svgRoot = svg; bindSVGInteractions(); resolve(); return; }
        }
        svgLoadAttempts++;
        if (svgLoadAttempts < 12) setTimeout(tryAccess, 250);
        else { console.warn("[SVG] object load timeout"); resolve(); }
      }
      tryAccess();
    });
  }
  // fallback search
  const wrapper = document.getElementById("board-wrapper");
  if (wrapper) {
    const found = wrapper.querySelector("svg");
    if (found) { DOM.svgRoot = found; bindSVGInteractions(); return; }
  }
  console.warn("[SVG] no svg found. Check INLINE_SVG_ID or SVG_OBJECT_ID or board-wrapper contents.");
}

function bindSVGInteractions() {
  if (!DOM.svgRoot) { log("SVG root not found"); return; }
  // gather ids
  componentIds = [];
  const all = DOM.svgRoot.querySelectorAll("[id]");
  all.forEach(el => {
    const id = String(el.id).trim();
    if (!id) return;
    if (/^(defs|linearGradient|radialGradient|clipPath|mask|title|desc|metadata)$/i.test(id)) return;
    if (id.length > 1) {
      componentIds.push(id);
      try { el.style.cursor = "pointer"; } catch {}
      el.addEventListener("click", (ev) => { ev.stopPropagation(); onComponentClicked(id); });
    }
  });
  componentIds = Array.from(new Set(componentIds)).sort();
  populateComponentDropdown();
  log(`[SVG] loaded, discovered ${componentIds.length} components`);
}

function setSVGElementStatus(id, status) {
  if (!DOM.svgRoot) return;
  const el = DOM.svgRoot.getElementById(id);
  if (!el) return;
  el.classList.remove("status-ok","status-degraded","status-failed","status-spare","highlight");
  if (status === "ok") el.classList.add("status-ok");
  else if (status === "degraded") el.classList.add("status-degraded");
  else if (status === "failed") el.classList.add("status-failed");
  else if (status === "spare") el.classList.add("status-spare");
  else if (status === "highlight") el.classList.add("highlight");
}

function onComponentClicked(id) {
  if (!DOM.compSelect) return;
  DOM.compSelect.value = id;
  highlightComponent(id);
  safeSend({ msg_type: "select_component", node_id: id });
  log(`Selected ${id}`);
}

function highlightComponent(id) {
  componentIds.forEach(cid => setSVGElementStatus(cid, null));
  setSVGElementStatus(id, "highlight");
}

// ------------ Dropdown ------------
function populateComponentDropdown() {
  if (!DOM.compSelect) return;
  const prev = DOM.compSelect.value;
  DOM.compSelect.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "-- Select component --";
  DOM.compSelect.appendChild(placeholder);

  componentIds.forEach(id => {
    const o = document.createElement("option");
    o.value = id;
    o.textContent = id;
    DOM.compSelect.appendChild(o);
  });

  if (prev) {
    const found = Array.from(DOM.compSelect.options).find(o => o.value === prev);
    if (found) DOM.compSelect.value = prev;
  }

  DOM.compSelect.addEventListener("change", (e) => {
    const val = e.target.value;
    if (val) {
      highlightComponent(val);
      safeSend({ msg_type: "select_component", node_id: val });
      log(`Dropdown select ${val}`);
    }
  });
}

// ------------ Charts ------------
function initCharts() {
  if (!DOM.chartCanvases || DOM.chartCanvases.length === 0) return;
  DOM.chartCanvases.forEach(cv => {
    const nodeId = cv.dataset.chartFor || cv.dataset.component;
    if (!nodeId) return;
    if (!chartStore[nodeId]) chartStore[nodeId] = { history: { hb: [] }, charts: {} };
    const ctx = cv.getContext("2d");
    const color = randomHue();
    const chart = new Chart(ctx, {
      type: "line",
      data: {
        labels: Array(TELEMETRY_HISTORY).fill(""),
        datasets: [{ label: nodeId, data: Array(TELEMETRY_HISTORY).fill(null), borderColor: color, backgroundColor: color.replace("1)", "0.12)"), tension: 0.25, spanGaps: true }]
      },
      options: { animation: false, plugins: { legend: { display: false } }, scales: { y: { suggestedMin: 0, suggestedMax: 100 } } }
    });
    chartStore[nodeId].charts.hb = chart;
  });
}

function randomHue() {
  const h = Math.floor(Math.random() * 360);
  return `hsl(${h} 70% 45% / 1)`;
}

function appendTelemetry(nodeId, sample = {}) {
  if (!chartStore[nodeId]) chartStore[nodeId] = { history: { hb: [] }, charts: {} };
  const store = chartStore[nodeId];
  if (sample.hb !== undefined && sample.hb !== null) store.history.hb.push(Number(sample.hb));
  else store.history.hb.push(null);
  if (store.history.hb.length > TELEMETRY_HISTORY) store.history.hb.shift();
  if (store.charts.hb) {
    const ds = store.charts.hb.data.datasets[0].data;
    ds.push(sample.hb !== undefined && sample.hb !== null ? Number(sample.hb) : null);
    if (ds.length > TELEMETRY_HISTORY) ds.shift();
    store.charts.hb.update("none");
  }
}

// ------------ Process visualizer ------------
function startProcessVisual(cmdId, estMs = 800) {
  if (!DOM.procStatus || !DOM.procProgress) return;
  DOM.procStatus.textContent = `Process ${cmdId} running...`;
  DOM.procProgress.style.width = "0%";
  const start = Date.now();
  function tick() {
    const elapsed = Date.now() - start;
    const pct = Math.min(100, Math.round((elapsed / estMs) * 100));
    DOM.procProgress.style.width = `${pct}%`;
    if (pct < 100) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

function finishProcessVisual(cmdId, status = "ok") {
  if (!DOM.procStatus || !DOM.procProgress) return;
  DOM.procProgress.style.width = "100%";
  DOM.procStatus.textContent = `Process ${cmdId} ${status}`;
  setTimeout(() => {
    DOM.procProgress.style.width = "0%";
    DOM.procStatus.textContent = "No active process";
  }, 700);
}

// ------------ Controls binding ------------
function bindControls() {
  if (DOM.injectBtn) {
    DOM.injectBtn.addEventListener("click", () => {
      const nodeId = DOM.compSelect ? DOM.compSelect.value : null;
      if (!nodeId) { alert("Please select a component to inject a fault."); return; }
      const faultType = document.getElementById("fault-select")?.value || "missing_heartbeat";
      const severity = document.getElementById("severity-select")?.value || "major";
      safeSend({ msg_type: "fault_event", node_id: nodeId, fault_type: faultType, severity });
      log(`Fault injected: ${nodeId} (${faultType}, severity=${severity})`);
    });
  }

  if (DOM.scenarioBtns && DOM.scenarioBtns.length) {
    DOM.scenarioBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        const sc = btn.dataset.scenario;
        safeSend({ msg_type: "run_scenario", scenario: sc });
        log(`Scenario started: ${sc}`);
      });
    });
  }

  if (DOM.slowSpeed && DOM.speedVal) {
    DOM.slowSpeed.addEventListener("input", () => {
      DOM.speedVal.textContent = `${DOM.slowSpeed.value}ms`;
    });
  }
}

// ------------ WS message handling (core) ------------
function handleWSMessage(msg) {
  const t = msg.msg_type || msg.type || msg.type_name;
  switch (t) {
    case "status_snapshot":
    case "board_snapshot": {
      const nodes = msg.nodes || {};
      Object.keys(nodes).forEach(id => {
        const n = nodes[id] || {};
        const status = n.status || "ok";
        setSVGElementStatus(id, status);
        const metrics = n.metrics || {};
        const hb = metrics.heartbeat ?? metrics.hb ?? metrics.health ?? metrics.heartbeat_val;
        const temp = metrics.temp_c ?? metrics.temp;
        appendTelemetry(id, { hb, temp });
      });
      break;
    }

    case "node_update": {
      const id = msg.node_id || msg.node;
      if (!id) break;
      if (msg.status) setSVGElementStatus(id, msg.status);
      if (msg.metrics) appendTelemetry(id, { hb: msg.metrics.heartbeat, temp: msg.metrics.temp_c });
      break;
    }

    case "cmd_ack": {
      const cid = msg.cmd_id || `cmd_${Date.now()}`;
      startProcessVisual(cid, msg.estimated_ms || 900);
      log(`cmd_ack ${cid}`);
      break;
    }

    case "cmd_result": {
      const cid = msg.cmd_id || `cmd_${Date.now()}`;
      finishProcessVisual(cid, msg.status || "done");
      log(`cmd_result ${cid} -> ${msg.status || "done"}`);
      // refresh snapshot so UI shows post-heal state
      setTimeout(() => safeSend({ msg_type: "status_request" }), 300);
      break;
    }

    case "fault_report":
    case "fault": {
      const node = msg.node_id || msg.node || msg.component;
      if (node) {
        setSVGElementStatus(node, "failed");
        log(`Fault reported ${node}: ${msg.detail || msg.fault_type || ""}`);
      }
      break;
    }

    case "log":
    case "info": {
      log(msg.text || msg.message || JSON.stringify(msg));
      break;
    }

    default:
      // ignore silently
      break;
  }
}

// ------------ Initialization ------------
function queryDOM() {
  DOM.boardWrapper = document.getElementById("board-wrapper") || document.body;
  DOM.compSelect = document.getElementById("component-select");
  DOM.injectBtn = document.getElementById("inject-fault-btn");
  DOM.scenarioBtns = document.querySelectorAll(".scenario-btn");
  DOM.logPanel = document.getElementById("log-panel");
  DOM.slowCheckbox = document.getElementById("slow-checkbox");
  DOM.slowSpeed = document.getElementById("slow-speed");
  DOM.speedVal = document.getElementById("speed-val");
  DOM.procStatus = document.getElementById("proc-status");
  DOM.procProgress = document.getElementById("proc-progress");
  DOM.chartCanvases = document.querySelectorAll(".chart-canvas");
  DOM.connStatus = document.getElementById("conn-status");
}

async function initializeAll() {
  queryDOM();
  await loadBoardSVG();
  initCharts();
  bindControls();
  initWebSocket();
  log("UI initialized and attempting WS connection");
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeAll);
} else {
  initializeAll();
}
