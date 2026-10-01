// PIN Pad controller
(function () {
  var input = document.getElementById('pinInput');
  var display = document.getElementById('pinDisplay');
  var dots = display ? display.querySelectorAll('.fh-pin-dot') : [];
  var keys = document.querySelectorAll('.fh-pin-key');
  var form = document.getElementById('pinForm');
  var pin = '';

  function updateDots() {
    dots.forEach(function (dot, i) {
      if (i < pin.length) dot.classList.add('fh-pin-dot-filled');
      else dot.classList.remove('fh-pin-dot-filled');
    });
  }

  function submit() {
    if (pin.length < 1) return;
    input.value = pin;
    form.submit();
  }

  keys.forEach(function (key) {
    key.addEventListener('click', function () {
      var k = this.getAttribute('data-key');
      if (k === 'clear') {
        pin = '';
      } else if (k === 'go') {
        submit();
      } else if (pin.length < 6) {
        pin += k;
      }
      updateDots();
    });
  });
})();
