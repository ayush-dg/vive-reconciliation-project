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

  // Exceptions review page: the "Find in NetSuite" modal. LOOK-ONLY --
  // it GETs an HTML fragment from /netsuite-search and swaps it into the
  // results area. Nothing here POSTs, resolves an exception, or changes
  // any record -- selecting rows only feeds the footer total. The
  // endpoint deliberately sits
  // OUTSIDE /exceptions/, which is a {vendor_name:path} catch-all that
  // would otherwise swallow it.
  const nsFindBtn = document.getElementById("nsFindBtn");
  const nsModal = document.getElementById("nsModal");
  if (nsFindBtn && nsModal) {
    const ctx = nsFindBtn.dataset;
    const nsResults = document.getElementById("nsResults");
    const nsInvoice = document.getElementById("nsInvoice");
    const nsFoot = document.getElementById("nsFootSummary");
    const statementAmount = parseFloat(ctx.amount || "") || null;

    const TOLERANCE_LABELS = {
      exact: "=", up_to: "≤", "1_dollar": "± $1",
      "5_percent": "± 5%", any: "Any"
    };
    const DATE_LABELS = {
      any: "Any time", 30: "Last 30 days", 90: "Last 90 days", 365: "Last 12 months"
    };

    // Opening defaults. The point is that the modal lands on a useful
    // list rather than an empty box: the statement amount is the
    // strongest signal for a line that did not tie out, so we RANK by it
    // (sort_amount) while leaving the amount filter wide open -- filtering
    // to the exact amount would show an empty list for exactly the
    // exceptions this exists to research.
    function defaultState() {
      return {
        useVendor: true, tolerance: "any", includePaid: false,
        invoice: "", range: "any", dateFrom: "", dateTo: ""
      };
    }

    let state = defaultState();

    function amountChipText() {
      if (state.tolerance === "any" || statementAmount === null) return "Any";
      const money = "$" + statementAmount.toFixed(2);
      if (state.tolerance === "exact") return "= " + money;
      if (state.tolerance === "up_to") return "≤ " + money;
      return TOLERANCE_LABELS[state.tolerance];
    }

    function dateChipText() {
      if (state.range === "custom") {
        return (state.dateFrom || "…") + " → " + (state.dateTo || "…");
      }
      return DATE_LABELS[state.range] || "Any time";
    }

    function renderChips() {
      const v = document.getElementById("nsChipVendor");
      v.setAttribute("aria-pressed", String(state.useVendor));
      v.classList.toggle("ns-chip-on", state.useVendor);
      document.getElementById("nsChipVendorValue").textContent =
        state.useVendor ? (ctx.vendorDisplay || "This vendor") : "Any vendor";

      document.getElementById("nsChipAmountValue").textContent = amountChipText();
      document.getElementById("nsChipAmount").classList.toggle(
        "ns-chip-on", state.tolerance !== "any");

      document.getElementById("nsChipDateValue").textContent = dateChipText();
      document.getElementById("nsChipDate").classList.toggle("ns-chip-on", state.range !== "any");

      const st = document.getElementById("nsChipStatus");
      st.setAttribute("aria-pressed", String(!state.includePaid));
      st.classList.toggle("ns-chip-on", !state.includePaid);
      document.getElementById("nsChipStatusValue").textContent =
        state.includePaid ? "Include paid" : "Open only";
    }

    function computeDates() {
      if (state.range === "custom") return [state.dateFrom, state.dateTo];
      if (state.range === "any") return ["", ""];
      const from = new Date();
      from.setDate(from.getDate() - parseInt(state.range, 10));
      return [from.toISOString().slice(0, 10), ""];
    }

    function runSearch() {
      const dates = computeDates();
      const params = new URLSearchParams({
        vendor_id: ctx.vendorId || "",
        vendor_name: ctx.vendorName || "",
        use_vendor: state.useVendor,
        // amount FILTERS; sort_amount only RANKS. Both are sent so the
        // list stays ranked by closeness even at "Any amount".
        amount: state.tolerance === "any" ? "" : (ctx.amount || ""),
        tolerance: state.tolerance,
        sort_amount: ctx.amount || "",
        invoice_contains: state.invoice,
        include_paid: state.includePaid,
        date_from: dates[0],
        date_to: dates[1]
      });
      nsResults.innerHTML = '<div class="ns-modal-empty">Searching…</div>';
      fetch("/netsuite-search?" + params.toString())
        .then(function (r) { return r.text(); })
        .then(function (html) {
          nsResults.innerHTML = html;
          wireRows();
          updateFooter();
        })
        .catch(function () {
          nsResults.innerHTML =
            '<div class="ns-modal-empty">NetSuite search is unavailable right now.</div>';
        });
    }

    function selectedRows() {
      return Array.prototype.slice.call(
        nsResults.querySelectorAll(".ns-row-check:checked")
      ).map(function (cb) { return cb.closest(".ns-modal-row"); });
    }

    function updateFooter() {
      const rows = selectedRows();
      if (rows.length === 0) { nsFoot.innerHTML = ""; return; }
      let total = 0;
      rows.forEach(function (r) { total += parseFloat(r.dataset.amount) || 0; });
      let html = '<span class="ns-foot-count">' + rows.length + " selected · Total $" +
        total.toFixed(2) + "</span>";
      if (statementAmount !== null) {
        const diff = total - statementAmount;
        html += '<span class="ns-foot-diff">Statement $' + statementAmount.toFixed(2) +
          " · Difference $" + diff.toFixed(2) + "</span>";
        if (Math.abs(diff) <= 0.01) {
          html += '<span class="ns-foot-match">✓ Matches the statement</span>';
        }
      }
      nsFoot.innerHTML = html;
    }

    function wireRows() {
      nsResults.querySelectorAll(".ns-modal-row").forEach(function (row) {
        const cb = row.querySelector(".ns-row-check");
        row.addEventListener("click", function (ev) {
          if (ev.target.closest(".ns-details-btn")) return;
          if (ev.target !== cb) cb.checked = !cb.checked;
          row.classList.toggle("ns-row-selected", cb.checked);
          updateFooter();
        });
      });
      nsResults.querySelectorAll(".ns-details-btn").forEach(function (btn) {
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          const target = document.getElementById(btn.getAttribute("aria-controls"));
          const open = btn.getAttribute("aria-expanded") === "true";
          btn.setAttribute("aria-expanded", String(!open));
          btn.classList.toggle("ns-details-open", !open);
          if (target) { target.hidden = open; }
        });
      });
    }

    // --- filter wiring -----------------------------------------------
    let debounce = null;
    nsInvoice.addEventListener("input", function () {
      clearTimeout(debounce);
      debounce = setTimeout(function () {
        state.invoice = nsInvoice.value;
        runSearch();
      }, 400);
    });

    document.getElementById("nsChipVendor").addEventListener("click", function () {
      state.useVendor = !state.useVendor;
      renderChips();
      runSearch();
    });
    document.getElementById("nsChipStatus").addEventListener("click", function () {
      state.includePaid = !state.includePaid;
      renderChips();
      runSearch();
    });

    function closePopovers(except) {
      [["nsChipAmount", "nsPopAmount"], ["nsChipDate", "nsPopDate"]].forEach(function (pair) {
        if (pair[1] === except) return;
        document.getElementById(pair[1]).hidden = true;
        document.getElementById(pair[0]).setAttribute("aria-expanded", "false");
      });
    }

    function togglePopover(chipId, popId) {
      const pop = document.getElementById(popId);
      const chip = document.getElementById(chipId);
      const willOpen = pop.hidden;
      closePopovers(willOpen ? popId : null);
      pop.hidden = !willOpen;
      chip.setAttribute("aria-expanded", String(willOpen));
    }

    document.getElementById("nsChipAmount").addEventListener("click", function () {
      togglePopover("nsChipAmount", "nsPopAmount");
    });
    document.getElementById("nsChipDate").addEventListener("click", function () {
      togglePopover("nsChipDate", "nsPopDate");
    });

    document.querySelectorAll("#nsPopAmount .ns-pop-opt").forEach(function (opt) {
      opt.addEventListener("click", function () {
        state.tolerance = opt.dataset.tol;
        closePopovers(null);
        renderChips();
        runSearch();
      });
    });
    document.querySelectorAll("#nsPopDate .ns-pop-opt").forEach(function (opt) {
      opt.addEventListener("click", function () {
        state.range = opt.dataset.range;
        state.dateFrom = "";
        state.dateTo = "";
        closePopovers(null);
        renderChips();
        runSearch();
      });
    });
    document.getElementById("nsDateApply").addEventListener("click", function () {
      state.dateFrom = document.getElementById("nsDateFrom").value;
      state.dateTo = document.getElementById("nsDateTo").value;
      state.range = (state.dateFrom || state.dateTo) ? "custom" : "any";
      closePopovers(null);
      renderChips();
      runSearch();
    });

    document.getElementById("nsReset").addEventListener("click", function () {
      state = defaultState();
      nsInvoice.value = state.invoice;
      document.getElementById("nsDateFrom").value = "";
      document.getElementById("nsDateTo").value = "";
      renderChips();
      runSearch();
    });
    document.getElementById("nsReload").addEventListener("click", runSearch);

    // --- open / close -------------------------------------------------
    function openModal() {
      state = defaultState();
      nsInvoice.value = state.invoice;
      renderChips();
      nsModal.showModal();
      runSearch();
    }
    function closeModal() {
      closePopovers(null);
      if (nsModal.open) { nsModal.close(); }
    }

    nsFindBtn.addEventListener("click", openModal);
    document.getElementById("nsModalClose").addEventListener("click", closeModal);
    document.getElementById("nsModalDone").addEventListener("click", closeModal);
    // Clicking the backdrop: <dialog> reports clicks on the backdrop as
    // clicks on the dialog element itself, so anything landing directly
    // on it (rather than on a child) is a backdrop click.
    nsModal.addEventListener("click", function (ev) {
      if (ev.target === nsModal) { closeModal(); }
    });
    // Esc fires "cancel" natively; returning focus is our job.
    nsModal.addEventListener("close", function () { nsFindBtn.focus(); });
  }
});
