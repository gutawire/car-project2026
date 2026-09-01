const FRAME_WIDTH = 320;
const FRAME_HEIGHT = 240;
const FRAME_INTERVAL_MS = 125; // ~8fps
const JPEG_QUALITY = 0.6;

const video = document.getElementById("video");
const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const statusEl = document.getElementById("status");
const eyeStateEl = document.getElementById("eyeState");

canvas.width = FRAME_WIDTH;
canvas.height = FRAME_HEIGHT;

const socket = io({
  secure: true,
  reconnection: true,
  reconnectionAttempts: Infinity,
  reconnectionDelay: 500,
  reconnectionDelayMax: 3000,
});

let lastDriving = null;

socket.on("connect", () => {
  statusEl.textContent = "Connected";
  statusEl.className = "status status-driving";
});

socket.on("disconnect", (reason) => {
  statusEl.textContent = `Disconnected (${reason}) - reconnecting...`;
  statusEl.className = "status status-stopped";
});

// Reconnection events live on the Manager (socket.io), not the Socket itself.
socket.io.on("reconnect_attempt", (attempt) => {
  statusEl.textContent = `Reconnecting... (attempt ${attempt})`;
  statusEl.className = "status status-connecting";
});

socket.io.on("reconnect", () => {
  statusEl.textContent = "Reconnected";
  statusEl.className = "status status-driving";
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

socket.on("status", (data) => {
  eyeStateEl.textContent = `eyes: ${data.eye_state}`;

  if (data.driving) {
    statusEl.textContent = "AWAKE - Driving";
    statusEl.className = "status status-driving";
  } else {
    statusEl.textContent = "STOPPED";
    statusEl.className = "status status-stopped";
  }

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
    btn.addEventListener("click", () => socket.emit("manual_control", { action: "stop" }));
    return;
  }
  const start = (e) => { e.preventDefault(); socket.emit("manual_control", { action }); };
  const stop = (e) => { e.preventDefault(); socket.emit("manual_control", { action: "stop" }); };
  btn.addEventListener("pointerdown", start);
  btn.addEventListener("pointerup", stop);
  btn.addEventListener("pointerleave", stop);
  btn.addEventListener("pointercancel", stop);
});

const buzzerTestBtn = document.getElementById("buzzerTestBtn");
if (buzzerTestBtn) {
  const buzzerOn = (e) => { e.preventDefault(); socket.emit("manual_buzzer", { on: true }); };
  const buzzerOff = (e) => { e.preventDefault(); socket.emit("manual_buzzer", { on: false }); };
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
});
