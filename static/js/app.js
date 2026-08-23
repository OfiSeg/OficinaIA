async function leerJsonSeguro(response){
  const text=await response.text();
  let data=null;
  try{data=JSON.parse(text)}catch{
    const detalle=text.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim().slice(0,180);
    throw new Error(response.status===401||response.redirected?'La sesión expiró. Volvé a iniciar sesión.':`No se pudo procesar la respuesta del servidor (${response.status}).${detalle?' '+detalle:''}`);
  }
  if(!data || typeof data!=='object') throw new Error('La respuesta del servidor no es válida.');
  return data;
}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));

/** Limpia ruido de formato típico de modelos antes de renderizar. */
function limpiarFormatoIA(texto){
  let t=String(texto??'');
  // Separadores decorativos
  t=t.replace(/^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$/gm,'');
  // Encabezados markdown → negrita simple (máx. un nivel visual)
  t=t.replace(/^#{1,6}\s+(.+)$/gm,'**$1**');
  // Blockquotes decorativos / sangría con >>>
  t=t.replace(/^[ \t]*>{1,}\s?/gm,'');
  // Viñetas con - o * unificadas a •
  t=t.replace(/^[ \t]*[-*]\s+/gm,'• ');
  // Espacios excesivos entre bloques
  t=t.replace(/\n{3,}/g,'\n\n');
  return t.trim();
}

/**
 * Renderer liviano orientado a lectura de oficina:
 * párrafos, •, numeración, negrita, links y código inline.
 */
function fmt(s){
  const limpio=limpiarFormatoIA(s);
  let h=esc(limpio);
  // Links
  h=h.replace(/(https?:\/\/[^\s<]+)/g,'<a href="$1" target="_blank" rel="noopener">$1</a>');
  // Código inline `...`
  h=h.replace(/`([^`]+)`/g,'<code class="inline-code">$1</code>');
  // Negrita **...**
  h=h.replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>');
  // Cursiva simple *...* (evitar conflictos con negrita ya procesada)
  h=h.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g,'$1<em>$2</em>');

  const lineas=h.split(/\n/);
  const out=[];
  let enLista=false;

  const cerrarLista=()=>{if(enLista){out.push('</ul>');enLista=false}};

  for(const raw of lineas){
    const linea=raw.trim();
    if(!linea){
      cerrarLista();
      continue;
    }
    // Lista con •
    if(/^•\s+/.test(linea)){
      if(!enLista){out.push('<ul class="sofia-list">');enLista=true}
      out.push('<li>'+linea.replace(/^•\s+/,'')+'</li>');
      continue;
    }
    // Lista numerada 1. 2. 3.
    const num=linea.match(/^(\d+)[.)]\s+(.+)$/);
    if(num){
      cerrarLista();
      out.push('<p class="sofia-step"><span class="sofia-step-n">'+num[1]+'.</span> '+num[2]+'</p>');
      continue;
    }
    cerrarLista();
    out.push('<p>'+linea+'</p>');
  }
  cerrarLista();
  return out.join('')||'<p></p>';
}

function chatContainer(){return document.getElementById('chat')}

function isNearBottom(el,threshold=140){
  if(!el)return true;
  return el.scrollHeight-el.scrollTop-el.clientHeight<threshold;
}

/** Lleva el viewport al final del historial (mensaje del usuario / carga). */
function scrollToBottom(smooth=false){
  const c=chatContainer();
  if(!c)return;
  requestAnimationFrame(()=>{
    if(smooth&&'scrollTo' in c)c.scrollTo({top:c.scrollHeight,behavior:'smooth'});
    else c.scrollTop=c.scrollHeight;
  });
}

/**
 * Posiciona la vista al comienzo de un mensaje (respuesta de Sofia),
 * no al último renglón. Respeta header fijo con un offset pequeño.
 */
function scrollToMessageStart(msgEl,smooth=true){
  const c=chatContainer();
  if(!c||!msgEl)return;
  requestAnimationFrame(()=>{
    const offset=12;
    const top=msgEl.offsetTop-offset;
    const target=Math.max(0,top);
    if(smooth&&'scrollTo' in c)c.scrollTo({top:target,behavior:'smooth'});
    else c.scrollTop=target;
  });
}

/** Compatibilidad: scroll() sigue existiendo pero ya no es el comportamiento del final de respuesta. */
function scroll(){scrollToBottom(false)}

function size(){const i=document.getElementById('mensaje');if(i){i.style.height='auto';i.style.height=Math.min(i.scrollHeight,110)+'px'}}

function addCopyButton(bubble,rawText){
  if(!bubble||!rawText)return;
  const btn=document.createElement('button');
  btn.type='button';
  btn.className='msg-copy';
  btn.title='Copiar respuesta';
  btn.setAttribute('aria-label','Copiar respuesta');
  btn.textContent='Copiar';
  btn.addEventListener('click',async e=>{
    e.stopPropagation();
    try{
      await navigator.clipboard.writeText(rawText);
      btn.textContent='Copiado';
      if(window.showToast)showToast('Respuesta copiada','success');
      setTimeout(()=>{btn.textContent='Copiar'},1600);
    }catch(_){
      btn.textContent='Error';
      setTimeout(()=>{btn.textContent='Copiar'},1600);
    }
  });
  bubble.appendChild(btn);
}

function add(role,content,raw=false){
  const c=chatContainer();
  if(!c)return;
  const r=document.createElement('div');
  r.className='msg '+role;
  const x=document.createElement('div');
  x.className='bubble';
  if(raw){
    x.innerHTML=content;
  }else if(role==='assistant'){
    x.innerHTML=fmt(content);
    addCopyButton(x,String(content??''));
  }else{
    x.textContent=String(content??'');
  }
  r.appendChild(x);
  c.appendChild(r);
  return r;
}

function htmlWelcomeChat(variant){
  /* variant: 'default' | 'vacio' — siempre con atajos de flujo */
  const sub = variant==='vacio'
    ? 'Podés iniciar una nueva conversación cuando quieras. Usá los atajos o escribí abajo.'
    : 'Preguntá por coberturas, flotas, pólizas o datos de la planilla. Usá los atajos para los flujos que más tiempo consumen.';
  return `<div id="chatWelcome" class="welcome">
  <strong>✦</strong>
  <h2>¿Qué necesitás resolver?</h2>
  <p>${sub}</p>
  <div class="workflow-grid" id="workflowGrid">
    <button type="button" class="workflow-card" data-fill="/guardar asegurado "><b>Alta asegurado</b><small>Cargar a Excel con campos en orden</small></button>
    <button type="button" class="workflow-card" data-fill="/flota "><b>Armar flota</b><small>Propuesta de vehículos para la planilla</small></button>
    <button type="button" class="workflow-card" data-fill="/coti "><b>Cotización</b><small>Comando /coti con datos del riesgo</small></button>
    <button type="button" class="workflow-card" data-fill="¿Cuántos servicios de remolque tiene "><b>Remolque / asistencia</b><small>Consulta rápida por compañía y plan</small></button>
    <button type="button" class="workflow-card" data-fill="Armame un mensaje de WhatsApp para el asegurado: "><b>WhatsApp al cliente</b><small>Texto listo para copiar y enviar</small></button>
    <button type="button" class="workflow-card" data-fill="/envios ya "><b>Envíos Ya</b><small>Datos limpios para cargar el envío</small></button>
  </div>
</div>`;
}
function wireWelcomeWorkflows(root){
  const grid=(root||document).querySelector('#workflowGrid');
  if(!grid||grid.dataset.wired)return;
  grid.dataset.wired='1';
  grid.addEventListener('click',e=>{
    const card=e.target.closest('.workflow-card');
    if(!card)return;
    const i=document.getElementById('mensaje');
    if(!i)return;
    i.value=card.dataset.fill||'';
    if(typeof size==='function')size();
    i.focus();
  });
}

function usarSugerencia(t){const i=document.getElementById('mensaje');if(i){i.value=t;size();i.focus()}}
let currentChatId=null;
function historialParaApi(){const c=document.getElementById('chat');return c?[...c.querySelectorAll('.msg')].map(x=>({rol:x.classList.contains('user')?'user':'assistant',contenido:x.querySelector('.bubble')?.textContent?.trim()||''})).filter(x=>x.contenido).slice(-10):[]}
let _chatsCache=[];
let _chatSearchQuery='';

function formatearFechaChat(valor){
  if(!valor)return '';
  let d;
  try{
    const raw=String(valor).trim();
    // Postgres / SQLite: "2026-08-22 17:32:01" o ISO
    if(/^\d{4}-\d{2}-\d{2} /.test(raw))d=new Date(raw.replace(' ','T')+'Z');
    else d=new Date(raw);
    if(Number.isNaN(d.getTime()))return raw;
  }catch(_){return String(valor)}
  const fecha=d.toLocaleDateString('es-AR',{day:'2-digit',month:'2-digit',year:'numeric'});
  const hora=d.toLocaleTimeString('es-AR',{hour:'2-digit',minute:'2-digit'});
  return fecha+' · '+hora;
}

function asegurarBuscadorChats(){
  const list=document.querySelector('.chat-list');
  if(!list||document.getElementById('chatSearch'))return;
  const head=list.querySelector('.chat-list-head');
  if(!head)return;
  const wrap=document.createElement('div');
  wrap.className='chat-search-wrap';
  wrap.innerHTML='<input id="chatSearch" type="search" placeholder="Buscar conversación…" autocomplete="off" aria-label="Buscar conversación">';
  head.insertAdjacentElement('afterend',wrap);
  const input=document.getElementById('chatSearch');
  let t;
  input.addEventListener('input',()=>{
    clearTimeout(t);
    t=setTimeout(()=>{
      _chatSearchQuery=input.value.trim().toLowerCase();
      renderListaChats(_chatsCache);
    },120);
  });
}

function renderListaChats(chats){
  const box=document.getElementById('chatList');
  if(!box)return;
  const q=_chatSearchQuery;
  const filtrados=!q?chats:chats.filter(x=>String(x.titulo||'').toLowerCase().includes(q));
  box.innerHTML='';
  if(!chats.length){
    box.innerHTML='<div class="chat-empty">No hay conversaciones guardadas.</div>';
    return;
  }
  if(!filtrados.length){
    box.innerHTML='<div class="chat-empty">Sin coincidencias.</div>';
    return;
  }
  filtrados.forEach(x=>{
    const row=document.createElement('div');
    row.className='chat-item-row';
    row.dataset.chatId=String(x.id);

    const b=document.createElement('button');
    b.type='button';
    b.className='chat-item'+(x.id===currentChatId?' active':'');
    const tagMap={flota:'Flota',coti:'Coti',alta:'Alta',envios:'Envío',whatsapp:'WA'};
    const tagLabel=tagMap[String(x.tipo||'').toLowerCase()]||'';
    const tagHtml=tagLabel?'<em class="chat-tag">'+esc(tagLabel)+'</em>':'';
    b.innerHTML='<span class="chat-item-title">'+esc(x.titulo||'Sin título')+tagHtml+'</span><small class="chat-item-meta">'+esc(formatearFechaChat(x.actualizado_en))+'</small>';
    b.onclick=()=>{abrirChat(x.id);if(typeof window.cerrarSheetChats==='function')window.cerrarSheetChats();};
    b.title=x.titulo||'';

    const actions=document.createElement('div');
    actions.className='chat-item-actions';

    const ren=document.createElement('button');
    ren.type='button';
    ren.className='chat-rename';
    ren.title='Renombrar';
    ren.setAttribute('aria-label','Renombrar: '+(x.titulo||''));
    ren.textContent='✎';
    ren.onclick=e=>{e.stopPropagation();iniciarRenombreChat(x.id,x.titulo||'',row)};

    const del=document.createElement('button');
    del.type='button';
    del.className='chat-delete';
    del.title='Eliminar conversación';
    del.setAttribute('aria-label','Eliminar conversación: '+(x.titulo||''));
    del.textContent='🗑';
    del.onclick=e=>{e.stopPropagation();eliminarChat(x.id)};

    actions.appendChild(ren);
    actions.appendChild(del);
    row.appendChild(b);
    row.appendChild(actions);
    box.appendChild(row);
  });
}

async function cargarListaChats(){
  const box=document.getElementById('chatList');
  if(!box)return;
  asegurarBuscadorChats();
  const r=await fetch('/api/chats',{credentials:'same-origin'});
  const d=await leerJsonSeguro(r);
  if(!r.ok||d.ok===false)throw new Error(d.error||'No se pudo cargar el historial.');
  _chatsCache=Array.isArray(d.chats)?d.chats:[];
  renderListaChats(_chatsCache);
}

function iniciarRenombreChat(id,tituloActual,row){
  if(!row)return;
  const item=row.querySelector('.chat-item');
  if(!item)return;
  const input=document.createElement('input');
  input.type='text';
  input.className='chat-rename-input';
  input.value=tituloActual;
  input.maxLength=100;
  input.setAttribute('aria-label','Nuevo título');
  item.replaceWith(input);
  input.focus();
  input.select();

  let cerrado=false;
  const cancelar=()=>{
    if(cerrado)return;
    cerrado=true;
    renderListaChats(_chatsCache);
  };
  const guardar=async()=>{
    if(cerrado)return;
    cerrado=true;
    const nuevo=input.value.trim();
    if(!nuevo||nuevo===tituloActual){
      renderListaChats(_chatsCache);
      return;
    }
    try{
      const r=await fetch('/api/chats/'+id,{
        method:'PATCH',
        headers:{'Content-Type':'application/json'},
        credentials:'same-origin',
        body:JSON.stringify({titulo:nuevo})
      });
      const d=await leerJsonSeguro(r);
      if(!r.ok||d.ok===false)throw new Error(d.error||'No se pudo renombrar.');
      const i=_chatsCache.findIndex(c=>c.id===id);
      if(i>=0)_chatsCache[i]={..._chatsCache[i],titulo:d.titulo||nuevo};
      renderListaChats(_chatsCache);
      if(window.showToast)showToast('Conversación renombrada','success');
    }catch(e){
      if(window.showToast)showToast(e?.message||'No se pudo renombrar','error');
      renderListaChats(_chatsCache);
    }
  };
  input.addEventListener('keydown',e=>{
    if(e.key==='Enter'){e.preventDefault();guardar()}
    if(e.key==='Escape'){e.preventDefault();cancelar()}
  });
  input.addEventListener('blur',()=>guardar());
}

async function abrirChat(id){
  const r=await fetch('/api/chats/'+id,{credentials:'same-origin'});
  const d=await leerJsonSeguro(r);
  if(!r.ok||!d.ok)throw new Error(d.error||'No se pudo abrir la conversación.');
  currentChatId=id;
  const c=document.getElementById('chat');
  c.innerHTML='';
  if(!d.mensajes.length){
    c.innerHTML=htmlWelcomeChat('default');c.classList.add('history-empty');wireWelcomeWorkflows(c);try{c.scrollTop=0}catch(_){}
  }else{
    c.classList.remove('history-empty');
    d.mensajes.forEach(m=>add(m.rol,m.contenido));
    scrollToBottom(false);
  }
  await cargarListaChats();
  if(!d.mensajes.length){try{c.scrollTop=0}catch(_){}}
}

async function nuevoChat(){
  const r=await fetch('/api/chats',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({titulo:'Nueva conversación'}),
    credentials:'same-origin'
  });
  const d=await leerJsonSeguro(r);
  if(d.ok)await abrirChat(d.id);
}

async function eliminarChat(id){
  try{
    const r=await fetch('/api/chats/'+id,{method:'DELETE',credentials:'same-origin'});
    if(!r.ok){
      if(window.showToast)showToast('No se pudo eliminar la conversación','error');
      return;
    }
    if(currentChatId===id){
      currentChatId=null;
      const c=document.getElementById('chat');
      if(c){c.innerHTML=htmlWelcomeChat('vacio');c.classList.add('history-empty');wireWelcomeWorkflows(c);try{c.scrollTop=0}catch(_){}}
    }
    await cargarListaChats();
    if(window.showToast)showToast('Conversación eliminada','success');
  }catch(_){
    if(window.showToast)showToast('No se pudo eliminar la conversación','error');
  }
}

async function borrarChatActual(){
  if(!currentChatId)return;
  await eliminarChat(currentChatId);
}
let enviandoMensaje=false;
function mostrarTabuladoFlota(texto){
  const c=document.getElementById('chat');
  if(!c||!texto)return;
  const lineas=String(texto).split('\n').filter(Boolean);

  const r=document.createElement('div');
  r.className='msg assistant';
  const b=document.createElement('div');
  b.className='bubble tabulado-flota';

  const titulo=document.createElement('div');
  titulo.className='tabulado-flota-title';
  titulo.textContent=`Bloque para pegar en Excel: ${lineas.length} vehículo(s)`;
  b.appendChild(titulo);

  const ayuda=document.createElement('div');
  ayuda.className='tabulado-flota-help';
  ayuda.textContent='Copiá el bloque y pegalo en la celda ITEM de la primera fila vacía de excel/flotas. Las columnas están separadas por tabulador, así que Excel las va a acomodar solo.';
  b.appendChild(ayuda);

  const pre=document.createElement('pre');
  pre.className='tabulado-flota-pre';
  pre.textContent=texto;
  b.appendChild(pre);

  const acciones=document.createElement('div');
  acciones.className='tabulado-flota-actions';
  const btn=document.createElement('button');
  btn.type='button';
  btn.className='tabulado-flota-copy';
  btn.textContent='Copiar bloque';
  btn.onclick=async()=>{
    try{
      await navigator.clipboard.writeText(texto);
      btn.textContent='¡Copiado!';
      setTimeout(()=>{btn.textContent='Copiar bloque'},1800);
    }catch(e){
      // Fallback para navegadores/contextos sin permiso de clipboard API.
      pre.focus();
      const sel=window.getSelection(),range=document.createRange();
      range.selectNodeContents(pre);
      sel.removeAllRanges();sel.addRange(range);
      document.execCommand('copy');
      btn.textContent='¡Copiado!';
      setTimeout(()=>{btn.textContent='Copiar bloque'},1800);
    }
  };
  acciones.appendChild(btn);
  b.appendChild(acciones);

  r.appendChild(b);
  c.appendChild(r);
}

function mostrarTextoEnviosYa(texto){
  const c=document.getElementById('chat');
  if(!c||!texto)return;

  const r=document.createElement('div');
  r.className='msg assistant';
  const b=document.createElement('div');
  b.className='bubble tabulado-flota';

  const titulo=document.createElement('div');
  titulo.className='tabulado-flota-title';
  titulo.textContent='Datos para cargar en Envíos Ya';
  b.appendChild(titulo);

  const ayuda=document.createElement('div');
  ayuda.className='tabulado-flota-help';
  ayuda.textContent='Copiá y pegá directo en Envíos Ya. El teléfono ya viene sin espacios ni guiones.';
  b.appendChild(ayuda);

  const pre=document.createElement('pre');
  pre.className='tabulado-flota-pre';
  pre.textContent=texto;
  b.appendChild(pre);

  const acciones=document.createElement('div');
  acciones.className='tabulado-flota-actions';
  const btn=document.createElement('button');
  btn.type='button';
  btn.className='tabulado-flota-copy';
  btn.textContent='Copiar';
  btn.onclick=async()=>{
    try{
      await navigator.clipboard.writeText(texto);
      btn.textContent='¡Copiado!';
      setTimeout(()=>{btn.textContent='Copiar'},1800);
    }catch(e){
      pre.focus();
      const sel=window.getSelection(),range=document.createRange();
      range.selectNodeContents(pre);
      sel.removeAllRanges();sel.addRange(range);
      document.execCommand('copy');
      btn.textContent='¡Copiado!';
      setTimeout(()=>{btn.textContent='Copiar'},1800);
    }
  };
  acciones.appendChild(btn);
  b.appendChild(acciones);

  r.appendChild(b);
  c.appendChild(r);
}

function mostrarPropuestaExcel(propuesta){
  const c=document.getElementById('chat');
  if(!c||!propuesta||typeof propuesta!=='object')return;

  const libroIdInicial=String(propuesta.LIBRO_ID||'1');
  const esFlota=Array.isArray(propuesta.vehiculos);
  if(esFlota){
    const camposBase=['asegurado','domicilio','localidad','cp','patente','marca_modelo','año','motor','chasis','uso','suma_asegurada','cobertura'];
    const vehiculos=propuesta.vehiculos.map(v=>{
      const fila={};
      if(v&&typeof v==='object')Object.keys(v).forEach(k=>fila[k]=String(v[k]??''));
      camposBase.forEach(k=>{if(!Object.prototype.hasOwnProperty.call(fila,k))fila[k]='';});
      return fila;
    });
    if(!vehiculos.length){
      return;
    }

    const camposDetectados=[];
    vehiculos.forEach(v=>{
      Object.keys(v).forEach(k=>{
        if(!camposDetectados.includes(k))camposDetectados.push(k);
      });
    });
    const ordenCampos=camposBase.filter(k=>camposDetectados.includes(k))
      .concat(camposDetectados.filter(k=>!camposBase.includes(k)));

    const r=document.createElement('div');
    r.className='msg assistant';
    const b=document.createElement('div');
    b.className='bubble excel-proposal';
    const titulo=document.createElement('div');
    titulo.className='excel-proposal-title';
    titulo.textContent=`Propuesta de flota: ${vehiculos.length} vehículo(s)`;
    b.appendChild(titulo);

    const ayuda=document.createElement('div');
    ayuda.className='excel-proposal-help';
    ayuda.textContent='Revisá y editá los datos antes de guardar. Cada fila corresponde a un vehículo.';
    b.appendChild(ayuda);

    const selectorWrap=document.createElement('label');
    selectorWrap.className='excel-proposal-field';
    const selectorLabel=document.createElement('span');
    selectorLabel.textContent='Libro destino';
    const selector=document.createElement('select');
    selector.dataset.libro=true;
    [
      ['1','Excel 1 — Asegurados'],
      ['2','Excel 2 — Flotas']
    ].forEach(([value,label])=>{
      const option=document.createElement('option');
      option.value=value;
      option.textContent=label;
      option.selected=value===libroIdInicial;
      selector.appendChild(option);
    });
    selectorWrap.appendChild(selectorLabel);
    selectorWrap.appendChild(selector);
    b.appendChild(selectorWrap);

    const tablaWrap=document.createElement('div');
    tablaWrap.className='excel-proposal-table-wrap';
    const tabla=document.createElement('table');
    tabla.className='excel-proposal-table';
    const thead=document.createElement('thead');
    const trHead=document.createElement('tr');
    const etiquetasCampo={
      asegurado:'ASEGURADO',
      domicilio:'DOMICILIO',
      localidad:'LOCALIDAD',
      cp:'CP',
      patente:'PATENTE',
      marca_modelo:'MARCA/MODELO',
      año:'AÑO',
      motor:'MOTOR',
      chasis:'CHASIS',
      uso:'USO DEL VEHÍCULO',
      suma_asegurada:'SUMA ASEGURADA',
      cobertura:'COBERTURA'
    };
    ordenCampos.forEach(campo=>{
      const th=document.createElement('th');
      th.textContent=etiquetasCampo[campo]||campo;
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    tabla.appendChild(thead);

    const tbody=document.createElement('tbody');
    vehiculos.forEach((vehiculo)=>{
      const tr=document.createElement('tr');
      ordenCampos.forEach(campo=>{
        const td=document.createElement('td');
        const input=document.createElement('input');
        input.type='text';
        input.value=vehiculo[campo]??'';
        input.dataset.campo=campo;
        input.readOnly=true;
        td.appendChild(input);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    tabla.appendChild(tbody);
    tablaWrap.appendChild(tabla);
    b.appendChild(tablaWrap);

    const acciones=document.createElement('div');
    acciones.className='excel-proposal-actions';

    const cancelar=document.createElement('button');
    cancelar.type='button';
    cancelar.className='excel-proposal-cancel';
    cancelar.textContent='Cancelar';

    const editar=document.createElement('button');
    editar.type='button';
    editar.className='excel-proposal-edit';
    editar.textContent='Editar';

    const guardar=document.createElement('button');
    guardar.type='button';
    guardar.className='excel-proposal-save';
    guardar.textContent='Guardar';

    const estado=document.createElement('span');
    estado.className='excel-proposal-status';

    acciones.appendChild(cancelar);
    acciones.appendChild(editar);
    acciones.appendChild(guardar);
    acciones.appendChild(estado);
    b.appendChild(acciones);
    r.appendChild(b);
    c.appendChild(r);

    cancelar.addEventListener('click',()=>{
      r.remove();
    });

    editar.addEventListener('click',()=>{
      tabla.querySelectorAll('input[data-campo]').forEach(input=>input.readOnly=false);
      editar.disabled=true;
      estado.textContent='Modo edición activo.';
    });

    guardar.addEventListener('click',async()=>{
      if(guardar.disabled)return;
      const filas=[];
      tbody.querySelectorAll('tr').forEach(tr=>{
        const fila={};
        tr.querySelectorAll('input[data-campo]').forEach(input=>{
          fila[input.dataset.campo]=input.value.trim();
        });
        filas.push(fila);
      });

      guardar.disabled=true;
      editar.disabled=true;
      estado.textContent='Validando…';
      try{
        const libroDest=String(selector.value);
        const avisosAcum=[];
        for(let i=0;i<filas.length;i++){
          const valResp=await fetch('/api/validar-excel-fila',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            credentials:'same-origin',
            body:JSON.stringify({campos:filas[i],libro_id:libroDest})
          });
          const val=await leerJsonSeguro(valResp);
          if(val.errores&&val.errores.length){
            throw Error(`Fila ${i+1}: ${val.errores.join(' ')}`);
          }
          if(val.campos&&typeof val.campos==='object'){
            Object.assign(filas[i],val.campos);
          }
          if(val.avisos&&val.avisos.length){
            avisosAcum.push(`Fila ${i+1}: ${val.avisos.join(' ')}`);
          }
        }
        if(avisosAcum.length){
          const seguir=confirm(avisosAcum.join('\n')+'\n\n¿Guardar de todas formas?');
          if(!seguir){
            estado.textContent=avisosAcum[0];
            guardar.disabled=false;
            editar.disabled=false;
            return;
          }
        }
        estado.textContent='Guardando…';
        const resp=await fetch('/api/excel/agregar-fila',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          credentials:'same-origin',
          body:JSON.stringify({
            filas,
            libro_id:libroDest,
            tipo_propuesta:'flota'
          })
        });
        const d=await leerJsonSeguro(resp);
        if(!resp.ok||d.ok===false)throw Error(d.error||'No se pudo guardar la flota.');
        estado.textContent=`Guardado correctamente: ${d.filas_agregadas||filas.length} fila(s).`;
        estado.classList.add('success');
        guardar.textContent='Guardado';
      }catch(e){
        estado.textContent=e?.message||'No se pudo guardar la flota.';
        guardar.disabled=false;
        editar.disabled=false;
      }
    });
    return;
  }

  const libroId=libroIdInicial;
  const ordenAsegurado=['ASEGURADO','NUMERO','VEHICULO','PATENTE','ENVIOS YA','CIA','MEDIO DE PAGO','CP','MAIL'];
  const ordenFlota=['patente','marca','modelo','año','motor','chasis','uso','suma_asegurada','cobertura'];
  const orden=libroId==='2'?ordenFlota:ordenAsegurado;
  const campos=[];
  orden.forEach(k=>{if(Object.prototype.hasOwnProperty.call(propuesta,k))campos.push([k,String(propuesta[k]??'')])});
  Object.keys(propuesta).forEach(k=>{
    if(k!=='LIBRO_ID'&&!orden.includes(k)&&!campos.some(([clave])=>clave===k))campos.push([k,String(propuesta[k]??'')]);
  });
  const r=document.createElement('div');
  r.className='msg assistant';
  const b=document.createElement('div');
  b.className='bubble excel-proposal';
  const titulo=document.createElement('div');
  titulo.className='excel-proposal-title';
  titulo.textContent='Registro detectado para Excel';
  b.appendChild(titulo);
  const ayuda=document.createElement('div');
  ayuda.className='excel-proposal-help';
  ayuda.textContent='Revisá los campos. Los vacíos quedan así hasta que los completes antes de guardar.';
  b.appendChild(ayuda);
  const form=document.createElement('div');
  form.className='excel-proposal-fields';
  campos.forEach(([clave,valor])=>{
    const label=document.createElement('label');
    label.className='excel-proposal-field';
    const span=document.createElement('span');
    span.textContent=clave;
    const input=document.createElement('input');
    input.type='text';
    input.value=valor;
    input.dataset.campo=clave;
    label.appendChild(span);
    label.appendChild(input);
    form.appendChild(label);
  });
  b.appendChild(form);
  const acciones=document.createElement('div');
  acciones.className='excel-proposal-actions';
  const guardar=document.createElement('button');
  guardar.type='button';
  guardar.className='excel-proposal-save';
  guardar.textContent='Guardar en Excel';
  const pendienteBtn=document.createElement('button');
  pendienteBtn.type='button';
  pendienteBtn.className='excel-proposal-save';
  pendienteBtn.style.background='transparent';
  pendienteBtn.style.color='inherit';
  pendienteBtn.style.border='1px solid rgba(127,127,127,.3)';
  pendienteBtn.textContent='Dejar pendiente';
  const estado=document.createElement('span');
  estado.className='excel-proposal-status';
  acciones.appendChild(guardar);
  acciones.appendChild(pendienteBtn);
  acciones.appendChild(estado);
  pendienteBtn.addEventListener('click',async()=>{
    const valores={};
    form.querySelectorAll('input[data-campo]').forEach(input=>{valores[input.dataset.campo]=input.value.trim()});
    if(window.crearPendiente){
      await window.crearPendiente('excel', valores.ASEGURADO||'Registro Excel', {campos:valores, preview:Object.entries(valores).map(([k,v])=>k+': '+v).join(' · ')});
      pendienteBtn.textContent='En pendientes';
      pendienteBtn.disabled=true;
    }
  });
  b.appendChild(acciones);
  r.appendChild(b);
  c.appendChild(r);

  guardar.addEventListener('click',async()=>{
    if(guardar.disabled)return;
    const valores={};
    form.querySelectorAll('input[data-campo]').forEach(input=>{
      valores[input.dataset.campo]=input.value.trim();
    });
    if(!valores.ASEGURADO){
      estado.textContent='Completá ASEGURADO antes de guardar.';
      return;
    }
    if(!valores.NUMERO&&!valores.PATENTE){
      estado.textContent='Completá NUMERO o PATENTE antes de guardar.';
      return;
    }
    guardar.disabled=true;
    estado.textContent='Validando…';
    try{
      // P1.6 — cablear /api/validar-excel-fila antes de persistir
      const valResp=await fetch('/api/validar-excel-fila',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        credentials:'same-origin',
        body:JSON.stringify({campos:valores,libro_id:libroId})
      });
      const val=await leerJsonSeguro(valResp);
      if(val.errores&&val.errores.length){
        estado.textContent=val.errores.join(' ');
        guardar.disabled=false;
        return;
      }
      if(val.campos&&typeof val.campos==='object'){
        Object.assign(valores,val.campos);
        form.querySelectorAll('input[data-campo]').forEach(input=>{
          if(Object.prototype.hasOwnProperty.call(valores,input.dataset.campo)){
            input.value=valores[input.dataset.campo];
          }
        });
      }
      if(val.avisos&&val.avisos.length){
        const seguir=confirm(val.avisos.join('\n')+'\n\n¿Guardar de todas formas?');
        if(!seguir){
          estado.textContent=val.avisos.join(' ');
          guardar.disabled=false;
          return;
        }
      }
      estado.textContent='Guardando…';
      const resp=await fetch('/api/excel/agregar-fila',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        credentials:'same-origin',
        body:JSON.stringify({campos:valores,libro_id:libroId})
      });
      const d=await leerJsonSeguro(resp);
      if(!resp.ok||d.ok===false)throw Error(d.error||'No se pudo guardar el registro.');
      estado.textContent='Guardado correctamente en Excel.';
      estado.classList.add('success');
      guardar.textContent='Guardado';
      if(d.texto_envios_ya)mostrarTextoEnviosYa(d.texto_envios_ya);
    }catch(e){
      estado.textContent=e?.message||'No se pudo guardar.';
      guardar.disabled=false;
    }
  });
}

function mostrarPropuestaMetadato(propuesta){
  const c=document.getElementById('chat');
  if(!c||!propuesta||typeof propuesta!=='object')return;
  const r=document.createElement('div');
  r.className='msg assistant';
  const b=document.createElement('div');
  b.className='bubble metadata-proposal';

  const titulo=document.createElement('div');
  titulo.className='metadata-proposal-title';
  titulo.textContent='Dato reutilizable detectado';
  b.appendChild(titulo);

  const ayuda=document.createElement('div');
  ayuda.className='metadata-proposal-help';
  ayuda.textContent='La IA propone guardar sólo este dato puntual como ficha. Revisalo y confirmá antes de guardarlo.';
  b.appendChild(ayuda);

  const campos=document.createElement('div');
  campos.className='metadata-proposal-fields';

  const labelTitulo=document.createElement('label');
  labelTitulo.className='metadata-proposal-field';
  const spanTitulo=document.createElement('span');
  spanTitulo.textContent='TÍTULO';
  const inputTitulo=document.createElement('input');
  inputTitulo.type='text';
  inputTitulo.value=String(propuesta.titulo??'');
  inputTitulo.dataset.campo='titulo';
  labelTitulo.appendChild(spanTitulo);
  labelTitulo.appendChild(inputTitulo);

  const labelContenido=document.createElement('label');
  labelContenido.className='metadata-proposal-field';
  const spanContenido=document.createElement('span');
  spanContenido.textContent='DATO';
  const inputContenido=document.createElement('textarea');
  inputContenido.rows=4;
  inputContenido.value=String(propuesta.contenido??'');
  inputContenido.dataset.campo='contenido';
  labelContenido.appendChild(spanContenido);
  labelContenido.appendChild(inputContenido);

  campos.appendChild(labelTitulo);
  campos.appendChild(labelContenido);
  b.appendChild(campos);

  const acciones=document.createElement('div');
  acciones.className='metadata-proposal-actions';
  const guardar=document.createElement('button');
  guardar.type='button';
  guardar.className='metadata-proposal-save';
  guardar.textContent='Guardar metadato';
  const estado=document.createElement('span');
  estado.className='metadata-proposal-status';
  acciones.appendChild(guardar);
  acciones.appendChild(estado);
  b.appendChild(acciones);

  r.appendChild(b);
  c.appendChild(r);

  guardar.addEventListener('click',async()=>{
    if(guardar.disabled)return;
    const titulo=inputTitulo.value.trim();
    const contenido=inputContenido.value.trim();
    if(!titulo||!contenido){
      estado.textContent='Completá título y dato.';
      return;
    }
    guardar.disabled=true;
    estado.textContent='Guardando…';
    try{
      const resp=await fetch('/api/metadatos',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        credentials:'same-origin',
        body:JSON.stringify({titulo,contenido})
      });
      const d=await leerJsonSeguro(resp);
      if(!resp.ok||d.ok===false)throw Error(d.error||'No se pudo guardar el metadato.');
      estado.textContent='Metadato guardado correctamente.';
      estado.classList.add('success');
      guardar.textContent='Guardado';
    }catch(e){
      estado.textContent=e?.message||'No se pudo guardar.';
      guardar.disabled=false;
    }
  });
}

const COMANDOS_CHAT=[
  {
    comando:'/guardar asegurado',
    descripcion:'Cargar un asegurado en la planilla con campos en orden fijo.',
    plantilla:'/guardar asegurado (asegurado) (numero) (vehiculo) (patente) (cia) (medio de pago) (cp) (mail)'
  },
  {
    comando:'/flota',
    descripcion:'Cargar datos de una póliza para completar una flota',
    plantilla:'/flota'
  },
  {
    comando:'/coti',
    descripcion:'Generar una cotización rápida. Formato: /coti CIA COBERTURA SUMA PREMIO',
    plantilla:'/coti CIA COBERTURA SUMA PREMIO'
  },
  {
    comando:'/envios ya',
    descripcion:'Generar el texto para cargar el asegurado en Envíos Ya, buscando por patente.',
    plantilla:'/envios ya (patente)'
  }
];
function ejecutarClickComando(cmd,input){
  if(cmd.comando==='/guardar asegurado'){
    input.value='';
    indiceComando=-1;
    cerrarMenuComandos();
    size();
    mostrarPropuestaExcel({
      LIBRO_ID:'1',
      ASEGURADO:'',NUMERO:'',VEHICULO:'',PATENTE:'',
      'ENVIOS YA':'',CIA:'','MEDIO DE PAGO':'',CP:'',MAIL:''
    });
    return;
  }
  input.value=cmd.plantilla;
  indiceComando=-1;
  cerrarMenuComandos();
  size();
  input.focus();
}

let indiceComando=-1;

function obtenerMenuComandos(){
  let menu=document.getElementById('chatCommandMenu');
  if(menu)return menu;
  const wrap=document.querySelector('.composer-wrap');
  if(!wrap)return null;
  menu=document.createElement('div');
  menu.id='chatCommandMenu';
  menu.className='chat-command-menu';
  menu.hidden=true;
  wrap.appendChild(menu);
  return menu;
}

function cerrarMenuComandos(){
  const menu=document.getElementById('chatCommandMenu');
  if(menu){
    menu.hidden=true;
    menu.innerHTML='';
  }
  indiceComando=-1;
}

function actualizarMenuComandos(){
  const input=document.getElementById('mensaje');
  const menu=obtenerMenuComandos();
  if(!input||!menu)return;
  const valor=input.value;
  const inicio=valor.trimStart();
  if(!inicio.startsWith('/')){
    cerrarMenuComandos();
    return;
  }
  const filtro=inicio.slice(1).toLowerCase();
  const disponibles=COMANDOS_CHAT.filter(x=>x.comando.slice(1).toLowerCase().startsWith(filtro));
  if(!disponibles.length){
    cerrarMenuComandos();
    return;
  }
  menu.innerHTML='';
  disponibles.forEach((cmd,index)=>{
    const item=document.createElement('button');
    item.type='button';
    item.className='chat-command-item'+(index===indiceComando?' active':'');
    item.dataset.index=String(index);
    item.innerHTML='<strong>'+esc(cmd.comando)+'</strong><small>'+esc(cmd.descripcion)+'</small>';
    item.addEventListener('mousedown',e=>e.preventDefault());
    item.addEventListener('click',()=>{
      ejecutarClickComando(cmd,input);
    });
    menu.appendChild(item);
  });
  menu.hidden=false;
}

function navegarMenuComandos(direccion){
  const input=document.getElementById('mensaje');
  const menu=obtenerMenuComandos();
  if(!input||!menu||menu.hidden)return false;
  const valor=input.value.trimStart();
  if(!valor.startsWith('/'))return false;
  const filtro=valor.slice(1).toLowerCase();
  const disponibles=COMANDOS_CHAT.filter(x=>x.comando.slice(1).toLowerCase().startsWith(filtro));
  if(!disponibles.length)return false;
  indiceComando=(indiceComando+direccion+disponibles.length)%disponibles.length;
  menu.querySelectorAll('.chat-command-item').forEach((item,index)=>{
    item.classList.toggle('active',index===indiceComando);
  });
  return true;
}

function seleccionarComandoActual(){
  const input=document.getElementById('mensaje');
  const menu=obtenerMenuComandos();
  if(!input||!menu||menu.hidden)return false;
  const valor=input.value.trimStart();
  if(!valor.startsWith('/'))return false;
  const filtro=valor.slice(1).toLowerCase();
  const disponibles=COMANDOS_CHAT.filter(x=>x.comando.slice(1).toLowerCase().startsWith(filtro));
  if(!disponibles.length)return false;
  const cmd=disponibles[indiceComando>=0?indiceComando:0];
  input.value=cmd.plantilla;
  cerrarMenuComandos();
  size();
  input.focus();
  return true;
}

function mostrarMenuComandosCompleto(){
  const input=document.getElementById('mensaje');
  const menu=obtenerMenuComandos();
  if(!input||!menu)return;
  indiceComando=-1;
  menu.innerHTML='';
  COMANDOS_CHAT.forEach((cmd,index)=>{
    const item=document.createElement('button');
    item.type='button';
    item.className='chat-command-item'+(index===indiceComando?' active':'');
    item.dataset.index=String(index);
    item.innerHTML='<strong>'+esc(cmd.comando)+'</strong><small>'+esc(cmd.descripcion)+'</small>';
    item.addEventListener('mousedown',e=>e.preventDefault());
    item.addEventListener('click',()=>{
      ejecutarClickComando(cmd,input);
    });
    menu.appendChild(item);
  });
  menu.hidden=false;
  input.focus();
}

function toggleMenuComandos(){
  const menu=obtenerMenuComandos();
  if(!menu)return;
  if(!menu.hidden){
    cerrarMenuComandos();
    return;
  }
  mostrarMenuComandosCompleto();
}

async function enviarMensaje(){
  const i=document.getElementById('mensaje'),b=document.querySelector('.send'),pdf=document.getElementById('pdfInput');
  if(!i||enviandoMensaje)return;
  const t=i.value.trim(),archivo=pdf?.files?.[0]||null;
  if(!t&&!archivo)return;
  enviandoMensaje=true;
  if(b)b.disabled=true;
  const c=chatContainer();
  // Si el usuario estaba siguiendo la conversación, al terminar posicionamos
  // al inicio de la respuesta de Sofia. Si se fue a leer mensajes anteriores,
  // no lo sacamos de ahí.
  const seguirConversacion=isNearBottom(c);
  try{
    if(!currentChatId){await nuevoChat();}
    const historial=historialParaApi();
    document.getElementById('chatWelcome')?.remove();try{document.getElementById('chat')?.classList.remove('history-empty')}catch(_){};
  try{document.getElementById('chat')?.classList.remove('history-empty')}catch(_){};
    add('user',(archivo?'📎 '+archivo.name+'\n':'')+(t||'Analizá este PDF.'));
    i.value='';size();
    if(seguirConversacion)scrollToBottom(false);
    const thinking=add('assistant','<span class="typing"><i></i><i></i><i></i></span>',true);
    // No secuestrar el scroll mientras "piensa": solo un leve ajuste si el usuario seguía abajo.
    if(seguirConversacion)scrollToMessageStart(thinking,false);
    try{
      const fd=new FormData();
      fd.append('mensaje',t);
      fd.append('historial',JSON.stringify(historial));
      fd.append('chat_id',String(currentChatId||''));
      if(archivo)fd.append('pdf',archivo,archivo.name);
      const r=await fetch('/api/chat',{method:'POST',body:fd,credentials:'same-origin'});
      const d=await leerJsonSeguro(r);
      if(!r.ok||d.ok===false)throw Error(d.error||'No se pudo consultar el asistente.');
      currentChatId=d.chat_id||currentChatId;
      const texto=d.respuesta||'No recibí una respuesta.';
      const bubble=thinking.querySelector('.bubble');
      bubble.innerHTML=fmt(texto);
      addCopyButton(bubble,texto);
      if(d.propuesta_excel)mostrarPropuestaExcel(d.propuesta_excel);
      if(d.propuesta_metadato)mostrarPropuestaMetadato(d.propuesta_metadato);
      if(d.tabulado_flota)mostrarTabuladoFlota(d.tabulado_flota);
      if(d.texto_envios_ya)mostrarTextoEnviosYa(d.texto_envios_ya);
      if(pdf)pdf.value='';
      mostrarPdf(null);
      try{await cargarListaChats()}catch(_){}
    }catch(e){
      const mensaje=e?.message||'No se pudo procesar la consulta. Intentá nuevamente.';
      thinking.querySelector('.bubble').innerHTML='<p>'+esc(mensaje)+'</p>';
    }
    // Al finalizar: viewport al comienzo de la respuesta de Sofia (no al último renglón).
    if(seguirConversacion)scrollToMessageStart(thinking,true);
  }finally{
    enviandoMensaje=false;
    if(b)b.disabled=false;
    i.focus();
  }
}
async function initChat(){
  const i=document.getElementById('mensaje');
  if(!i)return;
  wireWelcomeWorkflows(document);try{const h=document.getElementById('chat');if(h&&h.querySelector('#chatWelcome')){h.classList.add('history-empty');h.scrollTop=0}}catch(_){};

  i.oninput=()=>{
    size();
    actualizarMenuComandos();
  };

  i.onkeydown=e=>{
    if(e.key==='ArrowDown'){
      if(navegarMenuComandos(1)){e.preventDefault();return}
    }
    if(e.key==='ArrowUp'){
      if(navegarMenuComandos(-1)){e.preventDefault();return}
    }
    if(e.key==='Escape'){
      cerrarMenuComandos();
      return;
    }
    if(e.key==='Enter'&&!e.shiftKey){
      // Si el menú está abierto, Enter solo completa el comando cuando el
      // usuario todavía está escribiendo el comando (por ejemplo "/flo").
      // Si ya hay texto después de /flota, Enter debe enviar el mensaje.
      const valorActual=i.value.trimStart();
      const menu=document.getElementById('chatCommandMenu');
      const menuAbierto=menu&&!menu.hidden;
      const esSoloComando=/^\/[^\s]+$/.test(valorActual);
      const esComandoConTexto=/^\/[^\s]+\s+.+/s.test(valorActual);
      if(menuAbierto && !esComandoConTexto && esSoloComando && seleccionarComandoActual()){
        e.preventDefault();
        return;
      }
      e.preventDefault();
      enviarMensaje();
    }
  };

  const pdf=document.getElementById('pdfInput');
  if(pdf)pdf.addEventListener('change',()=>{
    const file=pdf.files?.[0];
    if(file){
      if(!file.name.toLowerCase().endsWith('.pdf')){
        if(window.showToast)showToast('Solo podés adjuntar archivos PDF.','warning');else alert('Solo podés adjuntar archivos PDF.');
        pdf.value='';
        return;
      }
      if(file.size>20*1024*1024){
        if(window.showToast)showToast('El PDF supera el límite de 20 MB.','warning');else alert('El PDF supera el límite de 20 MB.');
        pdf.value='';
        return;
      }
      mostrarPdf(file);
    }
  });

  document.addEventListener('click',e=>{
    const menu=document.getElementById('chatCommandMenu');
    if(menu&&!menu.hidden&&!e.target.closest('#chatCommandMenu')&&!e.target.closest('#slashBtn')&&e.target!==i){
      cerrarMenuComandos();
    }
  });

  const slashBtn=document.getElementById('slashBtn');
  if(slashBtn){
    slashBtn.addEventListener('click',e=>{
      e.preventDefault();
      e.stopPropagation();
      toggleMenuComandos();
    });
  }

  const r=await fetch('/api/chats',{credentials:'same-origin'});
  const d=await leerJsonSeguro(r);
  if(!r.ok||!d.ok)throw new Error(d.error||'No se pudo cargar el historial.');

  if(window.FORZAR_CHAT_NUEVO||!d.chats.length){
    const x=await fetch('/api/chats',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({titulo:'Nueva conversación'}),
      credentials:'same-origin'
    });
    const j=await leerJsonSeguro(x);
    if(j.ok)await abrirChat(j.id);
    window.FORZAR_CHAT_NUEVO=false;
  }else{
    await abrirChat(d.chats[0].id);
  }

  size();
  scroll();
}

async function buscar(q){const box=document.getElementById('resultadosBusqueda');if(!box)return;if(!q){box.innerHTML='<div class="empty"><b>Empezá a buscar</b><small>Los resultados aparecerán aquí.</small></div>';return}box.innerHTML='<div class="empty"><b>Buscando…</b></div>';try{const r=await fetch('/api/buscar?q='+encodeURIComponent(q)),d=await r.json();box.innerHTML=d.length?d.map(x=>`<div class="result"><b>${esc((x.extension||'FILE').replace('.','').toUpperCase())}</b><span><strong>${esc(x.nombre)}</strong><small>${esc(x.compania)} · ${esc(x.tamaño)} KB</small></span></div>`).join(''):'<div class="empty"><b>No encontramos coincidencias</b></div>'}catch{box.innerHTML='<div class="empty"><b>Error de búsqueda</b></div>'}}
function mostrarPdf(file){const box=document.getElementById('pdfAdjunto'),name=document.getElementById('pdfNombre');if(!box||!name)return;if(file){name.textContent=file.name;box.hidden=false}else{box.hidden=true;name.textContent=''}}
function quitarPdf(){const input=document.getElementById('pdfInput');if(input)input.value='';mostrarPdf(null)}
document.addEventListener('DOMContentLoaded',()=>{const s=document.getElementById('buscadorCompanias');if(s){let t;s.oninput=()=>{clearTimeout(t);t=setTimeout(()=>buscar(s.value.trim()),220)}}});

// Menú Cias integrado en la sidebar.
document.addEventListener('DOMContentLoaded',()=>{
  const toggle=document.getElementById('ciasToggle');
  const submenu=document.getElementById('ciasSubmenu');
  if(!toggle||!submenu)return;

  // Cias siempre inicia cerrado. El estado real se controla con hidden,
  // por lo que el submenu deja de ocupar espacio y no recibe interacción.
  toggle.setAttribute('aria-expanded','false');
  submenu.hidden=true;

  toggle.addEventListener('click',()=>{
    const abierto=toggle.getAttribute('aria-expanded')==='true';
    const nuevoEstado=!abierto;
    toggle.setAttribute('aria-expanded',String(nuevoEstado));
    submenu.hidden=!nuevoEstado;
  });
});

function inicializarFechaGlobal(){const e=document.getElementById('fechaHoy');if(!e)return;const actualizar=()=>{e.textContent=new Date().toLocaleDateString('es-AR',{weekday:'long',day:'numeric',month:'long'}).replace(/^./,x=>x.toUpperCase())};actualizar();const ahora=new Date(),manana=new Date(ahora);manana.setHours(24,0,0,0);setTimeout(()=>{actualizar();setInterval(actualizar,86400000)},manana-ahora)}
document.addEventListener('DOMContentLoaded',inicializarFechaGlobal);

/* ==========================================================
   TANDA 1 — Preferencias de apariencia + feedback toast
   ========================================================== */
(function(){
  const FONT_STEPS = ['sm','md','lg','xl'];
  const FONT_LABELS = {sm:'Pequeño',md:'Normal',lg:'Grande',xl:'Muy grande'};
  const THEME_KEY = 'oficinaia_theme';
  const FONT_KEY = 'oficinaia_font';

  function getTheme(){
    const t = localStorage.getItem(THEME_KEY);
    if(t === 'light' || t === 'dark') return t;
    if(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark';
    return 'light';
  }

  /* Tanda D — tema SOLO por data-theme (tokens en CSS). Sin body.style. */
  const THEME_PROPS = ['--navy','--teal','--bg','--sidebar-bg','--button-bg','--ink','--muted','--soft','--line','--tealbg','--surface','--surface-2','--surface-3','--hover','--card','--panel'];

  function applyTheme(theme){
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.style.colorScheme = theme === 'dark' ? 'dark' : 'light';
    // Limpiar residuos legacy de body.style (tandas anteriores)
    const body = document.body;
    if(body){
      THEME_PROPS.forEach(p => body.style.removeProperty(p));
    }
    const btn = document.getElementById('themeToggle');
    if(btn){
      btn.textContent = theme === 'dark' ? '☀' : '☾';
      btn.title = theme === 'dark' ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro';
      btn.setAttribute('aria-label', btn.title);
    }
  }

  function setTheme(theme){
    localStorage.setItem(THEME_KEY, theme);
    applyTheme(theme);
  }

  function toggleTheme(){
    const next = getTheme() === 'dark' ? 'light' : 'dark';
    setTheme(next);
  }

  function getFont(){
    const f = localStorage.getItem(FONT_KEY) || 'md';
    return FONT_STEPS.includes(f) ? f : 'md';
  }

  function applyFont(size){
    document.documentElement.setAttribute('data-font-size', size);
    // Controles solo − / + (sin etiqueta de tamaño)
    const dec = document.getElementById('fontDec');
    const inc = document.getElementById('fontInc');
    if(dec) dec.disabled = size === FONT_STEPS[0];
    if(inc) inc.disabled = size === FONT_STEPS[FONT_STEPS.length - 1];
  }

  function setFont(size){
    if(!FONT_STEPS.includes(size)) return;
    localStorage.setItem(FONT_KEY, size);
    applyFont(size);
  }

  function changeFont(delta){
    const cur = getFont();
    const i = FONT_STEPS.indexOf(cur);
    const next = FONT_STEPS[Math.max(0, Math.min(FONT_STEPS.length - 1, i + delta))];
    setFont(next);
  }

  window.showToast = function(message, type){
    const host = document.getElementById('toastHost');
    if(!host) return;
    const el = document.createElement('div');
    el.className = 'toast ' + (type || 'info');
    el.setAttribute('role', 'status');
    el.textContent = message;
    host.appendChild(el);
    const hide = () => {
      el.classList.add('leaving');
      setTimeout(() => el.remove(), 200);
    };
    setTimeout(hide, type === 'error' ? 4500 : 2800);
    el.addEventListener('click', hide);
  };

  function initAppearance(){
    applyTheme(getTheme());
    applyFont(getFont());
    const themeBtn = document.getElementById('themeToggle');
    if(themeBtn) themeBtn.addEventListener('click', toggleTheme);
    const dec = document.getElementById('fontDec');
    const inc = document.getElementById('fontInc');
    if(dec) dec.addEventListener('click', () => changeFont(-1));
    if(inc) inc.addEventListener('click', () => changeFont(1));

    // Si el usuario no eligió tema manualmente, seguir cambios del sistema
    if(window.matchMedia){
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      const onChange = () => {
        if(localStorage.getItem(THEME_KEY) === null){
          applyTheme(mq.matches ? 'dark' : 'light');
        }
      };
      if(mq.addEventListener) mq.addEventListener('change', onChange);
      else if(mq.addListener) mq.addListener(onChange);
    }
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initAppearance);
  } else {
    initAppearance();
  }
})();


/* Sidebar collapse / rail */
(function(){
  const KEY='oficinaia_sidebar';
  function apply(collapsed){
    document.documentElement.setAttribute('data-sidebar', collapsed ? 'collapsed' : 'expanded');
    const btn=document.getElementById('sidebarToggle');
    if(btn){
      btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      btn.title = collapsed ? 'Expandir menú' : 'Contraer menú';
    }
    try{localStorage.setItem(KEY, collapsed ? 'collapsed' : 'expanded')}catch(_){}
  }
  function init(){
    const btn=document.getElementById('sidebarToggle');
    if(!btn)return;
    let collapsed=false;
    try{collapsed=localStorage.getItem(KEY)==='collapsed'}catch(_){}
    apply(collapsed);
    btn.addEventListener('click',()=>{
      const now=document.documentElement.getAttribute('data-sidebar')==='collapsed';
      apply(!now);
    });
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);
  else init();
})();


/* P2.12 / Tanda C — Sheet de chats en mobile */
(function(){
  function abrirSheetChats(){
    const sheet=document.getElementById('chatListSheet');
    const body=document.getElementById('chatListSheetBody');
    if(!sheet||!body)return;
    body.innerHTML='';
    const source=document.getElementById('chatList');
    if(source){
      // Clonar filas visibles del listado desktop
      source.querySelectorAll('.chat-item-row').forEach(row=>{
        const clone=row.cloneNode(true);
        const btn=clone.querySelector('.chat-item');
        if(btn){
          const id=Number(clone.dataset.chatId);
          btn.onclick=()=>{abrirChat(id);cerrarSheetChats();};
        }
        clone.querySelectorAll('.chat-rename,.chat-delete').forEach(a=>a.remove());
        body.appendChild(clone);
      });
      if(!body.children.length){
        body.innerHTML='<div class="chat-empty">Sin conversaciones.</div>';
      }
    }
    sheet.hidden=false;
    document.body.classList.add('sheet-open');
  }
  function cerrarSheetChats(){
    const sheet=document.getElementById('chatListSheet');
    if(sheet)sheet.hidden=true;
    document.body.classList.remove('sheet-open');
  }
  window.cerrarSheetChats=cerrarSheetChats;
  function init(){
    const openBtn=document.getElementById('chatListOpen');
    if(openBtn)openBtn.addEventListener('click',abrirSheetChats);
    document.getElementById('chatListSheet')?.querySelectorAll('[data-close-sheet]').forEach(el=>{
      el.addEventListener('click',cerrarSheetChats);
    });
    document.getElementById('chatListSheetNew')?.addEventListener('click',()=>{
      nuevoChat();
      cerrarSheetChats();
    });
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);
  else init();
})();
