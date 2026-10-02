// Kiosk timer - updates elapsed time every second
(function () {
  function fmtElapsed(startedStr) {
    try {
      var started = new Date(startedStr.replace(' ', 'T') + 'Z');
      if (isNaN(started)) {
        started = new Date(startedStr);
        if (isNaN(started)) return '0m 0s';
      }
      var now = new Date();
      var diff = Math.floor((now - started) / 1000);
      if (diff < 0) diff = 0;
      var m = Math.floor(diff / 60);
      var s = diff % 60;
      return m + 'm ' + s + 's';
    } catch (e) {
      return '0m 0s';
    }
  }

  function updateTimers() {
    document.querySelectorAll('.fh-timer').forEach(function (el) {
      var container = el.closest('[data-started]');
      if (container) {
        var started = container.getAttribute('data-started');
        if (started) el.textContent = fmtElapsed(started);
      }
    });
  }

  updateTimers();
  setInterval(updateTimers, 1000);
})();
