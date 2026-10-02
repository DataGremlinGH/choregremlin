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
