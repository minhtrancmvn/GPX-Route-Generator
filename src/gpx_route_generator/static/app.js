const form = document.querySelector("#render-form");
const durationInput = document.querySelector("#duration");
const fpsInput = document.querySelector("#fps");
const requestEstimate = document.querySelector("#request-estimate");
const budgetConfirm = document.querySelector("#budget-confirm");
const confirmOverBudget = document.querySelector("#confirm-over-budget");
const renderButton = document.querySelector("#render-button");
const statusTitle = document.querySelector("#status-title");
const formatBadge = document.querySelector("#format-badge");
const progressFill = document.querySelector("#progress-fill");
const progressLabel = document.querySelector("#progress-label");
const requestLabel = document.querySelector("#request-label");
const message = document.querySelector("#message");
const downloadLink = document.querySelector("#download-link");
const previewVideo = document.querySelector("#preview-video");
const emptyState = document.querySelector("#empty-state");
const stageSpinner = document.querySelector("#stage-spinner");
const spinnerLabel = document.querySelector("#spinner-label");
const dropZone = document.querySelector("#drop-zone");
const dropFilename = document.querySelector("#drop-filename");
const gpxFileInput = document.querySelector("#gpx-file");

const dimensions = {
  landscape: "1280 × 720",
  portrait: "720 × 1280",
};

// ─── File drop zone ───────────────────────────────

gpxFileInput.addEventListener("change", () => {
  const file = gpxFileInput.files[0];
  if (file) {
    dropZone.classList.add("has-file");
    dropFilename.textContent = file.name;
  } else {
    dropZone.classList.remove("has-file");
    dropFilename.textContent = "";
  }
});

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag-over");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("drag-over");
});

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    gpxFileInput.files = dt.files;
    dropZone.classList.add("has-file");
    dropFilename.textContent = file.name;
  }
});

// ─── Estimate / format badge ──────────────────────

function currentEstimate() {
  const duration = Number(durationInput.value || 10);
  const fps = Number(fpsInput.value || 24);
  return Math.round(duration * fps);
}

function updateEstimate() {
  const estimate = currentEstimate();
  requestEstimate.textContent = `${estimate} map requests`;
  budgetConfirm.hidden = estimate <= 750;
  if (estimate <= 750) {
    confirmOverBudget.checked = false;
  }
}

function updateFormatBadge() {
  const value = new FormData(form).get("output_format") || "landscape";
  formatBadge.textContent = dimensions[value];
}

// ─── Progress & messages ──────────────────────────

function setProgress(progress, actualRequests) {
  const percent = Math.round((progress || 0) * 100);
  progressFill.style.width = `${percent}%`;
  progressLabel.textContent = `${percent}%`;
  requestLabel.textContent = `${actualRequests || 0} actual requests`;
}

function setMessage(text, type = "") {
  message.textContent = text;
  message.className = "message" + (type ? ` ${type}` : "");
}

function setSpinner(active, label = "Rendering…") {
  stageSpinner.classList.toggle("active", active);
  spinnerLabel.textContent = label;
}

// ─── Form payload ─────────────────────────────────

function buildPayload() {
  const payload = new FormData();
  const file = gpxFileInput.files[0];
  payload.set("gpx_file", file);
  for (const element of form.elements) {
    if (!element.name || element.name === "gpx_file") continue;
    if (element.type === "radio" && !element.checked) continue;
    if (element.type === "checkbox") {
      payload.set(element.name, element.checked ? "true" : "false");
    } else {
      payload.set(element.name, element.value);
    }
  }
  return payload;
}

// ─── Render flow ──────────────────────────────────

async function startRender(event) {
  event.preventDefault();
  downloadLink.hidden = true;
  previewVideo.hidden = true;
  previewVideo.removeAttribute("src");
  emptyState.hidden = false;
  setProgress(0, 0);
  setMessage("");

  if (!gpxFileInput.files[0]) {
    setMessage("Choose a GPX file before rendering.", "error");
    return;
  }

  renderButton.disabled = true;
  renderButton.innerHTML = `
    <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" style="animation: spin 0.75s linear infinite; display:inline-block">
      <path d="M8 1a7 7 0 1 0 7 7h-2a5 5 0 1 1-5-5V1Z"/>
    </svg>
    Rendering…`;
  statusTitle.textContent = "Starting";
  setSpinner(true, "Starting…");

  try {
    const response = await fetch("/api/render", {
      method: "POST",
      body: buildPayload(),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Render could not start.");
    }
    statusTitle.textContent = "Queued";
    setMessage(`Estimated ${data.estimated_map_requests} Google map requests.`);
    pollJob(data.id);
  } catch (error) {
    statusTitle.textContent = "Ready";
    setMessage(error.message, "error");
    setSpinner(false);
    resetButton();
  }
}

function resetButton() {
  renderButton.disabled = false;
  renderButton.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M6 3.5l7 4.5-7 4.5V3.5Z"/></svg>
    Render MP4`;
}

async function pollJob(jobId) {
  try {
    const response = await fetch(`/api/jobs/${jobId}`);
    const job = await response.json();
    if (!response.ok) {
      throw new Error(job.detail || "Could not load job status.");
    }
    statusTitle.textContent = job.status[0].toUpperCase() + job.status.slice(1);
    setProgress(job.progress, job.actual_map_requests);
    setSpinner(true, `${job.progress_frames || 0} / ${job.total_frames || "?"} frames`);

    if (job.status === "completed") {
      const videoUrl = `/api/jobs/${jobId}/video`;
      downloadLink.href = videoUrl;
      downloadLink.hidden = false;
      previewVideo.src = videoUrl;
      previewVideo.hidden = false;
      emptyState.hidden = true;
      setSpinner(false);
      previewVideo.load();
      setMessage("Render complete.", "success");
      resetButton();
      return;
    }

    if (job.status === "failed") {
      setMessage(job.error || "Render failed.", "error");
      setSpinner(false);
      resetButton();
      return;
    }

    setMessage(`${job.progress_frames} of ${job.total_frames} frames rendered.`);
    window.setTimeout(() => pollJob(jobId), 1000);
  } catch (error) {
    setMessage(error.message, "error");
    setSpinner(false);
    resetButton();
  }
}

// ─── Event listeners ──────────────────────────────

form.addEventListener("submit", startRender);
form.addEventListener("input", () => {
  updateEstimate();
  updateFormatBadge();
});
form.addEventListener("change", () => {
  updateEstimate();
  updateFormatBadge();
});
updateEstimate();
updateFormatBadge();

