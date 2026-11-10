(function () {
  const cards = () => Array.from(document.querySelectorAll('.drop-item[data-drop-id]'));
  let syncing = false;
  let refreshing = false;

  function formatTime(totalSeconds) {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    const minutes = Math.floor(seconds / 60);
    return String(minutes).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
  }

  function setSeconds(card, seconds) {
    card.dataset.dropSeconds = String(Math.max(0, seconds));
    const countdown = card.querySelector('[data-drop-countdown]');
    if (countdown) countdown.textContent = formatTime(seconds);
  }

  function setPoints(card, points) {
    const value = Math.max(0, Number(points) || 0);
    card.dataset.dropCurrent = String(value);
    const label = card.querySelector('[data-drop-points]');
    if (label) label.textContent = value.toFixed(2);
  }

  function refreshPage() {
    if (refreshing) return;
    refreshing = true;
    window.location.reload();
  }

  function removeCard(card) {
    card.remove();
    if (!cards().length) refreshPage();
  }

  function tick() {
    cards().forEach((card) => {
      const seconds = Math.max(0, Number(card.dataset.dropSeconds) - 1);
      const decay = Math.max(0, Number(card.dataset.dropDecay) || 0);
      const points = Math.max(0, Number(card.dataset.dropCurrent) - (decay / 60));
      setSeconds(card, seconds);
      setPoints(card, points);
      if (seconds <= 0) removeCard(card);
    });
  }

  function applyDrops(drops) {
    const byId = new Map(drops.map((drop) => [String(drop.id), drop]));
    cards().forEach((card) => {
      const drop = byId.get(String(card.dataset.dropId));
      if (!drop) {
        removeCard(card);
        return;
      }
      setSeconds(card, drop.seconds_remaining);
      setPoints(card, drop.current_points);
    });
  }

  function sync() {
    if (syncing) return;
    syncing = true;
    fetch('/api/drop-chores', { cache: 'no-store', headers: { Accept: 'application/json' } })
      .then((response) => {
        if (!response.ok) throw new Error('Unable to sync drop chores');
        return response.json();
      })
      .then(applyDrops)
      .catch(() => {})
      .finally(() => { syncing = false; });
  }

  if (cards().length) {
    tick();
    window.setInterval(tick, 1000);
    window.setInterval(sync, 5000);
  }
})();
