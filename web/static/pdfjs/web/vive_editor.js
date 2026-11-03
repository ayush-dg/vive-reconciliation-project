/* vive_editor.js -- the app's additions to the stock PDF.js 5.7.284 viewer
   (web/static/pdfjs, otherwise unmodified apart from two tags in viewer.html).

   Opened by GET /statements/<id>/<name>.pdf?edit=1 (web/routers/statements.py)
   as viewer.html?file=<pdf>&vive_sid=<statement id>&vive_etag=<SharePoint eTag>.

   - Viewer options: no preferences from localStorage, no PDF scripting, no
     sample file.
   - Tools: highlight, text and draw, and comments: select text and a floating
     "Comment" / "Highlight" button appears; a comment is a highlight with a
     hidden note (a standard PDF popup, so Acrobat/Edge/SharePoint show it
     too), listed in the comments sidebar. The stamp/image tool is hidden in
     vive_editor.css. Opening the comments sidebar puts existing comments in
     edit mode, which PDF.js counts as a change (Save lights up; saving
     rewrites the same comments).
   - "Reset": POST /statements/<id>/pdf/reset puts the SharePoint file back to
     the PDF as it arrived (all edits gone; the edited version stays in
     SharePoint's history), then the editor reopens.
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
    options.set("enableComment", true);
    options.set("enableHighlightFloatingButton", true);
  }
  var target = document;
  try { target = window.parent.document; } catch (e) { target = document; }
  target.addEventListener("webviewerloaded", onViewerLoaded);
  if (target !== document) { document.addEventListener("webviewerloaded", onViewerLoaded); }

  // PDF.js 5.x asks "Leave page?" whenever the document holds any marks, saved
  // or not -- so after a Save or a Reset, moving to the next statement still
  // asked. Registered before the viewer's own handler, this lets the warning
  // through only when there really are unsaved changes.
  window.addEventListener("beforeunload", function (event) {
    var app = window.PDFViewerApplication;
    if (!(app && app._annotationStorageModified)) { event.stopImmediatePropagation(); }
  }, true);

  // A comment lives on its highlight, so PDF.js's "Remove comment" left the
  // yellow mark behind. Removing (or emptying) the comment of a highlight now
  // removes the highlight itself, through PDF.js's own delete -- undo bar
  // "Highlight removed -- Undo" brings back the highlight with its comment.
  // Comments on text boxes and drawings keep the stock behaviour; plain
  // highlights (never commented) are untouched.
  //
  // Every way a comment is cleared ends in the editor's comment setter calling
  // uiManager.removeComment(editor) (the popup's Remove, an emptied edit, the
  // stock deleteComment), so that is the hook. The comment is remembered as it
  // is set (updateComment) and put back just before the delete, so undo
  // restores it too. Patched once per document, once the manager exists.
  // Select the editor, then delete it once PDF.js has finished building its
  // little toolbar (selecting builds it asynchronously; deleting mid-build made
  // PDF.js throw on the half-built toolbar).
  function selectAndDelete(ui, editor, then) {
    ui.setSelected(editor);
    var tries = 0;
    (function attempt() {
      var built = editor._editToolbar && editor.div && editor.div.querySelector(".deleteButton");
      if (!built && ++tries < 40) { window.setTimeout(attempt, 25); return; }
      ui.delete();
      if (then) { then(); }
    })();
  }

  function patchCommentDelete() {
    var app = window.PDFViewerApplication;
    var ui = app && app.pdfViewer && app.pdfViewer._layerProperties &&
             app.pdfViewer._layerProperties.annotationEditorUIManager;
    if (!ui || ui.__viveCommentDelete || typeof ui.removeComment !== "function" ||
        typeof ui.updateComment !== "function" || typeof ui.delete !== "function") { return; }
    var lastComment = new WeakMap();
    var stockUpdate = ui.updateComment.bind(ui);
    ui.updateComment = function (editor) {
      try { if (editor && editor.comment && editor.comment.text) { lastComment.set(editor, editor.comment); } } catch (e) {}
      return stockUpdate.apply(ui, arguments);
    };
    var stockRemove = ui.removeComment.bind(ui);
    ui.removeComment = function (editor) {
      var result = stockRemove.apply(ui, arguments);
      if (editor && editor.editorType === "highlight") {
        window.setTimeout(function () {
          if (!editor.div || !editor.div.isConnected) { return; }   // already deleted
          var saved = lastComment.get(editor);
          if (saved) { editor.comment = saved; }   // so undo brings the comment back too
          selectAndDelete(ui, editor);
        }, 0);
      }
      return result;
    };
    ui.__viveCommentDelete = true;
  }

  // A comment already saved in the PDF is not an editor: its Remove only
  // stores {popup: {deleted: true}} for that annotation id. For a saved
  // highlight, switch to highlight mode (which turns saved highlights into
  // editors), delete that editor with PDF.js's own delete -- same undo bar --
  // and go back to no tool.
  var HIGHLIGHT = 9;
  function findEditorFor(ui, annotationId) {
    var app = window.PDFViewerApplication;
    for (var page = 0; page < (app.pagesCount || 0); page++) {
      var editors = ui.getEditors(page);
      for (var step = editors.next(); !step.done; step = editors.next()) {
        if (step.value.annotationElementId === annotationId) { return step.value; }
      }
    }
    return null;
  }
  function deleteSavedHighlight(annotationId, storageKey) {
    var app = window.PDFViewerApplication;
    var ui = app.pdfViewer._layerProperties.annotationEditorUIManager;
    var wasNoTool = app.pdfViewer.annotationEditorMode === 0;
    if (wasNoTool) { app.eventBus.dispatch("switchannotationeditormode", { source: window, mode: HIGHLIGHT }); }
    var tries = 0;
    (function attempt() {
      var editor = findEditorFor(ui, annotationId);
      if (!editor) {
        if (++tries < 60) { window.setTimeout(attempt, 50); } else if (wasNoTool) { noTool(); }
        return;
      }
      // The deletion replaces the "comment removed" entry; without it, undo
      // brings the highlight back with its comment.
      try { app.pdfDocument.annotationStorage.remove(storageKey); } catch (e) {}
      selectAndDelete(ui, editor, function () { if (wasNoTool) { window.setTimeout(noTool, 50); } });
    })();
  }
  function patchSavedCommentDelete() {
    var app = window.PDFViewerApplication;
    var storage = app && app.pdfDocument && app.pdfDocument.annotationStorage;
    if (!storage || storage.__viveCommentDelete || typeof storage.setValue !== "function") { return; }
    var stockSet = storage.setValue.bind(storage);
    storage.setValue = function (key, value) {
      var result = stockSet.apply(storage, arguments);
      if (value && !value.annotationEditorType && value.annotationType === HIGHLIGHT &&
          value.popup && value.popup.deleted && value.id) {
        window.setTimeout(function () { deleteSavedHighlight(value.id, key); }, 0);
      }
      return result;
    };
    storage.__viveCommentDelete = true;
  }
  window.setInterval(function () { patchCommentDelete(); patchSavedCommentDelete(); }, 500);

  // The floating "Comment" / "Highlight" buttons (shown on a text selection)
  // switch the viewer into highlight mode to create the highlight and leave it
  // there -- the mouse stays a highlighter pen. When it was in no tool before,
  // go back to no tool once the highlight (and its comment) is done. Choosing
  // the Highlight tool from the toolbar is not affected.
  function noTool() {
    var app = window.PDFViewerApplication;
    if (app && app.pdfViewer && app.pdfViewer.annotationEditorMode !== 0) {
      app.eventBus.dispatch("switchannotationeditormode", { source: window, mode: 0 });
    }
  }
  document.addEventListener("click", function (event) {
    var button = event.target && event.target.closest &&
      event.target.closest('.editToolbar button[data-l10n-id^="pdfjs-comment-floating-button"],' +
                           '.editToolbar button[data-l10n-id^="pdfjs-highlight-floating-button"]');
    var app = window.PDFViewerApplication;
    if (!button || !app || !app.pdfViewer || app.pdfViewer.annotationEditorMode !== 0) { return; }
    var dialog = document.getElementById("commentManagerDialog");
    if (/comment/.test(button.getAttribute("data-l10n-id")) && dialog) {
      dialog.addEventListener("close", function () { window.setTimeout(noTool, 50); }, { once: true });
    } else {
      window.setTimeout(noTool, 400);   // after PDF.js has switched modes and added the highlight
    }
  }, true);

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

  // Reset: put the statement back exactly as it arrived (every comment and mark
  // removed). The server refuses if someone saved since this was opened; the
  // edited version stays in SharePoint's version history. Then reopen the
  // editor on the new version.
  async function reset() {
    var app = window.PDFViewerApplication;
    if (saving) { return; }
    var question = "Remove all comments, highlights, text and drawings from this statement and put it back " +
      "exactly as it arrived?\n\nThe edited version stays in SharePoint's version history.";
    if (hasUnsavedEdits()) { question += "\n\nYour unsaved changes will be lost too."; }
    if (!window.confirm(question)) { return; }
    saving = true;
    refresh();
    setStatus("Resetting…");
    try {
      var response = await fetch("/statements/" + encodeURIComponent(statementId) + "/pdf/reset", {
        method: "POST", credentials: "same-origin", headers: { "If-Match": etag }
      });
      if (response.redirected && /\/login/.test(response.url)) {
        setStatus("Your session has ended. Log in again in another tab, then Reset.", true);
        return;
      }
      var result = {};
      try { result = await response.json(); } catch (e) { result = {}; }
      if (response.ok && result.reset) {
        if (app && app.pdfDocument) { app.pdfDocument.annotationStorage.resetModified(); }
        setStatus("Reset to the original. Reopening…");
        window.location.href = params.get("file") + "?edit=1";
        return;
      }
      setStatus(result.error || ("Reset failed (HTTP " + response.status + "). Nothing was changed."), true);
    } catch (e) {
      setStatus("Reset failed: " + (e && e.message ? e.message : e) + ". Nothing was changed.", true);
    } finally {
      saving = false;
      refresh();
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var anchor = document.getElementById("editorModeSeparator");
    if (!anchor) { return; }
    var resetButton = document.createElement("button");
    resetButton.id = "viveResetButton";
    resetButton.type = "button";
    resetButton.className = "vive-reset";
    resetButton.textContent = "Reset";
    resetButton.title = "Remove all comments and marks: put the statement back exactly as it arrived";
    resetButton.addEventListener("click", reset);
    button = document.createElement("button");
    button.id = "viveSaveButton";
    button.type = "button";
    button.className = "vive-save";
    // Two labels; vive_editor.css shows the short one when the viewer is narrow (the PDF panel).
    button.innerHTML = '<span class="vive-long">Save to SharePoint</span><span class="vive-short">Save</span>';
    button.title = "Save your comments, highlights, text and drawings into the statement's SharePoint file";
    button.disabled = true;
    button.addEventListener("click", save);
    status = document.createElement("span");
    status.id = "viveSaveStatus";
    status.className = "vive-status";
    status.setAttribute("role", "status");
    anchor.parentNode.insertBefore(status, anchor);
    anchor.parentNode.insertBefore(button, status);
    anchor.parentNode.insertBefore(resetButton, status);
    window.setInterval(function () {
      refresh();
      if (hasUnsavedEdits() && status.textContent === "Saved to SharePoint") { setStatus(""); }
    }, 700);
  });
})();
