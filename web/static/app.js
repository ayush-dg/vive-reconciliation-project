// Upload page: list every picked file in the file-card (multiple files are
// supported), and show a brief "Queuing..." overlay while the upload
// request is in flight — it returns as soon as files are saved and queued,
// the pipeline itself now runs later on the background worker.
document.addEventListener("DOMContentLoaded", function () {
  const fileInput = document.getElementById("pdf-file-input");
  const fileCard = document.getElementById("file-card");
  const fileList = document.getElementById("file-list");
  const form = document.getElementById("upload-form");
  const overlay = document.getElementById("processing-overlay");
  const runBtn = document.getElementById("run-btn");

  // Live vendor/statement-period preview: fired the moment a file is
  // picked, well before the user clicks "Queue for reconciliation" (or
  // even decides to submit at all). This is a separate, cheap Haiku-based
  // call (see src/ai/quick_preview.py) — not the real extraction, which
  // only runs once the file is actually queued. Never blocks the form:
  // any failure just leaves the fields at their default placeholder text.
  const previewVendor = document.getElementById("preview-vendor");
  const previewPeriod = document.getElementById("preview-period");

  function runFilePreview(file, previewEl) {
    previewEl.textContent = "Detecting vendor & period…";
    const formData = new FormData();
    formData.append("file", file);
    fetch("/upload/preview", { method: "POST", body: formData })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        const vendor = data.vendor_name || "Not detected";
        const period = data.statement_period || "Not detected";
        previewEl.textContent = vendor + " · " + period;
        // Only one file selected: also fill in the shared form-card fields.
        if (fileInput.files.length === 1) {
          if (previewVendor) previewVendor.value = vendor;
          if (previewPeriod) previewPeriod.value = period;
        }
      })
      .catch(function () {
        previewEl.textContent = "Preview unavailable — will still detect during full extraction.";
      });
  }

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      const files = Array.from(fileInput.files || []);
      if (fileCard) fileCard.style.display = files.length ? "block" : "none";
      if (runBtn) runBtn.disabled = files.length === 0;
      if (previewVendor) previewVendor.value = "Detected automatically during processing";
      if (previewPeriod) previewPeriod.value = "Auto-detect from statement";
      if (fileList) {
        fileList.innerHTML = "";
        files.forEach(function (file) {
          const row = document.createElement("div");
          row.className = "file-row";
          row.innerHTML =
            '<div class="file-icon"><svg class="icon" style="width:18px;height:18px"><use href="#i-file"/></svg></div>' +
            '<div class="file-row-main"><div class="file-row-top">' +
            '<span class="fname"></span><span class="fsize"></span></div>' +
            '<div class="file-row-preview"></div></div>';
          row.querySelector(".fname").textContent = file.name;
          row.querySelector(".fsize").textContent = (file.size / (1024 * 1024)).toFixed(1) + " MB";
          fileList.appendChild(row);
          runFilePreview(file, row.querySelector(".file-row-preview"));
        });
      }
    });
  }

  if (form) {
    form.addEventListener("submit", function (e) {
      if (fileInput && fileInput.files.length === 0) {
        e.preventDefault();
        return;
      }
      if (overlay) overlay.classList.add("show");
      if (runBtn) runBtn.disabled = true;
    });
  }

  // Sidebar profile dropdown: click the profile block to toggle, click
  // anywhere else to close. Stopping propagation on the dropdown itself
  // keeps clicks inside it (e.g. the Logout link) from being swallowed by
  // the document-level close handler.
  const profileToggle = document.getElementById("profile-toggle");
  const profileDropdown = document.getElementById("profile-dropdown");
  if (profileToggle && profileDropdown) {
    profileToggle.addEventListener("click", function (e) {
      e.stopPropagation();
      profileDropdown.classList.toggle("show");
    });
    profileDropdown.addEventListener("click", function (e) {
      e.stopPropagation();
    });
    document.addEventListener("click", function () {
      profileDropdown.classList.remove("show");
    });
  }

  // Home page: while any job is still PENDING/PROCESSING/FAILED, reload
  // periodically so statuses (and the reconciliation runs table, once a
  // job completes) stay current. GET /jobs is the source of truth for
  // whether there's still anything worth refreshing for — once it comes
  // back empty, this stops rescheduling itself and the page goes quiet.
  if (document.body.dataset.page === "home") {
    fetch("/jobs")
      .then(function (r) { return r.json(); })
      .then(function (activeJobs) {
        if (activeJobs.length > 0) {
          setTimeout(function () { location.reload(); }, 30000);
        }
      })
      .catch(function () {});
  }

  // Upload results page (/upload/status/{batch_id}): while any file in
  // this batch is still queued/extracting, poll and reload so vendor,
  // statement period, and extracted invoices appear as soon as each file
  // finishes — same reload-on-poll pattern as the home page above, just on
  // a shorter interval since the user is actively watching right after
  // submitting.
  var batchPollEl = document.getElementById("batch-poll-data");
  if (batchPollEl) {
    var batchId = batchPollEl.dataset.batchId;
    fetch("/upload/status/" + batchId + "/poll")
      .then(function (r) { return r.json(); })
      .then(function (jobs) {
        var stillActive = jobs.some(function (j) {
          return j.status === "PENDING" || j.status === "PROCESSING";
        });
        if (stillActive) {
          setTimeout(function () { location.reload(); }, 8000);
        }
      })
      .catch(function () {});
  }
});
