(function () {
  const ticker = document.querySelector('[data-fh-alert-ticker]');
  if (!ticker) return;

  const content = ticker.querySelector('[data-fh-ticker-content]');
  const feedUrl = ticker.dataset.feedUrl || '/api/alerts';
  let latestKey = '';
  let pending = false;

  function collect(data) {
    const items = [];
    const seen = new Set();

    function add(title, body) {
      const heading = (title || '').trim();
      const copy = (body || '').trim();
      if (!heading) return;
      const key = heading + '|' + copy;
      if (seen.has(key)) return;
      seen.add(key);
      items.push({ title: heading, body: copy });
    }

    (data.broadcasts || []).forEach((item) => add(item.title, item.body));
    (data.events || []).slice().reverse().forEach((item) => {
      if (item.event_type !== 'broadcast') add(item.title, item.body);
    });
    return items.slice(0, 10);
  }

  function render(items) {
    const messages = items.length
      ? items
      : [{ title: 'Family alerts will appear here.', body: '' }];
    const key = messages.map((item) => item.title + '|' + item.body).join('~');
    if (key === latestKey) return;
    latestKey = key;

    content.textContent = '';
    messages.forEach((item) => {
      const span = document.createElement('span');
      span.className = 'fh-alert-ticker-item';
      span.textContent = item.body ? item.title + ' - ' + item.body : item.title;
      content.appendChild(span);
    });
    content.style.animation = 'none';
    void content.offsetWidth;
    content.style.animation = '';
  }

  function refresh() {
    if (pending) return;
    pending = true;
    fetch(feedUrl, {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    })
      .then((response) => {
        if (!response.ok) throw new Error('Unable to load alerts');
        return response.json();
      })
      .then((data) => render(collect(data)))
      .catch(() => {})
      .finally(() => { pending = false; });
  }

  const initial = Array.from(content.querySelectorAll('.fh-alert-ticker-item'));
  if (!initial.length) {
    const fallback = content.textContent.trim();
    if (fallback) {
      content.textContent = '';
      const span = document.createElement('span');
      span.className = 'fh-alert-ticker-item';
      span.textContent = fallback;
      content.appendChild(span);
    }
  }

  refresh();
  window.setInterval(refresh, 30000);
})();
