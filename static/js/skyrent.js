/* SkyRent global behaviour: navigation, alerts and small progressive enhancements. */
(function () {
  "use strict";

  // Auto-dismiss flash messages after a few seconds.
  document.querySelectorAll(".alert[data-auto-dismiss]").forEach(function (alert) {
    window.setTimeout(function () {
      if (!window.bootstrap) return;
      window.bootstrap.Alert.getOrCreateInstance(alert).close();
    }, 6000);
  });

  var nav = document.getElementById("mainNav");
  var toggle = document.querySelector(".nav-toggle");
  if (nav && window.bootstrap) {
    var collapse = window.bootstrap.Collapse.getOrCreateInstance(nav, { toggle: false });

    function syncToggle(expanded) {
      if (!toggle) return;
      toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
      toggle.setAttribute(
        "aria-label",
        expanded ? "Close navigation menu" : "Open navigation menu"
      );
    }

    nav.addEventListener("show.bs.collapse", function () { syncToggle(true); });
    nav.addEventListener("hide.bs.collapse", function () { syncToggle(false); });

    // Close the mobile menu after navigating to another page or anchor, and
    // after choosing an account action.
    nav.querySelectorAll("a:not(.dropdown-toggle), .dropdown-item").forEach(function (link) {
      link.addEventListener("click", function () {
        if (nav.classList.contains("show")) collapse.hide();
      });
    });

    // Close when clicking outside the open mobile panel.
    document.addEventListener("click", function (event) {
      if (!nav.classList.contains("show")) return;
      if (nav.contains(event.target) || (toggle && toggle.contains(event.target))) return;
      collapse.hide();
    });

    // Escape closes the mobile menu and returns focus to the toggle.
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.classList.contains("show")) {
        collapse.hide();
        if (toggle) toggle.focus();
      }
    });
  }

  // Mark images as loaded once decoded so their surrounding placeholder can
  // settle without a flash of empty space.
  document.querySelectorAll(".car-media img").forEach(function (image) {
    if (image.complete) {
      image.classList.add("is-loaded");
    } else {
      image.addEventListener("load", function () { image.classList.add("is-loaded"); });
    }
  });
})();
