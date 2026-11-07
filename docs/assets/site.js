// Subline website: the latest release's files on the download buttons, the
// settings-window tabs, and a still demo for people who ask for less motion.
// Everything works without this script; it only makes the links direct.

(function () {
  "use strict";

  var REPO = "mustafayurdakul/subline";

  function megabytes(bytes) {
    return Math.round(bytes / 1e6) + " MB";
  }

  function setText(name, text) {
    document.querySelectorAll('[data-release="' + name + '"]').forEach(function (el) {
      el.textContent = text;
    });
  }

  // The release page is the links' fallback; with the API's answer they point
  // at the files themselves.
  function loadRelease() {
    if (!window.fetch) return;
    fetch("https://api.github.com/repos/" + REPO + "/releases/latest", {
      headers: { Accept: "application/vnd.github+json" },
    })
      .then(function (response) {
        if (!response.ok) throw new Error(response.status);
        return response.json();
      })
      .then(function (release) {
        var assets = release.assets || [];
        var setup = assets.find(function (a) { return /-setup\.exe$/i.test(a.name); });
        var zip = assets.find(function (a) { return /\.zip$/i.test(a.name); });
        var version = (release.tag_name || "").replace(/^v/, "");
        if (version) setText("version", "Version " + version);
        if (setup) {
          document.querySelectorAll('[data-asset="setup"]').forEach(function (a) { a.href = setup.browser_download_url; });
          setText("hero", (version ? "v" + version + " \u00b7 " : "") + megabytes(setup.size) + " \u00b7 ");
          setText("setup-file", setup.name + " \u00b7 " + megabytes(setup.size));
        }
        if (zip) {
          document.querySelectorAll('[data-asset="zip"]').forEach(function (a) { a.href = zip.browser_download_url; });
          setText("zip-file", zip.name + " \u00b7 " + megabytes(zip.size));
        }
      })
      .catch(function () { /* keep the links to the release page */ });
  }

  function setUpTabs() {
    var tabs = Array.prototype.slice.call(document.querySelectorAll('.tabs [role="tab"]'));
    var image = document.getElementById("tour-img");
    var caption = document.getElementById("tour-caption");
    var panel = document.getElementById("panel-tour");
    if (!tabs.length || !image) return;

    function select(tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
      });
      image.src = tab.dataset.src;
      image.alt = tab.dataset.alt;
      caption.textContent = tab.dataset.caption;
      panel.setAttribute("aria-labelledby", tab.id);
      if (focus) tab.focus();
    }

    tabs.forEach(function (tab, index) {
      tab.addEventListener("click", function () { select(tab, false); });
      tab.addEventListener("keydown", function (event) {
        var next = null;
        if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
        else if (event.key === "ArrowLeft") next = tabs[(index - 1 + tabs.length) % tabs.length];
        else if (event.key === "Home") next = tabs[0];
        else if (event.key === "End") next = tabs[tabs.length - 1];
        if (next) {
          event.preventDefault();
          select(next, true);
        }
      });
    });

    // Fetch the other pages' images once the first is shown.
    window.addEventListener("load", function () {
      tabs.forEach(function (tab) { new Image().src = tab.dataset.src; });
    });
  }

  function respectReducedMotion() {
    var video = document.querySelector(".demo__video");
    if (!video || !window.matchMedia) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      video.removeAttribute("autoplay");
      video.pause();
      video.controls = true;
    }
  }

  respectReducedMotion();
  setUpTabs();
  loadRelease();
})();
