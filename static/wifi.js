const scanBtn = document.getElementById("scanBtn");
const networkList = document.getElementById("networkList");
const connectForm = document.getElementById("connectForm");
const ssidInput = document.getElementById("ssid");
const passwordInput = document.getElementById("password");
const resultEl = document.getElementById("result");

function showResult(message, ok) {
  resultEl.textContent = message;
  resultEl.className = `wifi-result ${ok ? "wifi-result-ok" : "wifi-result-error"}`;
}

function signalBars(signal) {
  const bars = Math.max(1, Math.ceil((signal / 100) * 4));
  return "█".repeat(bars) + "░".repeat(4 - bars);
}

async function scan() {
  scanBtn.disabled = true;
  scanBtn.textContent = "Scanning...";
  networkList.innerHTML = "";
  try {
    const res = await fetch("/wifi/networks");
    const networks = await res.json();
    if (networks.length === 0) {
      networkList.innerHTML = "<li class=\"hint\">No networks found. Try again.</li>";
    }
    for (const n of networks) {
      const li = document.createElement("li");
      li.className = "network-item";
      li.textContent = `${signalBars(n.signal)} ${n.ssid} ${n.secure ? "🔒" : ""} ${n.in_use ? "(connected)" : ""}`;
      li.addEventListener("click", () => {
        ssidInput.value = n.ssid;
        passwordInput.value = "";
        connectForm.hidden = false;
        passwordInput.focus();
      });
      networkList.appendChild(li);
    }
  } catch (err) {
    showResult(`Scan failed: ${err.message}`, false);
  } finally {
    scanBtn.disabled = false;
    scanBtn.textContent = "Scan for networks";
  }
}

connectForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const confirmed = confirm(
    "This will likely drop your phone's connection to the car right away " +
    "(one WiFi radio can't be a hotspot and a client at once). Continue?"
  );
  if (!confirmed) return;

  const submitBtn = connectForm.querySelector("button[type=submit]");
  submitBtn.disabled = true;
  showResult("Connecting... (this page may disconnect now, that's expected)", true);
  try {
    const res = await fetch("/wifi/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ssid: ssidInput.value, password: passwordInput.value }),
    });
    const data = await res.json();
    showResult(data.message, data.ok);
  } catch (err) {
    showResult(`Connect failed: ${err.message}`, false);
  } finally {
    submitBtn.disabled = false;
  }
});

scanBtn.addEventListener("click", scan);
scan();
