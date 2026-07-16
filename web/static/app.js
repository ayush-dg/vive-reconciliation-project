// Upload page: show the picked file in the file-card, and a full-page
// "Processing..." overlay for the duration of the (synchronous) pipeline
// run triggered by the form's normal submit.
document.addEventListener("DOMContentLoaded", function () {
  const fileInput = document.getElementById("pdf-file-input");
  const fileCard = document.getElementById("file-card");
  const fileName = document.getElementById("file-name");
  const fileSize = document.getElementById("file-size");
  const form = document.getElementById("upload-form");
  const overlay = document.getElementById("processing-overlay");
  const runBtn = document.getElementById("run-btn");

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      const file = fileInput.files[0];
      if (!file) return;
      if (fileCard) fileCard.style.display = "block";
      if (fileName) fileName.textContent = file.name;
      if (fileSize) fileSize.textContent = (file.size / (1024 * 1024)).toFixed(1) + " MB";
      if (runBtn) runBtn.disabled = false;
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
});
