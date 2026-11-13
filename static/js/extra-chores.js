// Chore Gremlin - Request Extra Chore modal
(function () {
  const modal = document.getElementById('extraChoreModal');
  const body = document.getElementById('extraChoreBody');
  if (!modal || !body) return;

  const optionsUrl = body.dataset.optionsUrl;
  const csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  let loaded = false;
  let loading = false;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function iconNode(chore) {
    const wrap = element('div', 'fh-extra-chore-icon');
    if (chore.chore_image) {
      const img = document.createElement('img');
      img.src = chore.chore_image;
      img.alt = '';
      img.width = 28;
      img.height = 28;
      img.style.borderRadius = '6px';
      wrap.appendChild(img);
    } else if (chore.chore_emoji) {
      wrap.textContent = chore.chore_emoji;
    } else {
      const icon = document.createElement('i');
      icon.className = 'bi ' + (chore.icon || 'bi-list-check');
      wrap.appendChild(icon);
    }
    return wrap;
  }

  function actionNode(chore, data) {
    if (chore.is_active) {
      return element('div', 'text-end small text-warning',
        'Please complete existing chore first');
    }
    if (chore.pending_approval) {
      return element('span', 'badge bg-secondary', 'Awaiting approval');
    }

    const form = document.createElement('form');
    form.method = 'POST';
    form.action = data.request_url || '';
    form.className = 'm-0';

    const choreInput = document.createElement('input');
    choreInput.type = 'hidden';
    choreInput.name = 'chore_id';
    choreInput.value = chore.id;
    form.appendChild(choreInput);

    const csrfInput = document.createElement('input');
    csrfInput.type = 'hidden';
    csrfInput.name = 'csrf_token';
    csrfInput.value = csrfToken;
    form.appendChild(csrfInput);

    const button = element('button', 'btn fh-btn-success btn-sm');
    button.type = 'submit';
    const icon = document.createElement('i');
    icon.className = 'bi bi-send-fill';
    button.appendChild(icon);
    button.appendChild(document.createTextNode(' Request Extra'));
    form.appendChild(button);
    return form;
  }

  function render(data) {
    body.textContent = '';
    const chores = data.chores || [];
    if (!chores.length) {
      const empty = element('div', 'text-center text-muted py-4');
      const icon = document.createElement('i');
      icon.className = 'bi bi-clipboard-x fs-1 d-block mb-2';
      empty.appendChild(icon);
      empty.appendChild(element('p', 'mb-0', 'No extra chores are available right now.'));
      body.appendChild(empty);
      return;
    }

    const list = element('div', 'd-flex flex-column gap-2');
    chores.forEach((chore) => {
      const row = element('div', 'fh-extra-chore-option');
      row.appendChild(iconNode(chore));

      const info = element('div', 'flex-fill');
      info.appendChild(element('div', 'fw-semibold', chore.name));
      const pay = element('div', 'small text-muted');
      pay.appendChild(document.createTextNode((data.token_icon || '') + ' '));
      pay.appendChild(document.createTextNode(Number(chore.pay_amount || 0).toFixed(2) + ' extra'));
      info.appendChild(pay);
      row.appendChild(info);
      row.appendChild(actionNode(chore, data));
      list.appendChild(row);
    });
    body.appendChild(list);
  }

  function showError() {
    body.textContent = '';
    const wrap = element('div', 'text-center text-muted py-4');
    wrap.appendChild(element('p', 'mb-2', 'Unable to load extra chores right now.'));
    const retry = element('button', 'btn fh-btn-outline btn-sm', 'Try again');
    retry.type = 'button';
    retry.addEventListener('click', () => {
      loaded = false;
      load();
    });
    wrap.appendChild(retry);
    body.appendChild(wrap);
  }

  function load() {
    if (loaded || loading) return;
    loading = true;
    body.textContent = '';
    const loadingWrap = element('div', 'text-center text-muted py-4');
    const spinner = element('span', 'spinner-border spinner-border-sm me-2');
    spinner.setAttribute('role', 'status');
    spinner.setAttribute('aria-hidden', 'true');
    loadingWrap.appendChild(spinner);
    loadingWrap.appendChild(document.createTextNode('Loading extra chores...'));
    body.appendChild(loadingWrap);

    fetch(optionsUrl, {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    })
      .then((response) => {
        if (!response.ok) throw new Error('Unable to load extra chores');
        return response.json();
      })
      .then((data) => {
        loaded = true;
        render(data);
      })
      .catch(showError)
      .finally(() => { loading = false; });
  }

  modal.addEventListener('show.bs.modal', load);
})();
