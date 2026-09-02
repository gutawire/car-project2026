const FRAME_WIDTH = 320;
const FRAME_HEIGHT = 240;
const FRAME_INTERVAL_MS = 125; // ~8fps
const JPEG_QUALITY = 0.6;

const video = document.getElementById("video");
const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const statusEl = document.getElementById("status");
const eyeStateEl = document.getElementById("eyeState");
const overlay = document.getElementById("overlay");
const overlayCtx = overlay.getContext("2d");
const clockEl = document.getElementById("clock");
const hudEl = document.getElementById("hud");
const sessionBtn = document.getElementById("sessionBtn");
const warningBanner = document.getElementById("warningBanner");
const actionInfoEl = document.getElementById("actionInfo");
const logEl = document.getElementById("terminalLog");

canvas.width = FRAME_WIDTH;
canvas.height = FRAME_HEIGHT;
overlay.width = FRAME_WIDTH;
overlay.height = FRAME_HEIGHT;

const socket = io({
  secure: true,
  reconnection: true,
  reconnectionAttempts: Infinity,
  reconnectionDelay: 500,
  reconnectionDelayMax: 3000,
});

let lastDriving = null;
let lastEyeState = null;

// --- System log: a scrolling terminal feed of notable events. Purely a
// client-side readout (each call just timestamps + appends a line), capped
// so it can't grow forever on a long-running session. ---
const LOG_MAX_LINES = 60;

function logLine(text, cls = "") {
  const line = document.createElement("div");
  line.className = `log-line ${cls}`;
  const t = new Date();
  line.textContent = `[${pad2(t.getHours())}:${pad2(t.getMinutes())}:${pad2(t.getSeconds())}] ${text}`;
  logEl.appendChild(line);
  while (logEl.children.length > LOG_MAX_LINES) {
    logEl.removeChild(logEl.firstChild);
  }
  logEl.scrollTop = logEl.scrollHeight;
}

logLine("DRIVER WATCH SYSTEM BOOT", "log-sys");
logLine("cascades loaded: face + eye", "log-sys");
logLine("awaiting camera stream...", "log-sys");

// --- Dashcam-style clock, top-right of the video, ticks every second on
// its own so it never freezes even if frames/detections stop arriving. ---
function pad2(n) {
  return String(n).padStart(2, "0");
}
function formatClock(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} `
       + `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}
function tickClock() {
  clockEl.textContent = formatClock(new Date());
}
tickClock();
setInterval(tickClock, 1000);

// --- Live HUD: frames-per-second (from status arrival spacing) and how
// long the car has been continuously driving. ---
const frameTimestamps = [];
let drivingSince = null;
let currentFps = null;
let lastFrameNumber = null;

function recordStatusTiming() {
  const now = performance.now();
  frameTimestamps.push(now);
  if (frameTimestamps.length > 20) frameTimestamps.shift();
  if (frameTimestamps.length < 2) {
    currentFps = null;
    return;
  }
  const span = frameTimestamps[frameTimestamps.length - 1] - frameTimestamps[0];
  currentFps = (frameTimestamps.length - 1) / (span / 1000);
}

function formatElapsed(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  return `${pad2(Math.floor(totalSeconds / 60))}:${pad2(totalSeconds % 60)}`;
}

function updateHud() {
  const fpsText = currentFps ? `${currentFps.toFixed(1)} FPS` : "-- FPS";
  const drivingText = drivingSince ? `DRIVING ${formatElapsed(Date.now() - drivingSince)}` : "STOPPED";
  const frameText = lastFrameNumber != null ? `FRAME #${lastFrameNumber}` : "FRAME #--";
  hudEl.textContent = `${fpsText} · ${drivingText} · ${frameText}`;
}
updateHud();
setInterval(updateHud, 1000);

// --- Action / alarm readout: reflects whichever motor action is active
// (autonomous drive, or a held hardware-test button) and whether the
// buzzer is currently sounding. Manual button presses update this
// immediately (the phone already knows what it just pressed) rather than
// waiting on a server round-trip. ---
let lastStatus = { driving: false, alarm: false };
let manualAction = null; // "forward" | "backward" | "left" | "right" while held
let manualBuzzerOn = false;

