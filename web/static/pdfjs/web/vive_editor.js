/* vive_editor.js -- the app's additions to the stock PDF.js 4.10.38 viewer
   (web/static/pdfjs, otherwise unmodified apart from two tags in viewer.html).

   Opened by GET /statements/<id>/<name>.pdf?edit=1 (web/routers/statements.py)
   as viewer.html?file=<pdf>&vive_sid=<statement id>&vive_etag=<SharePoint eTag>.

   - Viewer options: no preferences from localStorage, no PDF scripting, no
     sample file.
   - Tools: highlight, text and draw (the stamp/image tool is hidden in
     vive_editor.css).
   - "Save to SharePoint": PDF.js writes the annotations into the file
     (saveDocument) and it is POSTed to /statements/<id>/pdf with If-Match:
     <eTag>. The server replaces the SharePoint file only if nobody saved
     since; the new eTag is kept for the next save. */
(function () {
  "use strict";

  var params = new URLSearchParams(window.location.search);
  var statementId = params.get("vive_sid");
  var etag = params.get("vive_etag");

  // The viewer announces itself on parent.document -- the app page when it sits
  // in the PDF panel's iframe -- so listen there, for this frame only.
  function onViewerLoaded(event) {
    if (event.detail && event.detail.source && event.detail.source !== window) { return; }
    var options = window.PDFViewerApplicationOptions;
    options.set("disablePreferences", true);
    options.set("enableScripting", false);
    options.set("defaultUrl", "");
  }
  var target = document;
  try { target = window.parent.document; } catch (e) { target = document; }
  target.addEventListener("webviewerloaded", onViewerLoaded);
  if (target !== document) { document.addEventListener("webviewerloaded", onViewerLoaded); }

  if (!statementId || !etag) { return; }   // a plain view: no Save button

  var button, status, saving = false;

  function setStatus(text, isError) {
    status.textContent = text || "";
    status.classList.toggle("vive-error", Boolean(isError));
  }

  // Unsaved edits: the viewer's own flag (set by annotationStorage.onSetModified,
  // cleared by resetModified()) -- the same one behind its "leave page?" warning.
  function hasUnsavedEdits() {
    var app = window.PDFViewerApplication;
    return Boolean(app && app.pdfDocument && app._annotationStorageModified);
  }

  function refresh() {
    button.disabled = saving || !hasUnsavedEdits();
  }

  async function save() {
    var app = window.PDFViewerApplication;
    if (!app || !app.pdfDocument || saving) { return; }
    saving = true;
    refresh();
    setStatus("Saving…");
    try {
      var data = await app.pdfDocument.saveDocument();
      var response = await fetch("/statements/" + encodeURIComponent(statementId) + "/pdf", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/pdf", "If-Match": etag },
        body: data
      });
      if (response.redirected && /\/login/.test(response.url)) {
        setStatus("Your session has ended. Log in again in another tab, then Save.", true);
        return;
      }
      var result = {};
      try { result = await response.json(); } catch (e) { result = {}; }
      if (response.ok && result.saved) {
        etag = result.etag;
        app.pdfDocument.annotationStorage.resetModified();
        setStatus("Saved to SharePoint");
      } else {
        setStatus(result.error || ("Save failed (HTTP " + response.status + "). Nothing was saved."), true);
      }
    } catch (e) {
      setStatus("Save failed: " + (e && e.message ? e.message : e) + ". Nothing was saved.", true);
    } finally {
      saving = false;
      refresh();
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var anchor = document.getElementById("editorModeSeparator");
    if (!anchor) { return; }
    button = document.createElement("button");
    button.id = "viveSaveButton";
    button.type = "button";
    button.className = "vive-save";
    button.textContent = "Save to SharePoint";
    button.title = "Save your highlights, text and drawings into the statement's SharePoint file";
    button.disabled = true;
    button.addEventListener("click", save);
    status = document.createElement("span");
    status.id = "viveSaveStatus";
    status.className = "vive-status";
    status.setAttribute("role", "status");
    anchor.parentNode.insertBefore(status, anchor);
    anchor.parentNode.insertBefore(button, status);
    window.setInterval(function () {
      refresh();
      if (hasUnsavedEdits() && status.textContent === "Saved to SharePoint") { setStatus(""); }
    }, 700);
  });
})();
