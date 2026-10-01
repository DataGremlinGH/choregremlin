// Kiosk timer - updates elapsed time every second
(function () {
  function fmtElapsed(startedStr) {
    try {
      var started = new Date(startedStr.replace(' ', 'T'));
      if (isNaN(started)) started = new Date(startedStr);
      var now = new Date();
      var diff = Math.floor((now - started) / 1000);
      if (diff < 0) diff = 0;
      var m = Math.floor(diff / 60);
      var s = diff % 60;
      return m + 'm ' + s + 's';
    } catch (e) {
      return '—';
    }
  }

  function updateTimers() {
    document.querySelectorAll('.fh-timer').forEach(function (el) {
      var started = el.getAttribute('data-started');
      if (started) el.textContent = fmtElapsed(started);
    });
  }

  updateTimers();
  setInterval(updateTimers, 1000);
})();
