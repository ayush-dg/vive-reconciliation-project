// The sticky topbar's height as --topbar-h (2026-10-28), for whatever sits
// just under it -- Exceptions review's exception list (style.css).
(function () {
  function setTopbarHeight() {
    const topbar = document.querySelector(".topbar");
    if (topbar) { document.documentElement.style.setProperty("--topbar-h", topbar.offsetHeight + "px"); }
  }
  document.addEventListener("DOMContentLoaded", setTopbarHeight);
  window.addEventListener("resize", setTopbarHeight);
})();

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

  // Exceptions review page: the "Find in NetSuite" panel -- always open
  // and searching as soon as the page loads (2026-10-16; a modal behind a
  // button before). LOOK-ONLY -- it GETs an HTML fragment from
  // /netsuite-search and swaps it into the results area. Nothing here
  // POSTs, resolves an exception, or changes any record -- rows are not
  // selectable (2026-09-30). The endpoint deliberately sits OUTSIDE
  // /exceptions/, which is a {vendor_name:path} catch-all that would
  // otherwise swallow it.
  const nsPanel = document.getElementById("nsPanel");
  if (nsPanel) {
    const ctx = nsPanel.dataset;
    const nsResults = document.getElementById("nsResults");
    const nsInvoice = document.getElementById("nsInvoice");
    const nsInvoiceHint = document.getElementById("nsInvoiceHint");
    const nsAmountInput = document.getElementById("nsAmountInput");
    const nsStatusOpen = document.getElementById("nsStatusOpen");
    const nsStatusPaid = document.getElementById("nsStatusPaid");
    const nsShopSearch = document.getElementById("nsShopSearch");
    const nsShopBoxes = Array.prototype.slice.call(
      document.querySelectorAll("#nsShopList input[type=checkbox]"));

    // Fewer than this many non-space characters is not selective enough
    // to search by invoice number alone -- mirrors
    // src/matching/netsuite_search.py's MIN_INVOICE_SEARCH_CHARS (kept as
    // a literal here since JS can't import the Python constant; the two
    // are meant to always agree).
    const MIN_INVOICE_CHARS = 4;

    const DATE_LABELS = {
      any: "Any time", 30: "Last 30 days", 90: "Last 90 days", 365: "Last 12 months"
    };

    // Opening defaults. For "Amount Mismatch" specifically, the
    // statement amount is BY DEFINITION not the NetSuite bill's real
    // amount, so filtering to it can never find the bill (confirmed live
    // 2026-09-30 against several real Amount Mismatch exceptions -- the
    // default Exact-at-statement-amount search missed every one of
    // them); this reason instead opens with no amount filter, both
    // statuses ticked, and the invoice number prefilled when it is
    // selective enough to search by. "Not Found in NetSuite"/
    // "Invoice Missing" keep the original Exact + statement amount +
    // Open defaults, where the amount IS expected to match once found.
    function defaultState() {
      const isAmountMismatch = ctx.reason === "Amount Mismatch";
      const invoiceChars = (ctx.invoice || "").replace(/\s+/g, "").length;
      return {
        useVendor: true,
        // Shop: NetSuite location codes ticked in the Shop list. Always
        // starts on "Any shop" (2026-10-16).
        shops: [],
        tolerance: "exact",
        amount: isAmountMismatch ? "" : (ctx.amount || ""),
        statuses: isAmountMismatch ? ["open", "paid"] : ["open"],
        invoice: (isAmountMismatch && invoiceChars >= MIN_INVOICE_CHARS) ? ctx.invoice : "",
        range: "any", dateFrom: "", dateTo: ""
      };
    }

    let state = defaultState();

    function invoiceCharCount() {
      return state.invoice.replace(/\s+/g, "").length;
    }

    // An EMPTY amount box means "no amount filter" regardless of which
    // of the three tolerance buttons is selected -- there is no separate
    // "Any amount" button any more; the chip's x empties the box.
    function amountChipText() {
      const raw = (state.amount || "").trim();
      if (!raw) return "Any amount";
      const n = parseFloat(raw);
      const money = isNaN(n) ? raw : "$" + n.toFixed(2);
      const prefix = state.tolerance === "up_to" ? "Up to "
        : state.tolerance === "at_least" ? "At least " : "Exact ";
      return prefix + money;
    }

    // Both ticked is the "any" state the Status chip's x resets to.
    function statusChipText() {
      if (state.statuses.length !== 1) return "Any status";
      return state.statuses[0] === "paid" ? "Paid" : "Open";
    }

    function shopName(code) {
      const box = nsShopBoxes.find(function (b) { return b.value === code; });
      return box ? box.dataset.name : code;
    }

    function shopChipText() {
      if (!state.shops.length) return "Any shop";
      const first = shopName(state.shops[0]);
      return state.shops.length === 1 ? first : first + " +" + (state.shops.length - 1);
    }

    function dateChipText() {
      if (state.range === "custom") {
        return (state.dateFrom || "…") + " → " + (state.dateTo || "…");
      }
      return DATE_LABELS[state.range] || "Any time";
    }

    // The filter chips: the chip button, its dropdown, and its x (clear)
    // button -- a sibling of the chip, since a button can't nest inside
    // another (2026-10-06). Shop added 2026-10-16.
    const FILTERS = {
      vendor: { chip: "nsChipVendor", pop: "nsPopVendor", clear: "nsClearVendor" },
      shop: { chip: "nsChipShop", pop: "nsPopShop", clear: "nsClearShop" },
      amount: { chip: "nsChipAmount", pop: "nsPopAmount", clear: "nsClearAmount" },
      date: { chip: "nsChipDate", pop: "nsPopDate", clear: "nsClearDate" },
      status: { chip: "nsChipStatus", pop: "nsPopStatus", clear: "nsClearStatus" }
    };

    // Whether a chip is narrowing the search right now. Drives both its
    // highlight and its x, which resets it to the opposite, "any" state
    // (CLEAR_TO_ANY below).
    function filterIsSet(name) {
      if (name === "vendor") return state.useVendor;
      if (name === "shop") return state.shops.length > 0;
      if (name === "amount") return !!state.amount.trim();
      if (name === "date") return state.range !== "any";
      return state.statuses.length === 1;
    }

    // What each chip's x resets it to: Any vendor / Any amount (box
    // emptied, tolerance back to Exact) / Any time / Any status (both
    // ticked). Reset filters, by contrast, goes back to the opening
    // defaults (defaultState()).
    const CLEAR_TO_ANY = {
      vendor: function () { state.useVendor = false; },
      shop: function () { state.shops = []; },
      amount: function () { state.amount = ""; state.tolerance = "exact"; },
      date: function () { state.range = "any"; state.dateFrom = ""; state.dateTo = ""; },
      status: function () { state.statuses = ["open", "paid"]; }
    };

    function renderChips() {
      document.getElementById("nsChipVendorValue").textContent =
        state.useVendor ? (ctx.vendorDisplay || "This vendor") : "Any vendor";
      document.getElementById("nsChipShopValue").textContent = shopChipText();
      document.getElementById("nsChipAmountValue").textContent = amountChipText();
      document.getElementById("nsChipDateValue").textContent = dateChipText();
      document.getElementById("nsChipStatusValue").textContent = statusChipText();

      Object.keys(FILTERS).forEach(function (name) {
        const set = filterIsSet(name);
        const clearBtn = document.getElementById(FILTERS[name].clear);
        document.getElementById(FILTERS[name].chip).classList.toggle("ns-chip-on", set);
        clearBtn.hidden = !set;
        clearBtn.parentElement.classList.toggle("ns-chip-has-clear", set);
      });

      // Mark the chosen tolerance, so picking one with the box still
      // empty (nothing on the chip changes yet) is visible in the list.
      document.querySelectorAll("#nsPopAmount .ns-pop-opt").forEach(function (opt) {
        opt.setAttribute("aria-pressed", String(opt.dataset.tol === state.tolerance));
      });

      nsInvoiceHint.hidden = invoiceCharCount() === 0 || invoiceCharCount() >= MIN_INVOICE_CHARS;
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
        amount: state.amount || "",
        tolerance: state.tolerance,
        // sort_amount only RANKS, and always stays the statement's own
        // amount regardless of what the (now-editable) amount FILTER box
        // holds -- the list keeps ranking by closeness to the statement
        // even once the filter is widened or cleared.
        sort_amount: ctx.amount || "",
        invoice_contains: invoiceCharCount() >= MIN_INVOICE_CHARS ? state.invoice : "",
        statuses: state.statuses.join(","),
        date_from: dates[0],
        date_to: dates[1],
        locations: state.shops.join(",")
      });
      nsResults.innerHTML = '<div class="ns-modal-empty">Searching…</div>';
      setPick(null);
      fetch("/netsuite-search?" + params.toString())
        .then(function (r) { return r.text(); })
        .then(function (html) {
          nsResults.innerHTML = html;
          wireDetailsToggles();
          wirePicks();
          wireMatchedToggle();
        })
        .catch(function () {
          nsResults.innerHTML =
            '<div class="ns-modal-empty">NetSuite search is unavailable right now.</div>';
        });
    }

    // "Accept as match" (2026-10-19): one result can be picked at a time
    // (.ns-pick); the bar below the panel shows it, and its button opens
    // the confirm dialog, whose form posts the record's type + internal id.
    const nsAccept = document.getElementById("nsAccept");
    const nsAcceptDialog = document.getElementById("nsAcceptDialog");
    let picked = null;

    function money(n) {
      const v = Math.abs(n);
      return (n < 0 ? "−$" : "$") + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function setPick(box) {
      picked = box ? box.dataset : null;
      if (!nsAccept) return;
      nsAccept.dataset.state = picked ? "picked" : "empty";
      if (!picked) return;
      const stmt = parseFloat(nsAccept.dataset.statementAmount);
      const ns = parseFloat(picked.amount);
      const kind = picked.recordType === "credit" ? "Credit" : "Bill";
      document.getElementById("nsPickKind").textContent = kind;
      document.getElementById("nsPickTranid").textContent = picked.tranid;
      document.getElementById("nsPickDate").textContent = picked.date || "";
      document.getElementById("nsPickStmt").textContent = isNaN(stmt) ? "—" : money(stmt);
      document.getElementById("nsPickNs").textContent = isNaN(ns) ? "—" : money(ns);
      const diff = (isNaN(stmt) || isNaN(ns)) ? null : Math.round((stmt - ns) * 100) / 100;
      document.getElementById("nsPickDiff").textContent = diff === null ? "—" : money(diff);
      document.getElementById("nsPickDiffWrap").classList.toggle("ns-off", !!diff);
    }

    // Records already matched are hidden by default (2026-10-27); "Show"
    // reveals them (still marked and unpickable), "Hide" puts them away --
    // with their details rows, which only ever open through their own button.
    function wireMatchedToggle() {
      const btn = nsResults.querySelector(".ns-show-matched");
      if (!btn) return;
      btn.addEventListener("click", function () {
        const show = btn.getAttribute("aria-expanded") !== "true";
        btn.setAttribute("aria-expanded", String(show));
        btn.textContent = show ? "Hide" : "Show";
        nsResults.querySelectorAll('tr[data-matched="1"]').forEach(function (tr) {
          tr.hidden = !show;
          if (!show) {
            const details = document.getElementById(tr.dataset.rowId + "-details");
            if (details) { details.hidden = true; }
          }
        });
      });
    }

    function wirePicks() {
      const boxes = nsResults.querySelectorAll(".ns-pick");
      boxes.forEach(function (box) {
        box.addEventListener("change", function () {
          boxes.forEach(function (other) {
            if (other !== box) { other.checked = false; other.closest("tr").classList.remove("ns-picked"); }
          });
          box.closest("tr").classList.toggle("ns-picked", box.checked);
          setPick(box.checked ? box : null);
        });
      });
    }

    if (nsAccept && nsAcceptDialog) {
      document.getElementById("nsAcceptBtn").addEventListener("click", function () {
        if (!picked) return;
        const ns = parseFloat(picked.amount);
        const stmt = parseFloat(nsAccept.dataset.statementAmount);
        document.getElementById("nsAcceptType").value = picked.recordType;
        document.getElementById("nsAcceptId").value = picked.internalId;
        document.getElementById("nsConfirmKind").textContent = picked.recordType;
        document.getElementById("nsConfirmTranid").textContent = picked.tranid;
        document.getElementById("nsConfirmAmount").textContent = isNaN(ns) ? "—" : money(ns);
        const diff = (isNaN(stmt) || isNaN(ns)) ? 0 : Math.round((stmt - ns) * 100) / 100;
        document.getElementById("nsConfirmDiff").textContent =
          diff ? "The " + money(diff) + " difference is accepted as-is." : "";
        nsAcceptDialog.showModal();
      });
      document.getElementById("nsAcceptCancel").addEventListener("click", function () {
        nsAcceptDialog.close();
      });
    }

    // The details toggle per row.
    function wireDetailsToggles() {
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
    let invoiceDebounce = null;
    nsInvoice.addEventListener("input", function () {
      state.invoice = nsInvoice.value;
      nsInvoiceHint.hidden = invoiceCharCount() === 0 || invoiceCharCount() >= MIN_INVOICE_CHARS;
      clearTimeout(invoiceDebounce);
      invoiceDebounce = setTimeout(runSearch, 400);
    });

    let amountDebounce = null;
    nsAmountInput.addEventListener("input", function () {
      state.amount = nsAmountInput.value;
      renderChips();
      clearTimeout(amountDebounce);
      amountDebounce = setTimeout(runSearch, 400);
    });

    function updateStatusesFromCheckboxes() {
      // At least one box stays ticked -- unticking the last one keeps
      // Open ticked rather than allowing a "no status" search.
      if (!nsStatusOpen.checked && !nsStatusPaid.checked) {
        nsStatusOpen.checked = true;
      }
      state.statuses = [];
      if (nsStatusOpen.checked) state.statuses.push("open");
      if (nsStatusPaid.checked) state.statuses.push("paid");
      renderChips();
      runSearch();
    }
    nsStatusOpen.addEventListener("change", updateStatusesFromCheckboxes);
    nsStatusPaid.addEventListener("change", updateStatusesFromCheckboxes);

    // Shop list: ticking a box searches again (the dropdown stays open so
    // several can be ticked); the box above it narrows the list by name.
    let shopDebounce = null;
    nsShopBoxes.forEach(function (box) {
      box.addEventListener("change", function () {
        state.shops = nsShopBoxes.filter(function (b) { return b.checked; })
          .map(function (b) { return b.value; });
        renderChips();
        clearTimeout(shopDebounce);
        shopDebounce = setTimeout(runSearch, 300);
      });
    });
    function filterShopList() {
      const q = nsShopSearch.value.trim().toLowerCase();
      nsShopBoxes.forEach(function (box) {
        box.parentElement.hidden = !!q && box.parentElement.dataset.name.indexOf(q) === -1;
      });
    }
    nsShopSearch.addEventListener("input", filterShopList);

    function closePopovers(except) {
      Object.keys(FILTERS).forEach(function (name) {
        if (name === except) return;
        document.getElementById(FILTERS[name].pop).hidden = true;
        document.getElementById(FILTERS[name].chip).setAttribute("aria-expanded", "false");
      });
    }

    // Opening one dropdown closes any other.
    function togglePopover(name) {
      const pop = document.getElementById(FILTERS[name].pop);
      const willOpen = pop.hidden;
      closePopovers(willOpen ? name : null);
      pop.hidden = !willOpen;
      document.getElementById(FILTERS[name].chip).setAttribute("aria-expanded", String(willOpen));
    }

    // The filter whose dropdown is open, or null.
    function openFilter() {
      return Object.keys(FILTERS).find(function (name) {
        return !document.getElementById(FILTERS[name].pop).hidden;
      }) || null;
    }

    // The x: back to the "any" state, search again, and move focus to
    // the chip, since the x itself disappears.
    function clearFilter(name) {
      CLEAR_TO_ANY[name]();
      applyStateToInputs();
      closePopovers(null);
      renderChips();
      runSearch();
      document.getElementById(FILTERS[name].chip).focus();
    }

    Object.keys(FILTERS).forEach(function (name) {
      document.getElementById(FILTERS[name].chip).addEventListener("click", function () {
        togglePopover(name);
      });
      document.getElementById(FILTERS[name].clear).addEventListener("click", function () {
        clearFilter(name);
      });
    });

    document.querySelectorAll("#nsPopVendor .ns-pop-opt").forEach(function (opt) {
      opt.addEventListener("click", function () {
        state.useVendor = opt.dataset.vendor === "on";
        closePopovers(null);
        renderChips();
        runSearch();
      });
    });
    document.querySelectorAll("#nsPopAmount .ns-pop-opt").forEach(function (opt) {
      opt.addEventListener("click", function () {
        state.tolerance = opt.dataset.tol;
        renderChips();
        if (!state.amount.trim()) {
          // Nothing to apply a tolerance to yet (and nothing to search
          // differently): keep the dropdown open and put the cursor in
          // the amount box instead of closing with no visible change.
          nsAmountInput.focus();
          return;
        }
        closePopovers(null);
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

    function applyStateToInputs() {
      nsInvoice.value = state.invoice;
      nsAmountInput.value = state.amount;
      nsStatusOpen.checked = state.statuses.indexOf("open") !== -1;
      nsStatusPaid.checked = state.statuses.indexOf("paid") !== -1;
      document.getElementById("nsDateFrom").value = state.dateFrom;
      document.getElementById("nsDateTo").value = state.dateTo;
      nsShopBoxes.forEach(function (box) { box.checked = state.shops.indexOf(box.value) !== -1; });
      nsShopSearch.value = "";
      filterShopList();
    }

    document.getElementById("nsReset").addEventListener("click", function () {
      state = defaultState();
      applyStateToInputs();
      closePopovers(null);
      renderChips();
      runSearch();
    });
    document.getElementById("nsReload").addEventListener("click", runSearch);

    // An open dropdown closes on a click anywhere outside its own chip,
    // x and dropdown -- on the page, not just in the panel. Capture phase,
    // so it still runs for controls that stop propagation (the results'
    // Details toggles). Clicks inside it -- the amount box, the date
    // inputs, the status and shop checkboxes -- keep it open.
    document.addEventListener("click", function (ev) {
      const open = openFilter();
      if (open && !document.getElementById(FILTERS[open].pop).parentElement.contains(ev.target)) {
        closePopovers(null);
      }
    }, true);
    // Escape with a dropdown open closes only that dropdown and returns
    // focus to its chip.
    nsPanel.addEventListener("keydown", function (ev) {
      const open = openFilter();
      if (ev.key !== "Escape" || !open) return;
      ev.preventDefault();
      closePopovers(null);
      document.getElementById(FILTERS[open].chip).focus();
    });

    // Always open: search straight away with this exception's defaults.
    applyStateToInputs();
    renderChips();
    runSearch();
  }

  // "Past syncs" picker (2026-10-01): a fixed-label button plus a
  // role="listbox" popup (styled like the NetSuite modal's .ns-popover),
  // layered over a visually hidden native <select> -- the same bridge as
  // the calendar button over its hidden date input. The <select> stays the
  // real control: the list is rebuilt from its options every time it
  // opens, so it always marks the select's current value, and picking an
  // entry sets select.value and fires the select's own "change" event, so
  // whatever the page already does on change (submit the form, re-filter
  // cards) runs exactly as before. Picking always fires "change", even for
  // the entry that's already selected.
  document.querySelectorAll("[data-sync-picker]").forEach(function (wrap) {
    const select = document.getElementById(wrap.dataset.syncPicker);
    const button = wrap.querySelector(".sync-picker-btn");
    const list = wrap.querySelector(".sync-picker-list");
    if (!select || !button || !list) return;
    // data-picker-label (2026-10-28, Statement Processing's vendor/shop
    // filters): the button shows the picked option and is highlighted while
    // one is picked. Without it the label stays fixed ("Past syncs").
    const label = wrap.hasAttribute("data-picker-label") ? button.querySelector(".picker-label") : null;

    function showSelection() {
      if (!label) return;
      const opt = select.options[select.selectedIndex];
      label.textContent = opt ? opt.text : "";
      button.title = opt ? opt.text : "";
      button.classList.toggle("active", !!select.value);
    }

    function enabledOptions() {
      return Array.from(list.children).filter(function (li) {
        return li.getAttribute("aria-disabled") !== "true";
      });
    }

    function build() {
      list.textContent = "";
      Array.from(select.options).forEach(function (opt, i) {
        // A hidden option is the select's "nothing picked" value, not a list entry.
        if (opt.hidden) return;
        const li = document.createElement("li");
        li.id = list.id + "-" + i;
        li.className = "ns-pop-opt";
        li.setAttribute("role", "option");
        li.tabIndex = -1;
        li.textContent = opt.text;
        li.dataset.value = opt.value;
        li.setAttribute("aria-selected", String(opt.selected && !opt.disabled));
        if (opt.disabled) { li.setAttribute("aria-disabled", "true"); }
        list.appendChild(li);
      });
    }

    function open() {
      build();
      list.hidden = false;
      button.setAttribute("aria-expanded", "true");
      const current = list.querySelector('[aria-selected="true"]') || enabledOptions()[0];
      if (current) { current.focus(); }
    }

    function close(returnFocus) {
      list.hidden = true;
      button.setAttribute("aria-expanded", "false");
      if (returnFocus) { button.focus(); }
    }

    function pick(li) {
      close(true);
      select.value = li.dataset.value;
      showSelection();
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    // The page restores saved filters into the select before this runs.
    showSelection();

    button.addEventListener("click", function () {
      if (list.hidden) { open(); } else { close(false); }
    });
    // Type to jump (2026-10-28), as a native <select> does: letters typed
    // within a second of each other build up a prefix, and the first entry
    // starting with it (case-insensitive) gets focus -- which scrolls it into
    // view. A space continues the prefix ("Gates G"); on its own it picks.
    let typed = "", typedAt = 0;
    function isTypeAhead(ev) {
      if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.key.length !== 1) return false;
      return ev.key !== " " || (typed && Date.now() - typedAt < 1000);
    }
    function jumpTo(ch) {
      const now = Date.now();
      typed = (now - typedAt < 1000 ? typed : "") + ch.toLowerCase();
      typedAt = now;
      const hit = enabledOptions().find(function (li) { return li.textContent.trim().toLowerCase().startsWith(typed); });
      if (hit) { hit.focus(); }
    }

    button.addEventListener("keydown", function (ev) {
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") { ev.preventDefault(); open(); }
      else if (isTypeAhead(ev) && ev.key !== " ") { ev.preventDefault(); open(); jumpTo(ev.key); }
    });
    list.addEventListener("click", function (ev) {
      const li = ev.target.closest('[role="option"]');
      if (li && li.getAttribute("aria-disabled") !== "true") { pick(li); }
    });
    list.addEventListener("keydown", function (ev) {
      const opts = enabledOptions();
      const i = opts.indexOf(document.activeElement);
      if (isTypeAhead(ev)) { ev.preventDefault(); jumpTo(ev.key); return; }
      if (ev.key === "ArrowDown") { ev.preventDefault(); opts[Math.min(i + 1, opts.length - 1)].focus(); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); opts[Math.max(i - 1, 0)].focus(); }
      else if (ev.key === "Home") { ev.preventDefault(); opts[0].focus(); }
      else if (ev.key === "End") { ev.preventDefault(); opts[opts.length - 1].focus(); }
      else if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); if (i >= 0) { pick(opts[i]); } }
      else if (ev.key === "Tab") { close(false); }
    });
    // Escape and outside clicks close it from anywhere, not just from
    // inside the list (e.g. after clicking the list's own padding).
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && !list.hidden) { ev.preventDefault(); close(true); }
    });
    document.addEventListener("click", function (ev) {
      if (!list.hidden && !wrap.contains(ev.target)) { close(false); }
    });
  });
});