function updateActionInfo() {
  const actionText = manualAction
    ? manualAction.toUpperCase()
    : (lastStatus.driving ? "FORWARD (auto)" : "STOPPED");
  const alarmOn = manualBuzzerOn || lastStatus.alarm;
  actionInfoEl.textContent = `ACTION: ${actionText}  ·  ALARM: ${alarmOn ? "ON" : "off"}`;
  actionInfoEl.classList.toggle("alarm-active", alarmOn);
}
updateActionInfo();

// --- Bounding-box overlay, sci-fi targeting-reticle style: corner
// brackets + a small glowing label, not a plain rectangle. Detection boxes
// come back in the *unmirrored* frame the server actually analyzed, but
// the <video> preview is CSS-mirrored (scaleX(-1)) for a natural selfie
// view. Flip the x-axis here in plain math (not a CSS transform on the
// canvas) so boxes land in the right spot while label text stays
// right-reading, not mirrored. ---
function mirroredX(x, w) {
  return FRAME_WIDTH - x - w;
}

function drawBracket(x, y, w, h, color, label) {
  const c = 8; // corner tick length
  overlayCtx.strokeStyle = color;
  overlayCtx.lineWidth = 2;
  overlayCtx.shadowColor = color;
  overlayCtx.shadowBlur = 6;

  const corners = [
    [x, y, 1, 1], [x + w, y, -1, 1],
    [x, y + h, 1, -1], [x + w, y + h, -1, -1],
  ];
  for (const [cx, cy, dx, dy] of corners) {
    overlayCtx.beginPath();
    overlayCtx.moveTo(cx, cy + c * dy);
    overlayCtx.lineTo(cx, cy);
    overlayCtx.lineTo(cx + c * dx, cy);
    overlayCtx.stroke();
  }

  if (label) {
    overlayCtx.font = "10px ui-monospace, monospace";
    overlayCtx.fillStyle = color;
    overlayCtx.shadowBlur = 4;
    overlayCtx.fillText(label, x, y - 4);
  }
  overlayCtx.shadowBlur = 0;
}

function drawOverlay(data) {
  overlayCtx.clearRect(0, 0, FRAME_WIDTH, FRAME_HEIGHT);

  if (data.face) {
    const [x, y, w, h] = data.face;
    drawBracket(mirroredX(x, w), y, w, h, "#39ff14", "FACE_LOCK");
  }

  (data.eyes || []).forEach(([x, y, w, h], i) => {
    drawBracket(mirroredX(x, w), y, w, h, "#00e5ff", `EYE_${i}`);
  });
}

socket.on("connect", () => {
  statusEl.textContent = "Connected";
  statusEl.className = "status status-driving";
  logLine("socket connected", "log-sys");
});

socket.on("disconnect", (reason) => {
  statusEl.textContent = `Disconnected (${reason}) - reconnecting...`;
  statusEl.className = "status status-stopped";
  logLine(`socket disconnected (${reason})`, "log-warn");
});

// Reconnection events live on the Manager (socket.io), not the Socket itself.
socket.io.on("reconnect_attempt", (attempt) => {
  statusEl.textContent = `Reconnecting... (attempt ${attempt})`;
  statusEl.className = "status status-connecting";
});

socket.io.on("reconnect", () => {
  statusEl.textContent = "Reconnected";
  statusEl.className = "status status-driving";
  logLine("socket reconnected", "log-sys");
});

// Keep the screen awake so the camera loop and socket connection don't get
// suspended by the phone going to sleep mid-test.
let wakeLock = null;
async function requestWakeLock() {
  if (!("wakeLock" in navigator)) return;
  try {
    wakeLock = await navigator.wakeLock.request("screen");
  } catch (err) {
    console.warn("Wake lock failed:", err.message);
  }
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") requestWakeLock();
});
requestWakeLock();

function updateSessionButton(armed) {
  sessionBtn.textContent = armed ? "Stop" : "Start Driving";
  sessionBtn.classList.toggle("session-start", !armed);
  sessionBtn.classList.toggle("session-stop", armed);
}

sessionBtn.addEventListener("click", () => {
  const currentlyArmed = sessionBtn.classList.contains("session-stop");
  if (currentlyArmed) {
    socket.emit("stop_session");
    logLine("STOP requested from phone", "log-warn");
  } else {
    socket.emit("start_session");
    logLine("START requested from phone", "log-sys");
  }
});

