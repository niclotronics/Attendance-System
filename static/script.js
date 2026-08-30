/* ==================================================================
   Government Polytechnic Pune - Smart Attendance System v2.0
   Shared JavaScript Utilities & Helpers
   ================================================================== */

/** Show temporary alert inside container element */
function showAlert(containerEl, message, type) {
  if (!containerEl) return;
  const icon = type === "success" ? "bi-check-circle-fill" : type === "warning" ? "bi-exclamation-triangle-fill" : "bi-exclamation-octagon-fill";
  containerEl.innerHTML = `
    <div class="alert alert-${type}">
      <i class="bi ${icon}"></i>
      <span>${message}</span>
    </div>`;
  containerEl.style.display = "block";
}

function clearAlert(containerEl) {
  if (!containerEl) return;
  containerEl.innerHTML = "";
  containerEl.style.display = "none";
}

/** Toast notifications (top-right floating) */
function showToast(message, type = "success") {
  let toastBox = document.getElementById("toastContainer");
  if (!toastBox) {
    toastBox = document.createElement("div");
    toastBox.id = "toastContainer";
    toastBox.style.cssText = "position:fixed;top:20px;right:20px;z-index:99999;display:flex;flex-direction:column;gap:10px;";
    document.body.appendChild(toastBox);
  }

  const toast = document.createElement("div");
  const bg = type === "success" ? "#10b981" : type === "warning" ? "#f59e0b" : "#ef4444";
  toast.style.cssText = `background:${bg};color:#fff;padding:12px 20px;border-radius:10px;font-weight:600;font-size:0.88rem;box-shadow:0 10px 25px rgba(0,0,0,0.4);display:flex;align-items:center;gap:10px;animation:fadeDown 0.3s ease;`;
  toast.innerHTML = `<i class="bi bi-bell-fill"></i> ${message}`;

  toastBox.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transition = "opacity 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

/** Generic Modal Open / Close */
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("active");
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("active");
}

/** Format seconds -> MM:SS */
function formatMMSS(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${String(m).padStart(2, "0")}:${String(rem).padStart(2, "0")}`;
}

/** Return progress bar color class based on percentage */
function progressColorClass(pct) {
  if (pct >= 85) return "progress-green";
  if (pct >= 75) return "progress-orange";
  return "progress-red";
}

/** Return badge class based on status text */
function statusBadgeClass(status) {
  if (status === "Safe") return "badge-safe";
  if (status === "Warning") return "badge-warning";
  return "badge-danger";
}

/** Fetch API wrapper POST */
async function postJSON(url, payload) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    return await res.json();
  } catch (err) {
    console.error("POST Error:", err);
    throw err;
  }
}

/** Fetch API wrapper GET */
async function getJSON(url) {
  try {
    const res = await fetch(url);
    return await res.json();
  } catch (err) {
    console.error("GET Error:", err);
    throw err;
  }
}

/** QR Code helper function using Google Charts QR API fallback or QRCode.js */
function renderQRCode(containerId, qrText, size = 180) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";

  if (window.QRCode) {
    new QRCode(container, {
      text: qrText,
      width: size,
      height: size,
      colorDark: "#030712",
      colorLight: "#ffffff",
      correctLevel: QRCode.CorrectLevel.H,
    });
  } else {
    // Fallback QR generator image
    const img = document.createElement("img");
    img.src = `https://api.qrserver.com/v1/create-qr-code/?size=${size}x${size}&data=${encodeURIComponent(qrText)}&color=030712&bgcolor=ffffff`;
    img.alt = "Attendance QR Code";
    img.style.width = size + "px";
    img.style.height = size + "px";
    img.style.borderRadius = "8px";
    container.appendChild(img);
  }
}