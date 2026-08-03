/* ==================================================================
   Government Polytechnic Pune - Smart Attendance System
   Shared JavaScript helpers (toast, modal, formatting)
   ================================================================== */

/** Show a temporary toast-style alert inside a given container element */
function showAlert(containerEl, message, type) {
  // type: "success" | "error" | "warning"
  if (!containerEl) return;
  containerEl.innerHTML = `<div class="alert alert-${type}">${message}</div>`;
  containerEl.style.display = "block";
}

function clearAlert(containerEl) {
  if (!containerEl) return;
  containerEl.innerHTML = "";
  containerEl.style.display = "none";
}

/** Generic modal open/close (expects element with id) */
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

/** Return the progress bar color class based on percentage */
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

/** Small helper to POST JSON and parse JSON response */
async function postJSON(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  return res.json();
}

/** Small helper to GET JSON */
async function getJSON(url) {
  const res = await fetch(url);
  return res.json();
}