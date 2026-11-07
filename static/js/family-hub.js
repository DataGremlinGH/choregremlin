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
    const alert = bootstrap.Alert.getOrCreateInstance(el);
    setTimeout(() => alert.close(), 3000);
  });
}, 100);

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
    openButton.addEventListener('click', () => setOpen(!sheet.classList.contains('show')));
  }
  if (backdrop) backdrop.addEventListener('click', () => setOpen(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setOpen(false);
  });
  desktop.addEventListener('change', (event) => {
    if (event.matches) setOpen(false);
  });
});
