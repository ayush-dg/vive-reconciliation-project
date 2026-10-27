// List-page filters that survive leaving the page (2026-10-27).
//
// Home, Exceptions and Statement Processing reset to their defaults whenever
// you came back through a plain link (the sidebar, a breadcrumb, "← Statement
// Processing"): Home's filters lived only in the address, the other two only
// in the page. Now each page keeps its filters in the address AND remembers
// them for this browser tab (sessionStorage), and coming back to the plain
// address from ANOTHER page brings them back. Clicking a control on the same
// page (e.g. Home's "Last run" chip, which links to plain "/") is a real
// choice and is never overridden. Loaded in <head>, before the pages' own
// scripts. Storage can be unavailable (private mode): everything still works,
// it just isn't remembered.
window.ViveFilters = (function () {
  function key() { return "vive-filters:" + location.pathname; }

  function read() {
    try { return sessionStorage.getItem(key()); } catch (e) { return null; }
  }

  function write(query) {
    try { sessionStorage.setItem(key(), query || ""); } catch (e) { /* not remembered */ }
  }

  function cameFromThisPage() {
    try {
      return !!document.referrer && new URL(document.referrer).pathname === location.pathname;
    } catch (e) { return false; }
  }

  // Call first thing on the page. `server`: the server renders from the
  // address (Home, Exceptions' time window), so restoring means reloading
  // with the remembered address; else the address is just rewritten.
  // Returns the values to start from for `names` (the page's own controls),
  // or null when the page is about to reload.
  function init(names, server) {
    var saved = read();
    if (!location.search && saved && !cameFromThisPage()) {
      if (server) {
        location.replace(location.pathname + saved + location.hash);
        return null;
      }
      history.replaceState(null, "", location.pathname + saved + location.hash);
    }
    var fromUrl = new URLSearchParams(location.search);
    var fallback = new URLSearchParams(read() || "");
    var values = {};
    (names || []).forEach(function (name) {
      // The address wins; a control the address doesn't mention keeps its
      // remembered value (e.g. a time-window chip link carries no vendor).
      values[name] = fromUrl.has(name) ? fromUrl.get(name) : (fallback.get(name) || "");
    });
    if (!names || !names.length) { write(location.search); }
    return values;
  }

  // Puts the page's own control values into the address and remembers it.
  function save(values) {
    var params = new URLSearchParams(location.search);
    Object.keys(values || {}).forEach(function (name) {
      if (values[name]) { params.set(name, values[name]); } else { params.delete(name); }
    });
    var query = params.toString() ? "?" + params.toString() : "";
    history.replaceState(null, "", location.pathname + query + location.hash);
    write(query);
  }

  // "Reset filters": forget them and load the page's defaults.
  function reset() {
    try { sessionStorage.removeItem(key()); } catch (e) { /* nothing to forget */ }
    location.href = location.pathname;
  }

  return { init: init, save: save, reset: reset };
})();
