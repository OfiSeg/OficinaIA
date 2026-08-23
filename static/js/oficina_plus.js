/* OficinaIA Plus v3 — badge, chips contextuales, plantillas sin reload */
(function () {
  'use strict';

  /* ---------- Badge pendientes ---------- */
  window.actualizarBadgePendientes = function (n) {
    const badge = document.getElementById('badgePendientes');
    if (!badge) return;
    const num = Number(n) || 0;
    if (num > 0) {
      badge.hidden = false;
      badge.textContent = num > 99 ? '99+' : String(num);
    } else {
      badge.hidden = true;
      badge.textContent = '0';
    }
  };

  async function refrescarBadgePendientes() {
    try {
      const r = await fetch('/api/pendientes?estado=pendiente', { credentials: 'same-origin' });
      const d = await r.json();
      if (r.ok && d.ok) window.actualizarBadgePendientes(d.total_pendientes || 0);
    } catch (_) {}
  }

  window.crearPendiente = async function (tipo, titulo, payload) {
    try {
      const r = await fetch('/api/pendientes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ tipo, titulo, payload: payload || {} }),
      });
      const d = await r.json();
      if (!r.ok || !d.ok) throw new Error(d.error || 'No se pudo crear el pendiente');
      window.actualizarBadgePendientes(d.total_pendientes || 0);
      if (window.showToast) showToast('Quedó en Pendientes', 'success');
      return d.id;
    } catch (e) {
      if (window.showToast) showToast(e.message || 'Error', 'error');
      return null;
    }
  };

  /* ---------- Chips contextuales arriba del composer ---------- */
  let ultimoTextoSofia = '';

  function asegurarBarraChips() {
    const wrap = document.querySelector('.composer-wrap');
    if (!wrap) return null;
    let bar = document.getElementById('composerSuggestions');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'composerSuggestions';
      bar.className = 'composer-suggestions';
      bar.setAttribute('aria-label', 'Sugerencias');
      const composer = wrap.querySelector('.composer');
      if (composer) wrap.insertBefore(bar, composer);
      else wrap.appendChild(bar);
    }
    return bar;
  }

  function limpiarChips() {
    const bar = document.getElementById('composerSuggestions');
    if (bar) bar.innerHTML = '';
  }

  function pareceConocimientoUtil(texto) {
    if (!texto || texto.length < 80) return false;
    const t = texto.toLowerCase();
    // Evitar saludos / errores cortos
    if (/^(hola|ok|listo|gracias|no pude|error)/i.test(texto.trim())) return false;
    // Señales de contenido operativo
    const señales = [
      'cobertura', 'remolque', 'grúa', 'grua', 'asistencia', 'km', 'servicio',
      'póliza', 'poliza', 'franquicia', 'compañía', 'compania', 'plan',
      'límite', 'limite', 'exclusión', 'exclusion', 'terceros', 'all risk',
      '•', 'patente', 'suma asegurada',
    ];
    return señales.some((s) => t.includes(s)) || texto.length > 220;
  }

  function pareceMensajeCliente(texto) {
    const t = (texto || '').toLowerCase();
    return t.includes('whatsapp') || t.includes('te dejamos') || t.includes('san josé') || t.includes('san jose');
  }

  async function guardarComoFicha(texto) {
    if (!texto) return;
    try {
      const r = await fetch('/api/ficha-desde-texto', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ texto }),
      });
      const d = await r.json();
      if (!r.ok || !d.ok) throw new Error(d.error || 'No se pudo armar la ficha');
      const ficha = d.ficha;
      const save = await fetch('/api/metadatos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ titulo: ficha.titulo, contenido: ficha.contenido }),
      });
      const sd = await save.json();
      if (!save.ok || !sd.ok) throw new Error(sd.error || 'No se pudo guardar el metadato');
      if (window.showToast) showToast('Ficha guardada en Metadatos', 'success');
      limpiarChips();
    } catch (e) {
      if (window.showToast) showToast(e.message || 'Error al guardar ficha', 'error');
    }
  }

  function mostrarChipsParaTexto(texto) {
    const bar = asegurarBarraChips();
    if (!bar) return;
    bar.innerHTML = '';
    ultimoTextoSofia = texto || '';
    if (!pareceConocimientoUtil(ultimoTextoSofia) && !pareceMensajeCliente(ultimoTextoSofia)) return;

    const chips = [];

    if (pareceConocimientoUtil(ultimoTextoSofia)) {
      chips.push({
        id: 'ficha',
        label: 'Guardar como ficha',
        title: 'Guarda este contenido en Metadatos para no volver a buscarlo',
      });
    }

    if (pareceMensajeCliente(ultimoTextoSofia) || ultimoTextoSofia.length > 120) {
      chips.push({
        id: 'copiar',
        label: 'Copiar respuesta',
        title: 'Copiar texto para pegar donde haga falta',
      });
    }

    // WhatsApp solo si no parece ya un mensaje listo, o como atajo suave
    if (!pareceMensajeCliente(ultimoTextoSofia) && pareceConocimientoUtil(ultimoTextoSofia)) {
      chips.push({
        id: 'wa',
        label: 'Armar WhatsApp',
        title: 'Pide a Sofia un mensaje listo para el cliente',
      });
    }

    chips.forEach((c) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'composer-chip';
      btn.textContent = c.label;
      btn.title = c.title;
      btn.dataset.chip = c.id;
      bar.appendChild(btn);
    });

    bar.onclick = async (e) => {
      const btn = e.target.closest('button[data-chip]');
      if (!btn) return;
      const id = btn.dataset.chip;
      if (id === 'ficha') {
        btn.disabled = true;
        await guardarComoFicha(ultimoTextoSofia);
        btn.disabled = false;
      } else if (id === 'copiar') {
        try {
          await navigator.clipboard.writeText(ultimoTextoSofia);
          if (window.showToast) showToast('Copiado', 'success');
        } catch (_) {
          if (window.showToast) showToast('No se pudo copiar', 'error');
        }
      } else if (id === 'wa') {
        const i = document.getElementById('mensaje');
        if (i) {
          i.value =
            'Armame un mensaje de WhatsApp claro y cordial (San José Seguros), listo para copiar, con esta información:\n\n' +
            ultimoTextoSofia.slice(0, 2500);
          if (typeof size === 'function') size();
          i.focus();
        }
      }
    };
  }

  function textoDeMsg(msgEl) {
    const bubble = msgEl && msgEl.querySelector('.bubble');
    if (!bubble) return '';
    const clone = bubble.cloneNode(true);
    clone.querySelectorAll('.msg-copy, .sofia-actions, .excel-proposal, .tabulado-flota, .metadata-proposal').forEach((n) => n.remove());
    // Si es propuesta estructurada, no sugerir ficha genérica
    if (bubble.classList.contains('excel-proposal') || bubble.classList.contains('tabulado-flota')) return '';
    return (clone.innerText || clone.textContent || '').trim();
  }

  function observarChat() {
    const chat = document.getElementById('chat');
    if (!chat || chat.dataset.plusObserved) return;
    chat.dataset.plusObserved = '1';
    asegurarBarraChips();

    const mo = new MutationObserver((mutations) => {
      mutations.forEach((m) => {
        m.addedNodes.forEach((node) => {
          if (node.nodeType !== 1) return;
          if (node.classList && node.classList.contains('msg') && node.classList.contains('assistant')) {
            const tryShow = () => {
              if (node.querySelector('.typing')) return;
              const texto = textoDeMsg(node);
              if (texto) mostrarChipsParaTexto(texto);
            };
            setTimeout(tryShow, 100);
            setTimeout(tryShow, 500);
            setTimeout(tryShow, 1200);
          }
        });
      });
    });
    mo.observe(chat, { childList: true, subtree: false });
  }

  /* ---------- Tags historial ---------- */
  function tagDesdeTitulo(titulo) {
    const t = String(titulo || '').toLowerCase();
    if (t.includes('/flota') || t.includes('flota')) return 'Flota';
    if (t.includes('/coti') || t.includes('coti') || t.includes('cotiz')) return 'Coti';
    if (t.includes('whatsapp') || t.includes('mensaje')) return 'WA';
    if (t.includes('remolque') || t.includes('grúa') || t.includes('grua') || t.includes('asistencia')) return 'Remolque';
    if (t.includes('cobertura')) return 'Cobertura';
    if (t.includes('asegurado') || t.includes('/guardar')) return 'Alta';
    if (t.includes('envios') || t.includes('envíos')) return 'Envío';
    return '';
  }

  const _renderListaChatsOrig = window.renderListaChats;
  if (typeof _renderListaChatsOrig === 'function') {
    window.renderListaChats = function (chats) {
      _renderListaChatsOrig(chats);
      document.querySelectorAll('.chat-item-title').forEach((el) => {
        if (el.querySelector('.chat-tag')) return;
        const tag = tagDesdeTitulo(el.textContent);
        if (!tag) return;
        const span = document.createElement('em');
        span.className = 'chat-tag';
        span.textContent = tag;
        el.appendChild(span);
      });
    };
  }

  /* ---------- Plantillas metadato (sin reload) ---------- */
  async function inyectarPlantillasMetadato() {
    const panel = document.getElementById('metaPanel');
    if (!panel || document.getElementById('metaPlantillas')) return;
    const head = panel.querySelector('.workspace-head .excel-actions') || panel.querySelector('.workspace-head');
    if (!head) return;
    try {
      const r = await fetch('/api/plantillas-metadato', { credentials: 'same-origin' });
      const d = await r.json();
      if (!r.ok || !d.ok) return;
      const wrap = document.createElement('div');
      wrap.id = 'metaPlantillas';
      wrap.className = 'meta-plantillas';
      wrap.innerHTML = '<span class="meta-plantillas-label">Plantillas:</span>';
      (d.plantillas || []).forEach((pl) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn-soft';
        b.textContent = pl.id;
        b.title = pl.titulo;
        b.addEventListener('click', async () => {
          const titulo = pl.titulo.replace(/\{[^}]+\}/g, '').replace(/\s+/g, ' ').trim() || 'Nueva ficha';
          const contenido = pl.contenido;
          try {
            b.disabled = true;
            const r2 = await fetch('/api/metadatos', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              credentials: 'same-origin',
              body: JSON.stringify({ titulo, contenido }),
            });
            const d2 = await r2.json();
            if (!r2.ok || !d2.ok) throw new Error(d2.error || 'Error');
            if (window.showToast) showToast('Plantilla creada: ' + pl.id, 'success');
            if (typeof window.abrirPanelMetadatos === 'function') window.abrirPanelMetadatos();
            if (typeof window.cargarListaMetadatos === 'function') await window.cargarListaMetadatos();
            if (typeof window.cargarMetadato === 'function' && d2.metadato && d2.metadato.id) {
              await window.cargarMetadato(d2.metadato.id);
            }
          } catch (e) {
            if (window.showToast) showToast(e.message || 'No se pudo crear', 'error');
          } finally {
            b.disabled = false;
          }
        });
        wrap.appendChild(b);
      });
      head.appendChild(wrap);
    } catch (_) {}
  }

  document.addEventListener('DOMContentLoaded', () => {
    refrescarBadgePendientes();
    observarChat();
    inyectarPlantillasMetadato();
  });
})();