socket.on("status", (data) => {
  eyeStateEl.textContent = `eyes: ${data.eye_state}`;
  drawOverlay(data);
  recordStatusTiming();
  lastFrameNumber = data.frame_number;
  lastStatus = { driving: data.driving, alarm: data.alarm };
  updateActionInfo();
  updateSessionButton(data.armed);

  if (data.eye_state !== lastEyeState) {
    logLine(`EYE_STATE -> ${data.eye_state.toUpperCase()}`);
    lastEyeState = data.eye_state;
  }

  if (data.warning) {
    warningBanner.hidden = false;
    warningBanner.textContent = `⚠ WAKE UP - stopping in ${data.warning_seconds_left.toFixed(1)}s`;
  } else {
    warningBanner.hidden = true;
  }

  if (data.driving) {
    statusEl.textContent = "AWAKE - Driving";
    statusEl.className = "status status-driving";
    if (!lastDriving) {
      drivingSince = Date.now();
      logLine("MOTOR: FORWARD (drowsiness check passed)", "log-ok");
    }
  } else {
    statusEl.textContent = data.armed ? "STOPPED" : "Tap Start to begin";
    statusEl.className = "status status-stopped";
    drivingSince = null;
    if (lastDriving) logLine("MOTOR: STOP", "log-warn");
  }
  updateHud();

  if (lastDriving && !data.driving && navigator.vibrate) {
    navigator.vibrate([200, 100, 200]);
  }
  lastDriving = data.driving;
});

// Hardware test panel: hold a button to drive/beep, release to stop. Uses
// Pointer Events so mouse and touch share one code path, and treats
// pointerleave/pointercancel the same as release so a finger sliding off
// the button (rather than a clean tap-up) still stops the motor.
document.querySelectorAll(".dpad-btn[data-action]").forEach((btn) => {
  const action = btn.dataset.action;
  if (action === "stop") {
    btn.addEventListener("click", () => {
      socket.emit("manual_control", { action: "stop" });
      manualAction = null;
      updateActionInfo();
      logLine("MANUAL: STOP", "log-warn");
    });
    return;
  }
  const start = (e) => {
    e.preventDefault();
    socket.emit("manual_control", { action });
    manualAction = action;
    updateActionInfo();
    logLine(`MANUAL: ${action.toUpperCase()}`);
  };
  const stop = (e) => {
    e.preventDefault();
    socket.emit("manual_control", { action: "stop" });
    manualAction = null;
    updateActionInfo();
  };
  btn.addEventListener("pointerdown", start);
  btn.addEventListener("pointerup", stop);
  btn.addEventListener("pointerleave", stop);
  btn.addEventListener("pointercancel", stop);
});

const buzzerTestBtn = document.getElementById("buzzerTestBtn");
if (buzzerTestBtn) {
  const buzzerOn = (e) => {
    e.preventDefault();
    socket.emit("manual_buzzer", { on: true });
    manualBuzzerOn = true;
    updateActionInfo();
    logLine("MANUAL: BUZZER ON", "log-warn");
  };
  const buzzerOff = (e) => {
    e.preventDefault();
    socket.emit("manual_buzzer", { on: false });
    manualBuzzerOn = false;
    updateActionInfo();
  };
  buzzerTestBtn.addEventListener("pointerdown", buzzerOn);
  buzzerTestBtn.addEventListener("pointerup", buzzerOff);
  buzzerTestBtn.addEventListener("pointerleave", buzzerOff);
  buzzerTestBtn.addEventListener("pointercancel", buzzerOff);
}

async function startCamera() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "user", width: FRAME_WIDTH, height: FRAME_HEIGHT },
    audio: false,
  });
  video.srcObject = stream;
  logLine("camera stream acquired", "log-ok");

  setInterval(() => {
    if (video.readyState < 2) return;
    ctx.drawImage(video, 0, 0, FRAME_WIDTH, FRAME_HEIGHT);
    const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
    // volatile: drop this frame instead of queuing it if the socket is
    // briefly disconnected - a backlog of stale frames flushed on
    // reconnect would otherwise be processed as if they were current.
    socket.volatile.emit("frame", dataUrl);
  }, FRAME_INTERVAL_MS);
}

startCamera().catch((err) => {
  statusEl.textContent = `Camera error: ${err.message}`;
  statusEl.className = "status status-stopped";
  logLine(`CAMERA ERROR: ${err.message}`, "log-warn");
});
