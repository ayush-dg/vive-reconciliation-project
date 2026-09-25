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

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      const files = Array.from(fileInput.files || []);
      if (fileCard) fileCard.style.display = files.length ? "block" : "none";
      if (runBtn) runBtn.disabled = files.length === 0;
      if (fileList) {
        fileList.innerHTML = "";
        files.forEach(function (file) {
          const row = document.createElement("div");
          row.className = "file-row";
          row.innerHTML =
            '<div class="file-icon"><svg class="icon" style="width:18px;height:18px"><use href="#i-file"/></svg></div>' +
            '<div class="file-row-main"><div class="file-row-top">' +
            '<span class="fname"></span><span class="fsize"></span></div></div>';
          row.querySelector(".fname").textContent = file.name;
          row.querySelector(".fsize").textContent = (file.size / (1024 * 1024)).toFixed(1) + " MB";
          fileList.appendChild(row);
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

  // Home page: while any job is still PENDING/PROCESSING, reload
  // periodically so statuses (and the reconciliation runs table, once a
  // job completes) stay current. GET /jobs is the source of truth for
  // whether there's still anything worth refreshing for — once it comes
  // back empty, this stops rescheduling itself and the page goes quiet.
  // FAILED is a terminal state (queries.get_active_jobs() no longer
  // includes it, see queries.get_failed_jobs()) -- a job that flips from
  // PROCESSING straight to FAILED is still caught by the reload already
  // scheduled from the prior in-flight check.
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

  // Exceptions review page: the "Search NetSuite" open-AP panel. Fetches
  // an HTML fragment from /netsuite-search and swaps it into the results
  // div, so relaxing a filter never reloads the exception under review.
  // The route deliberately sits OUTSIDE /exceptions/, which is a
  // {vendor_name:path} catch-all that would otherwise swallow it.
  const nsForm = document.getElementById("nsSearchForm");
  if (nsForm) {
    const nsResults = document.getElementById("nsSearchResults");

    function runNetsuiteSearch() {
      const params = new URLSearchParams({
        vendor_id: nsForm.dataset.vendorId || "",
        vendor_name: nsForm.dataset.vendorName || "",
        use_vendor: document.getElementById("nsUseVendor").checked,
        amount: document.getElementById("nsAmount").value,
        tolerance: document.getElementById("nsTolerance").value,
        invoice_contains: document.getElementById("nsInvoice").value,
        include_paid: document.getElementById("nsIncludePaid").checked
      });
      nsResults.innerHTML = '<div class="empty-state">Searching…</div>';
      fetch("/netsuite-search?" + params.toString())
        .then(function (r) { return r.text(); })
        .then(function (html) { nsResults.innerHTML = html; })
        .catch(function () {
          nsResults.innerHTML =
            '<div class="empty-state">NetSuite search is unavailable right now.</div>';
        });
    }

    document.getElementById("nsSearchBtn")
      .addEventListener("click", runNetsuiteSearch);
    // One automatic run on load with the filters pre-filled from the
    // exception, so the panel opens on the tightest sensible search
    // rather than an empty box the user has to prime themselves.
    runNetsuiteSearch();
  }
});
