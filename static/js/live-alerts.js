// Chore Gremlin - live family alerts (SSE + browser notifications)
(function () {
  if (!window.EventSource) return;

  let lastEventId = 0;
  let permissionAsked = false;

  function notificationsEnabled() {
    return window.fhNotificationsEnabled !== false;
  }

  function notify(title, body, data) {
    if (!notificationsEnabled()) return;
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'granted') return;
    try {
      const notification = new Notification(title, {
        body: body || '',
        icon: '/static/icons/icon-192.png',
        tag: 'choregremlin-' + (data && data.id ? data.id : Date.now()),
      });
      notification.onclick = () => {
        const target = data && data.payload && data.payload.url;
        if (target) {
          window.location.href = target;
        } else {
          window.focus();
        }
        notification.close();
      };
    } catch (e) {
      // Notifications are best-effort only.
    }
  }

  function showToast(title, body, kind) {
    if (!title) return;
    const host = document.getElementById('fhLiveToasts') || (() => {
      const el = document.createElement('div');
      el.id = 'fhLiveToasts';
      el.className = 'fh-live-toasts';
      document.body.appendChild(el);
      return el;
    })();
    const toast = document.createElement('div');
    toast.className = 'fh-live-toast fh-live-toast-' + (kind || 'general');
    const heading = document.createElement('div');
    heading.className = 'fh-live-toast-title';
    heading.textContent = title;
    toast.appendChild(heading);
    if (body) {
      const copy = document.createElement('div');
      copy.className = 'fh-live-toast-body';
      copy.textContent = body;
      toast.appendChild(copy);
    }
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'fh-live-toast-close';
    close.setAttribute('aria-label', 'Dismiss alert');
    close.innerHTML = '<i class="bi bi-x-lg"></i>';
    close.addEventListener('click', () => toast.remove());
    toast.appendChild(close);
    host.appendChild(toast);
    setTimeout(() => toast.remove(), 9000);
  }

  function handleFrame(event) {
    let payload = {};
    try {
      payload = JSON.parse(event.data || '{}');
    } catch (e) {
      return;
    }
    if (payload.id && payload.id <= lastEventId) return;
    if (payload.id) lastEventId = payload.id;
    if (event.type === 'broadcast' || event.type === 'achievement') {
      const title = payload.title || 'Family update';
      const body = payload.body || '';
      showToast(title, body, payload.payload && payload.payload.kind);
      notify(title, body, payload);
    }
  }

  function connect() {
    const source = new EventSource('/events/stream' + (lastEventId ? '?since=' + lastEventId : ''));
    ['broadcast', 'achievement', 'message'].forEach((name) => {
      source.addEventListener(name, handleFrame);
    });
    source.addEventListener('ready', (event) => {
      try {
        const payload = JSON.parse(event.data || '{}');
        const latest = payload.latest_event_id || 0;
        if (!lastEventId && latest) lastEventId = latest;
      } catch (e) {}
    });
    source.onerror = () => {
      // EventSource reconnects automatically; stay quiet to avoid alert spam.
    };
  }

  document.addEventListener('click', () => {
    if (permissionAsked || !notificationsEnabled()) return;
    permissionAsked = true;
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {});
    }
  }, { once: true });

  connect();
})();
