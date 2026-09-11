(function () {
  'use strict';

  const list = document.getElementById('healthServicesList');
  const summary = document.getElementById('healthServicesSummary');
  const checkedAt = document.getElementById('healthCheckedAt');
  const refreshBtn = document.getElementById('healthRefreshBtn');
  if (!list || !summary || !checkedAt) return;

  const STATUS_TEXT = {
    ok: 'Correcto',
    warning: 'Advertencia',
    error: 'Error'
  };

  const STATUS_ICON = {
    ok: '✓',
    warning: '!',
    error: '×'
  };

  function safeText(value) {
    return String(value == null ? '' : value);
  }

  function formatTime(value) {
    if (!value) return 'Sin comprobar';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return safeText(value);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function renderService(service) {
    const item = document.createElement('details');
    item.className = 'health-service health-service-' + safeText(service.status || 'warning');

    const head = document.createElement('summary');
    const titleWrap = document.createElement('span');
    titleWrap.className = 'health-service-title';

    const icon = document.createElement('span');
    icon.className = 'health-service-state-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = STATUS_ICON[service.status] || '!';

    const name = document.createElement('b');
    name.textContent = safeText(service.label || service.service);

    titleWrap.appendChild(icon);
    titleWrap.appendChild(name);

    const state = document.createElement('span');
    state.className = 'health-service-state';
    state.textContent = STATUS_TEXT[service.status] || 'Advertencia';

    head.appendChild(titleWrap);
    head.appendChild(state);
    item.appendChild(head);

    const body = document.createElement('div');
    body.className = 'health-service-body';

    const message = document.createElement('p');
    message.className = 'health-service-message';
    message.textContent = safeText(service.message);
    body.appendChild(message);

    const rows = document.createElement('div');
    rows.className = 'health-service-checks';
    (service.checks || []).forEach(function (check) {
      const row = document.createElement('div');
      row.className = 'health-service-check';

      const label = document.createElement('span');
      label.textContent = safeText(check.label);
      const value = document.createElement('b');
      if (check.ok === true) value.className = 'health-check-ok';
      else if (check.ok === false) value.className = 'health-check-error';
      else value.className = 'health-check-warning';
      value.textContent = safeText(check.detail);

      row.appendChild(label);
      row.appendChild(value);
      rows.appendChild(row);
    });
    body.appendChild(rows);

    if (service.code && service.code !== 'OK') {
      const code = document.createElement('div');
      code.className = 'health-service-code';
      code.textContent = safeText(service.code);
      body.appendChild(code);
    }

    item.appendChild(body);
    return item;
  }

  function render(data) {
    const services = data && data.services ? Object.values(data.services) : [];
    list.innerHTML = '';
    services.forEach(function (service) {
      list.appendChild(renderService(service));
    });
    if (!services.length) {
      const empty = document.createElement('div');
      empty.className = 'health-service-placeholder';
      empty.textContent = 'No se encontraron servicios para comprobar.';
      list.appendChild(empty);
    }

    const counts = services.reduce(function (acc, service) {
      const key = service.status in acc ? service.status : 'warning';
      acc[key] += 1;
      return acc;
    }, { ok: 0, warning: 0, error: 0 });

    if (counts.error) {
      summary.textContent = counts.error + ' servicio' + (counts.error === 1 ? '' : 's') + ' con error · ' + counts.warning + ' con advertencia';
      summary.className = 'health-services-summary health-summary-error';
    } else if (counts.warning) {
      summary.textContent = counts.ok + ' operativo' + (counts.ok === 1 ? '' : 's') + ' · ' + counts.warning + ' con advertencia';
      summary.className = 'health-services-summary health-summary-warning';
    } else {
      summary.textContent = 'Todos los servicios comprobados están operativos.';
      summary.className = 'health-services-summary health-summary-ok';
    }
    checkedAt.textContent = 'Última comprobación: ' + formatTime(data.checked_at);
  }

  async function load(force) {
    if (refreshBtn) {
      refreshBtn.disabled = true;
      refreshBtn.textContent = 'Comprobando…';
    }
    summary.textContent = 'Comprobando servicios…';
    summary.className = 'health-services-summary';
    try {
      const url = '/api/system/health?probe=1' + (force ? '&refresh=1' : '');
      const response = await fetch(url, { headers: { 'Accept': 'application/json' } });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || 'No se pudo comprobar el sistema.');
      render(data);
    } catch (error) {
      summary.textContent = 'No se pudo completar el autodiagnóstico.';
      summary.className = 'health-services-summary health-summary-error';
      list.innerHTML = '';
      const row = document.createElement('div');
      row.className = 'health-service-placeholder';
      row.textContent = safeText(error && error.message ? error.message : error);
      list.appendChild(row);
      checkedAt.textContent = 'Sin comprobación completa';
    } finally {
      if (refreshBtn) {
        refreshBtn.disabled = false;
        refreshBtn.textContent = 'Comprobar servicios';
      }
    }
  }

  if (refreshBtn) refreshBtn.addEventListener('click', function () { load(true); });
  load(false);
})();
