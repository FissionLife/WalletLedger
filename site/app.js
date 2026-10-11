/*
  WalletLedger landing page: the only JavaScript on the site.

  EDIT LINKS HERE. These two URLs are the single source of truth for the page:
  every element with data-link="bot" / data-link="repo" gets its href from here, and every
  data-repo-path="docs/SECURITY.md" link becomes <repo>/blob/<branch>/<path>.
  (The hrefs written in index.html are only fallbacks for visitors with JavaScript turned off.)
*/
const SITE = {
  botUrl: "https://t.me/Fissionlabsbot",
  repoUrl: "https://github.com/FissionLife/WalletLedger",
  branch: "main",
};

(function () {
  "use strict";

  // 1. Links from the config above.
  document.querySelectorAll('[data-link="bot"]').forEach(function (a) {
    a.href = SITE.botUrl;
  });
  document.querySelectorAll('[data-link="repo"]').forEach(function (a) {
    a.href = SITE.repoUrl;
  });
  document.querySelectorAll("[data-repo-path]").forEach(function (a) {
    a.href = SITE.repoUrl + "/blob/" + SITE.branch + "/" + a.getAttribute("data-repo-path");
  });

  // 2. Light / dark theme toggle. The choice is remembered in this browser only.
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function currentTheme() {
    var set = root.getAttribute("data-theme");
    if (set === "light" || set === "dark") return set;
    return media && media.matches ? "dark" : "light";
  }

  function syncThemeColor() {
    // Keep the mobile browser bar colour in step with a manual choice.
    var colour = currentTheme() === "dark" ? "#0f0f0f" : "#ffffff";
    document.querySelectorAll('meta[name="theme-color"]').forEach(function (m) {
      m.setAttribute("content", colour);
    });
  }

  var themeButton = document.querySelector(".theme-toggle");
  if (themeButton) {
    themeButton.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try {
        localStorage.setItem("wl-theme", next);
      } catch (e) {
        /* storage blocked (private mode etc.): the toggle still works for this visit */
      }
      syncThemeColor();
    });
  }
  if (root.hasAttribute("data-theme")) syncThemeColor();

  // 3. Mobile menu.
  var menuButton = document.querySelector(".menu-toggle");
  var mobileNav = document.getElementById("mobile-nav");

  function setMenu(open) {
    if (!menuButton || !mobileNav) return;
    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    mobileNav.hidden = !open;
    mobileNav.classList.toggle("is-open", open);
  }

  if (menuButton && mobileNav) {
    menuButton.addEventListener("click", function () {
      setMenu(menuButton.getAttribute("aria-expanded") !== "true");
    });
    mobileNav.addEventListener("click", function (e) {
      if (e.target.closest("a")) setMenu(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && menuButton.getAttribute("aria-expanded") === "true") {
        setMenu(false);
        menuButton.focus();
      }
    });
  }

  // 4. Copy-to-clipboard buttons on the setup commands.
  var status = document.getElementById("copy-status");

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      // If the browser refuses (permissions), try the older method below.
      return navigator.clipboard.writeText(text).catch(function () {
        return legacyCopy(text);
      });
    }
    return legacyCopy(text);
  }

  // Fallback for older browsers / plain http.
  function legacyCopy(text) {
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (e) {
        ok = false;
      }
      document.body.removeChild(area);
      if (ok) resolve();
      else reject(new Error("copy failed"));
    });
  }

  function flash(button, message) {
    var label = button.querySelector("span");
    var original = label ? label.textContent : "";
    if (label) label.textContent = message;
    button.classList.toggle("is-copied", message === "Copied");
    if (status) status.textContent = message === "Copied" ? "Copied to clipboard" : "Could not copy";
    setTimeout(function () {
      if (label) label.textContent = original;
      button.classList.remove("is-copied");
    }, 1600);
  }

  document.querySelectorAll(".copy-btn").forEach(function (button) {
    button.addEventListener("click", function () {
      var text;
      if (button.hasAttribute("data-copy-all")) {
        var lines = [];
        document.querySelectorAll(".cmd-row code").forEach(function (c) {
          lines.push(c.textContent.trim());
        });
        text = lines.join("\n");
      } else {
        var code = button.closest(".cmd-row").querySelector("code");
        text = code ? code.textContent.trim() : "";
      }
      copyText(text).then(
        function () { flash(button, "Copied"); },
        function () { flash(button, "Press Ctrl+C"); }
      );
    });
  });
})();
