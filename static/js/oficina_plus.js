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

  /* ---------- Tips de descubrimiento (arriba del chat) ---------- */
  const TIPS_OFICINAIA = [
    'Tirame una póliza en PDF al chat y puedo analizarla.',
    'Si tirás una póliza individual, puedo reconocerla y prepararte el alta automáticamente.',
    'También podés usar /alta para procesar una póliza individual a mano.',
    'De una póliza puedo sacar datos como asegurado, número, vehículo, patente y compañía.',
    'Cuando aparecen en la póliza, también detecto el medio de pago y el código postal.',
    'Antes de guardar un alta, siempre podés revisar los datos que encontré.',
    'Puedo prepararte los datos de una póliza tabulados, listos para pegar en Excel.',
    'Si una póliza trae varios vehículos, la distingo de una póliza individual.',
    'Podés adjuntar el PDF con el 📎 o arrastrarlo directo sobre el chat.',
    'Si mandás un PDF sin escribir nada, igual lo proceso.',
    'Los PDFs que adjuntás pueden pesar hasta 20 MB.',
    'Usá /flota para empezar a armar una flota.',
    'No hace falta mandar toda la flota junta: podés cargarla en tandas.',
    'También podés sumar vehículos de a uno.',
    'Mientras armamos la flota, podés corregirme un dato de un vehículo puntual.',
    'Si a un vehículo le falta un dato, me lo podés pasar más adelante.',
    'Los vehículos que ya cargaste quedan guardados mientras seguimos con la flota.',
    'Antes de que la flota llegue al Excel, la revisás vos.',
    'El resultado de /flota queda tabulado, listo para copiar y pegar en Excel.',
    'Podés armar una flota grande sin cargar cada vehículo a mano en el Excel.',
    'Reconozco datos como patente, año, motor, chasis, uso, suma asegurada y cobertura, según el formato de la póliza.',
    'Tengo un procesamiento pensado especialmente para el formato de flotas de La Segunda.',
    'Si un dato de una fila no me cierra, lo marco para que lo revises en vez de inventarlo.',
    'Los vehículos con datos dudosos pueden quedar pendientes de revisión mientras seguís cargando el resto.',
    'OficinaIA trabaja con un Excel de Asegurados y otro de Flotas.',
    'Podés elegir con qué libro de Excel querés trabajar.',
    'Podés editar celdas del Excel directamente desde OficinaIA.',
    'Podés agregar filas nuevas a la planilla.',
    'Podés eliminar las filas vacías de un saque.',
    'Podés eliminar columnas vacías.',
    'Podés agregar columnas nuevas.',
    'Podés eliminar columnas.',
    'Podés importar un Excel existente a OficinaIA.',
    'También podés exportar la planilla cuando la necesites.',
    'Los datos de Asegurados y de Flotas se guardan en libros separados.',
    'Para guardar un dato, busco la columna por su nombre, no por una posición fija.',
    'Antes de sumar un asegurado, valido que tenga los datos mínimos para identificarlo.',
    'Si una patente ya está cargada, te aviso antes de que la guardes de nuevo.',
    'Usá /guardar asegurado para preparar un registro nuevo.',
    '/guardar asegurado acepta los datos entre paréntesis.',
    'También podés pasarle los datos de /guardar asegurado separados por comas.',
    'Al final de /guardar asegurado podés indicar en qué Excel guardarlo.',
    'El Excel 1 es Asegurados y el Excel 2 es Flotas.',
    'Antes de guardar un alta que salió de una póliza, podés revisar lo que encontré.',
    'Los datos de la póliza se acomodan según las columnas reales de tu Excel.',
    'Usá /coti para cargar una cotización rápida.',
    'El formato de /coti es: CIA COBERTURA SUMA PREMIO.',
    'En /coti podés indicar compañía, cobertura, suma asegurada y premio.',
    '/coti es un comando fijo: no depende de que Gemini lo interprete.',
    'Usá /envios ya seguido de la patente.',
    '/envios ya también acepta la patente entre paréntesis.',
    'Los datos de Envíos Ya se guardan aparte del resto del asegurado.',
    'Cuando preparo un alta desde una póliza, Envíos Ya queda vacío para que lo completes vos.',
    'Podés preguntarme por coberturas, asistencia, remolques, grúas, límites o condiciones usando la documentación cargada.',
    'Si mencionás una compañía, busco directo en su documentación.',
    'Puedo buscar dentro de los PDFs cargados por término o frase.',
    'Los metadatos pueden completar la información que traen los PDFs.',
    'Podés guardar un dato útil de una compañía como metadato, para tenerlo a mano en futuras consultas.',
    'Distingo entre una consulta sobre tu cartera y una consulta sobre documentación de compañías.',
    'Para preguntas de coberturas, asistencia o remolque, uso la documentación cargada como fuente.',
  ];

  function mostrarTipOficinaIA() {
    const tarjeta = document.getElementById('chatTip');
    const texto = document.getElementById('chatTipTexto');
    const cerrar = document.getElementById('chatTipCerrar');
    if (!tarjeta || !texto || !cerrar || !TIPS_OFICINAIA.length) return;

    // El tip se muestra SIEMPRE al cargar/entrar al Chat IA.
    // No usamos sessionStorage para recordar que ya fue mostrado:
    // F5, nueva entrada al chat o nuevo inicio de sesión vuelven a mostrarlo.
    let elegido = Math.floor(Math.random() * TIPS_OFICINAIA.length);

    // Evita repetir el mismo tip de forma consecutiva cuando sea posible.
    try {
      const ultimo = Number(localStorage.getItem('oficinaia_ultimo_tip'));
      if (TIPS_OFICINAIA.length > 1 && Number.isInteger(ultimo) && elegido === ultimo) {
        elegido = (elegido + 1 + Math.floor(Math.random() * (TIPS_OFICINAIA.length - 1))) % TIPS_OFICINAIA.length;
      }
      localStorage.setItem('oficinaia_ultimo_tip', String(elegido));
    } catch (_) {}

    texto.textContent = TIPS_OFICINAIA[elegido];
    tarjeta.hidden = false;

    // La X solo cierra el cartel actual. Al volver a cargar/entrar,
    // el tip vuelve a aparecer.
    cerrar.onclick = function () {
      tarjeta.hidden = true;
    };
  }
  document.addEventListener('DOMContentLoaded', mostrarTipOficinaIA);
})();
