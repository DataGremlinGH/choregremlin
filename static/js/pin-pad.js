// PIN Pad controller
(function () {
  var input = document.getElementById('pinInput');
  var display = document.getElementById('pinDisplay');
  var dots = display ? display.querySelectorAll('.fh-pin-dot') : [];
  var keys = document.querySelectorAll('.fh-pin-key');
  var form = document.getElementById('pinForm');
  var pin = '';

  function updateDots() {
    if (!display) return;
    var shown = Math.min(Math.max(pin.length, 4), 12);
    display.innerHTML = '';
    for (var i = 0; i < shown; i++) {
      var dot = document.createElement('span');
      dot.className = 'fh-pin-dot' + (i < pin.length ? ' fh-pin-dot-filled' : '');
      display.appendChild(dot);
    }
  }

  function submit() {
    if (pin.length < 1) return;
    input.value = pin;
    if (typeof form.requestSubmit === 'function') form.requestSubmit();
    else form.submit();
  }

  keys.forEach(function (key) {
    key.addEventListener('click', function () {
      var k = this.getAttribute('data-key');
      if (k === 'clear') {
        pin = '';
      } else if (k === 'go') {
        submit();
      } else if (pin.length < 64) {
        pin += k;
      }
      updateDots();
    });
  });
})();
