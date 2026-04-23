// ── GIK Timetable Scheduler — UI Interactions ──────────────────────────────

document.addEventListener("DOMContentLoaded", function () {
    // Loading spinner on Generate button
    const genBtn = document.getElementById("generateBtn");
    if (genBtn) {
        genBtn.addEventListener("click", function () {
            genBtn.innerHTML =
                '<span class="spinner-border spinner-border-sm me-1"></span> Generating…';
            genBtn.disabled = true;
            // Allow the form to submit
            genBtn.closest("form").submit();
        });
    }

    // Auto-dismiss flash alerts after 5 seconds
    document.querySelectorAll(".alert-dismissible").forEach(function (alert) {
        setTimeout(function () {
            var bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });

    // Highlight active nav link
    const currentPath = window.location.pathname;
    document.querySelectorAll(".nav-link").forEach(function (link) {
        if (link.getAttribute("href") === currentPath) {
            link.classList.add("active", "fw-bold");
        }
    });
});
