// Responsive PIN entry controller.
//
// Touch / narrow screens use the on-screen keypad. Wider screens with a fine
// pointer use the masked numeric input, but the document-level keyboard
// handler keeps physical keyboards (including Bluetooth keyboards attached to
// tablets) working everywhere.
(function () {
  'use strict';

  var form = document.getElementById('pinForm');
  if (!form) return;

  var input = form.querySelector('#pinInput');
  var display = form.querySelector('#pinDisplay');
  if (!input || !display) return;

  var minDigits = parseInt(form.getAttribute('data-pin-min'), 10) || 1;
  var maxDigits = parseInt(form.getAttribute('data-pin-max'), 10) || 64;
  var minDots = parseInt(form.getAttribute('data-pin-min-dots'), 10) || Math.min(minDigits, 4);
  var maxDots = parseInt(form.getAttribute('data-pin-max-dots'), 10) || 12;
  var username = document.getElementById('loginUsername');
  var desktopQuery = window.matchMedia
    ? window.matchMedia('(min-width: 769px) and (pointer: fine)')
    : null;

  input.setAttribute('maxlength', String(maxDigits));
  input.setAttribute('pattern', '[0-9]*');
  input.setAttribute('inputmode', 'numeric');

  function isDesktop() {
    return !!(desktopQuery && desktopQuery.matches);
  }

  function digitsOnly(value) {
    return String(value || '').replace(/\D+/g, '').slice(0, maxDigits);
  }

  function currentPin() {
    return digitsOnly(input.value);
  }

  function renderDots() {
    var pin = currentPin();
    var shown = Math.max(minDots, Math.min(pin.length, maxDots));
    display.innerHTML = '';
    for (var i = 0; i < shown; i += 1) {
      var dot = document.createElement('span');
      dot.className = 'fh-pin-dot' + (i < pin.length ? ' fh-pin-dot-filled' : '');
      display.appendChild(dot);
    }
    display.setAttribute('data-length', String(pin.length));
    display.setAttribute(
      'aria-label',
      pin.length + (pin.length === 1 ? ' digit entered' : ' digits entered')
    );
  }

  function setPin(value) {
    var next = digitsOnly(value);
    if (input.value !== next) input.value = next;
    renderDots();
  }

  function appendDigit(digit) {
    var pin = currentPin();
    if (pin.length >= maxDigits) return;
    setPin(pin + digit);
  }

  function backspace() {
    var pin = currentPin();
    if (!pin.length) return;
    setPin(pin.slice(0, -1));
  }

  function clearPin() {
    setPin('');
  }

  function focusPin() {
    if (!isDesktop()) return;
    try {
      input.focus({ preventScroll: true });
    } catch (err) {
      input.focus();
    }
    var end = input.value.length;
    try {
      input.setSelectionRange(end, end);
    } catch (err) {
      // Some browsers refuse selection changes on password inputs.
    }
  }

  function focusFirstField() {
    if (!isDesktop()) return;
    if (username && !username.value.trim()) {
      username.focus();
    } else {
      focusPin();
    }
  }

  function submitPin() {
    var pin = currentPin();
    if (pin.length < minDigits) {
      form.classList.remove('fh-pin-error');
      // Force a reflow so the shake animation can replay.
      void form.offsetWidth;
      form.classList.add('fh-pin-error');
      focusPin();
      return;
    }
    form.classList.remove('fh-pin-error');
    if (typeof form.requestSubmit === 'function') {
      form.requestSubmit();
    } else {
      form.submit();
    }
  }

  form.addEventListener('click', function (event) {
    var target = event.target;
    var button = target && target.closest ? target.closest('[data-key]') : null;
    if (!button || !form.contains(button)) return;

    var key = button.getAttribute('data-key');
    if (/^\d$/.test(key)) {
      appendDigit(key);
    } else if (key === 'backspace') {
      backspace();
    } else if (key === 'clear') {
      clearPin();
    } else if (key === 'go') {
      submitPin();
    }
  });

  form.addEventListener('animationend', function () {
    form.classList.remove('fh-pin-error');
  });

  input.addEventListener('input', function () {
    var sanitized = digitsOnly(input.value);
    if (input.value !== sanitized) input.value = sanitized;
    renderDots();
  });

  input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      submitPin();
    }
  });

  if (username) {
    username.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      if (isDesktop()) {
        focusPin();
      } else {
        // Drop focus so physical-keyboard digits are captured by the
        // document handler instead of being typed into the username field.
        username.blur();
      }
    });
  }

  document.addEventListener('keydown', function (event) {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;

    var target = event.target;
    var tag = target && target.tagName ? target.tagName.toLowerCase() : '';
    var isField = tag === 'input' || tag === 'textarea' || tag === 'select' ||
      (target && target.isContentEditable);

    if (target === input) {
      // Let the input handle digits and Backspace natively; its input event
      // keeps the dots in sync. Enter submits through our validation.
      if (event.key === 'Enter') {
        event.preventDefault();
        submitPin();
      }
      return;
    }
    if (isField) return;

    if (/^\d$/.test(event.key)) {
      event.preventDefault();
      appendDigit(event.key);
    } else if (event.key === 'Backspace') {
      event.preventDefault();
      backspace();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      submitPin();
    }
  });

  function handleLayoutChange() {
    if (isDesktop()) {
      if (currentPin() || !username || username.value.trim()) focusPin();
    } else if (document.activeElement === input) {
      input.blur();
    }
    renderDots();
  }

  if (desktopQuery) {
    if (desktopQuery.addEventListener) {
      desktopQuery.addEventListener('change', handleLayoutChange);
    } else if (desktopQuery.addListener) {
      desktopQuery.addListener(handleLayoutChange);
    }
  }

  setPin(input.value);
  focusFirstField();
})();
