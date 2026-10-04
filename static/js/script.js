// Mobile menu toggle
document.getElementById("menuBtn").addEventListener("click", function () {
  document.getElementById("nav").classList.toggle("open");
});
// Confirmation before dangerous actions (forms with data-confirm="message")
document.querySelectorAll("form[data-confirm]").forEach(function (f) {
  f.addEventListener("submit", function (e) {
    if (!confirm(f.dataset.confirm)) e.preventDefault();
  });
});
// Hide success messages after 4 seconds
setTimeout(function () {
  document.querySelectorAll(".flash.success").forEach(function (el) { el.style.display = "none"; });
}, 4000);
