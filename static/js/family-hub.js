// Family Hub - Main JS

// Register service worker for PWA
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}

// Prevent double-tap zoom on iOS
let lastTouch = 0;
document.addEventListener('touchend', (e) => {
  const now = Date.now();
  if (now - lastTouch <= 300) e.preventDefault();
  lastTouch = now;
}, { passive: false });

// Auto-dismiss alerts after 3s
setTimeout(() => {
  document.querySelectorAll('.fh-alert').forEach(el => {
    if (!window.bootstrap) return;
    const alert = bootstrap.Alert.getOrCreateInstance(el);
    setTimeout(() => alert.close(), 3000);
  });
}, 100);

// Keep background content fixed while any modal is open.
(function () {
  const body = document.body;

  const lockScroll = () => body.classList.add('fh-modal-open');
  const unlockScroll = () => {
    if (document.querySelector('.modal.show')) return;
    body.classList.remove('fh-modal-open');
  };

  document.addEventListener('show.bs.modal', lockScroll);
  document.addEventListener('shown.bs.modal', lockScroll);
  document.addEventListener('hide.bs.modal', () => window.setTimeout(unlockScroll, 0));
  document.addEventListener('hidden.bs.modal', () => window.setTimeout(unlockScroll, 0));

  // Focus the first meaningful control when a dialog opens. PIN dialogs mark
  // their input with data-fh-autofocus so it is ready to type into immediately.
  document.addEventListener('shown.bs.modal', (event) => {
    const modal = event.target;
    if (!modal) return;
    const target = modal.querySelector('[data-fh-autofocus]') ||
      modal.querySelector('input:not([type="hidden"]):not([disabled]), textarea:not([disabled]), select:not([disabled])');
    if (!target) return;
    window.setTimeout(() => {
      try {
        target.focus({ preventScroll: true });
      } catch (err) {
        target.focus();
      }
    }, 30);
  });

  // Remove a stale backdrop that would otherwise leave a grey film over the
  // page and swallow clicks after an interrupted modal transition.
  const clearStaleBackdrop = () => {
    if (document.querySelector('.modal.show')) return;
    document.querySelectorAll('.modal-backdrop').forEach((el) => el.remove());
    body.classList.remove('fh-modal-open');
    body.classList.remove('modal-open');
    body.style.removeProperty('overflow');
    body.style.removeProperty('padding-right');
  };
  document.addEventListener('hidden.bs.modal', () => window.setTimeout(clearStaleBackdrop, 0));

  // Repair stale Bootstrap state after a bfcache restore or interrupted modal.
  window.addEventListener('pageshow', clearStaleBackdrop);
})();

// Responsive app shell navigation
document.addEventListener('DOMContentLoaded', () => {
  const shell = document.querySelector('.fh-app-nav');
  if (!shell) return;

  document.body.classList.add('fh-nav-enabled');

  const sheet = document.getElementById('fhMoreSheet');
  const backdrop = shell.querySelector('[data-fh-more-close]');
  const openButton = shell.querySelector('[data-fh-more-open]');
  const desktop = window.matchMedia('(min-width: 992px)');

  const setOpen = (open) => {
    if (!sheet || !backdrop) return;
    sheet.classList.toggle('show', open);
    backdrop.classList.toggle('show', open);
    if (openButton) openButton.setAttribute('aria-expanded', String(open));
  };

  if (openButton) {
    openButton.addEventListener('click', () => {
      setOpen(!(sheet && sheet.classList.contains('show')));
    });
  }
  if (backdrop) backdrop.addEventListener('click', () => setOpen(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setOpen(false);
  });
  desktop.addEventListener('change', (event) => {
    if (event.matches) setOpen(false);
  });

  const sidebar = document.querySelector('.fh-sidebar');
  if (sidebar) {
    const storageKey = 'fh-sidebar-scroll';
    try {
      const saved = parseInt(localStorage.getItem(storageKey), 10);
      if (!Number.isNaN(saved)) sidebar.scrollTop = saved;
    } catch (err) {}
    let scrollFrame = null;
    sidebar.addEventListener('scroll', () => {
      if (scrollFrame) return;
      scrollFrame = window.requestAnimationFrame(() => {
        scrollFrame = null;
        try {
          localStorage.setItem(storageKey, String(sidebar.scrollTop));
        } catch (err) {}
      });
    }, { passive: true });
  }
});
