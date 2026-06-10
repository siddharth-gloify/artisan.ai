// PostForge — global JS (shared between index and editor pages)

// Highlight selected cards on load if a value is pre-set (e.g. after browser back)
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".select-card input[type='radio']:checked, .palette-card input[type='radio']:checked").forEach(input => {
    input.closest("[data-group]")?.classList.add("selected");
  });
});
