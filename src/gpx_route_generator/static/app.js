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

const dimensions = {
  landscape: "1280 x 720",
  portrait: "720 x 1280",
};

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

function setProgress(progress, actualRequests) {
  const percent = Math.round((progress || 0) * 100);
  progressFill.style.width = `${percent}%`;
  progressLabel.textContent = `${percent}%`;
  requestLabel.textContent = `${actualRequests || 0} actual requests`;
}

function setMessage(text, isError = false) {
  message.textContent = text;
  message.classList.toggle("error", isError);
}

function buildPayload() {
  const payload = new FormData();
  const file = document.querySelector("#gpx-file").files[0];
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

async function startRender(event) {
  event.preventDefault();
  downloadLink.hidden = true;
  previewVideo.hidden = true;
  previewVideo.removeAttribute("src");
  emptyState.hidden = false;
  setProgress(0, 0);
  setMessage("");

  if (!document.querySelector("#gpx-file").files[0]) {
    setMessage("Choose a GPX file before rendering.", true);
    return;
  }

  renderButton.disabled = true;
  renderButton.textContent = "Rendering...";
  statusTitle.textContent = "Starting";

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
    setMessage(error.message, true);
    renderButton.disabled = false;
    renderButton.textContent = "Render MP4";
  }
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

    if (job.status === "completed") {
      const videoUrl = `/api/jobs/${jobId}/video`;
      downloadLink.href = videoUrl;
      downloadLink.hidden = false;
      previewVideo.src = videoUrl;
      previewVideo.hidden = false;
      emptyState.hidden = true;
      previewVideo.load();
      setMessage("Render complete.");
      renderButton.disabled = false;
      renderButton.textContent = "Render MP4";
      return;
    }

    if (job.status === "failed") {
      setMessage(job.error || "Render failed.", true);
      renderButton.disabled = false;
      renderButton.textContent = "Render MP4";
      return;
    }

    setMessage(`${job.progress_frames} of ${job.total_frames} frames rendered.`);
    window.setTimeout(() => pollJob(jobId), 1000);
  } catch (error) {
    setMessage(error.message, true);
    renderButton.disabled = false;
    renderButton.textContent = "Render MP4";
  }
}

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

