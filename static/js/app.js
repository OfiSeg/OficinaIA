async function leerJsonSeguro(response){
  const text=await response.text();
  let data=null;
  try{data=JSON.parse(text)}catch{
    if(response.status===401||response.redirected)throw new Error('La sesión expiró. Volvé a iniciar sesión.');
    if(response.status>=500)throw new Error('El servidor interrumpió esta consulta. Probá enviar el mensaje nuevamente; el chat debería seguir funcionando.');
    throw new Error(`No se pudo procesar la respuesta del servidor (${response.status}).`);
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
  }else{
    x.textContent=String(content??'');
  }
  r.appendChild(x);
  c.appendChild(r);
  return r;
}

function htmlWelcomeChat(variant){
  const sub = variant==='vacio'
    ? 'Empezá por una tarea concreta o escribí tu consulta abajo.'
    : 'Accesos para operaciones frecuentes. Podés completar el dato que falta y enviar.';
  return `<div id="chatWelcome" class="welcome">
  <strong>✦</strong>
  <h2>¿Qué necesitás resolver?</h2>
  <p>${sub}</p>
  <div class="workflow-grid" id="workflowGrid">
    <button type="button" class="workflow-card" data-fill="/flota "><b>Procesar una flota</b><small>Iniciá una flota y cargá vehículos, coberturas y datos para el Excel.</small></button>
    <button type="button" class="workflow-card" data-fill="¿En qué compañía puedo asegurar "><b>Buscar dónde emitir</b><small>Compará compañías según vehículo, año, uso o cobertura necesaria.</small></button>
    <button type="button" class="workflow-card" data-fill="¿Cuántas pólizas emití "><b>Consultar mi cartera</b><small>Conteos, fechas, compañías, vehículos y datos reales del Excel interno.</small></button>
    <button type="button" class="workflow-card" data-fill="Armame un mensaje de WhatsApp para el asegurado: "><b>Redactar para un asegurado</b><small>Prepará un mensaje claro y directo usando el contexto que le indiques.</small></button>
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
function historialParaApi(){const c=document.getElementById('chat');return c?[...c.querySelectorAll('.msg')].map(x=>({rol:x.classList.contains('user')?'user':'assistant',contenido:(x.querySelector('.bubble')?.textContent?.trim()||'').slice(0,2000)})).filter(x=>x.contenido).slice(-8):[]}
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
    const tagMap={flota:'Flota',coti:'Coti',alta:'Alta',envios:'Envío',mail:'Mail',whatsapp:'WA'};
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

// TANDA 5 — después de leer una póliza con /alta, se ofrecen dos caminos:
// tabulado (copiar/pegar) o guardar en Excel (reutiliza el formulario y el
// guardado que ya tiene /guardar asegurado).
function mostrarTabuladoAlta(texto){
  const c=document.getElementById('chat');
  if(!c||!texto)return;

  const r=document.createElement('div');
  r.className='msg assistant';
  const b=document.createElement('div');
  b.className='bubble tabulado-flota';

  const titulo=document.createElement('div');
  titulo.className='tabulado-flota-title';
  titulo.textContent='Fila lista para pegar en Excel';
  b.appendChild(titulo);

  const ayuda=document.createElement('div');
  ayuda.className='tabulado-flota-help';
  ayuda.textContent='Copiá el bloque y pegalo en la primera fila vacía. Las columnas están separadas por tabulador, así que Excel las va a acomodar solo.';
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

function mostrarOpcionesAltaAsegurado(_tabuladoInicial,camposGuardar){
  const c=document.getElementById('chat');
  if(!c||!camposGuardar||typeof camposGuardar!=='object')return;

  const valores={...camposGuardar};
  valores.LIBRO_ID=String(valores.LIBRO_ID||'1');
  // En el alta desde póliza el teléfono es SIEMPRE manual. NUMERO es la
  // columna histórica donde vive ese dato; TELEFONO queda como compatibilidad.
  valores.NUMERO='';
  valores.TELEFONO='';
  valores['ENVIOS YA']='';

  const r=document.createElement('div');
  r.className='msg assistant';
  const b=document.createElement('div');
  b.className='bubble alta-compact-card';

  const titulo=document.createElement('div');
  titulo.className='alta-compact-title';
  const refrescarTitulo=()=>{
    const nombre=String(valores.ASEGURADO||'').trim();
    titulo.textContent=nombre?`Alta detectada — ${nombre}`:'Alta detectada';
  };
  refrescarTitulo();
  b.appendChild(titulo);

  const resumen=document.createElement('div');
  resumen.className='alta-compact-summary';
  const resumenRefs={};
  const camposResumen=[
    ['VEHICULO','Vehículo'],
    ['PATENTE','Patente'],
    ['CIA','Compañía'],
    ['MEDIO DE PAGO','Medio de pago'],
    ['IMPORTE APROX','Precio'],
    ['EMITIDO DÍA:','Emisión']
  ];
  const valorVisible=(clave,valor)=>{
    const raw=String(valor??'').trim();
    if(!raw)return '—';
    if(clave==='IMPORTE APROX'){
      const n=Number(raw.replace(',','.'));
      if(Number.isFinite(n)){
        try{return new Intl.NumberFormat('es-AR',{style:'currency',currency:'ARS',maximumFractionDigits:2}).format(n)}catch(_){return raw}
      }
    }
    return raw;
  };
  camposResumen.forEach(([clave,label])=>{
    const item=document.createElement('div');
    item.className='alta-compact-item';
    const k=document.createElement('span');
    k.className='alta-compact-key';
    k.textContent=label;
    const v=document.createElement('strong');
    v.className='alta-compact-value';
    v.textContent=valorVisible(clave,valores[clave]);
    resumenRefs[clave]=v;
    item.appendChild(k);item.appendChild(v);resumen.appendChild(item);
  });
  b.appendChild(resumen);

  const telefonoWrap=document.createElement('label');
  telefonoWrap.className='alta-phone-field';
  const telefonoLabel=document.createElement('span');
  telefonoLabel.textContent='Teléfono';
  const telefonoInput=document.createElement('input');
  telefonoInput.type='text';
  telefonoInput.inputMode='tel';
  telefonoInput.autocomplete='off';
  telefonoInput.placeholder='Lo completás vos';
  telefonoInput.value='';
  telefonoInput.dataset.campo='NUMERO';
  const telefonoNota=document.createElement('small');
  telefonoNota.textContent='Manual · nunca se toma de la póliza';
  telefonoWrap.appendChild(telefonoLabel);
  telefonoWrap.appendChild(telefonoInput);
  telefonoWrap.appendChild(telefonoNota);
  b.appendChild(telefonoWrap);

  const detalles=document.createElement('div');
  detalles.className='alta-edit-panel';
  detalles.hidden=true;
  const editables=[
    ['ASEGURADO','Asegurado','text'],
    ['VEHICULO','Vehículo','text'],
    ['PATENTE','Patente','text'],
    ['CIA','Compañía','text'],
    ['MEDIO DE PAGO','Medio de pago','select'],
    ['CP','Código postal','text'],
    ['EMITIDO DÍA:','Día de emisión','text'],
    ['IMPORTE APROX','Precio','text'],
    ['MAIL','Mail','email']
  ];
  const inputs={};
  editables.forEach(([clave,label,tipo])=>{
    const wrap=document.createElement('label');
    wrap.className='alta-edit-field';
    const span=document.createElement('span');
    span.textContent=label;
    let input;
    if(tipo==='select'){
      input=document.createElement('select');
      [['','—'],['CUPONERA','CUPONERA'],['CBU','CBU'],['CREDITO','CREDITO']].forEach(([value,text])=>{
        const opt=document.createElement('option');
        opt.value=value;opt.textContent=text;
        if(String(valores[clave]||'').toUpperCase()===value)opt.selected=true;
        input.appendChild(opt);
      });
    }else{
      input=document.createElement('input');
      input.type=tipo;
      input.value=String(valores[clave]??'');
    }
    input.dataset.campo=clave;
    inputs[clave]=input;
    const sync=()=>{
      valores[clave]=input.value.trim();
      if(resumenRefs[clave])resumenRefs[clave].textContent=valorVisible(clave,valores[clave]);
      if(clave==='ASEGURADO')refrescarTitulo();
    };
    input.addEventListener('input',sync);
    input.addEventListener('change',sync);
    wrap.appendChild(span);wrap.appendChild(input);detalles.appendChild(wrap);
  });
  b.appendChild(detalles);

  const acciones=document.createElement('div');
  acciones.className='alta-compact-actions';
  const guardar=document.createElement('button');
  guardar.type='button';
  guardar.className='excel-proposal-save';
  guardar.textContent='Guardar en Excel';
  const editar=document.createElement('button');
  editar.type='button';
  editar.className='alta-secondary-btn';
  editar.textContent='Editar';
  const tabular=document.createElement('button');
  tabular.type='button';
  tabular.className='alta-secondary-btn';
  tabular.textContent='Tabulado';
  const estado=document.createElement('span');
  estado.className='excel-proposal-status';
  acciones.appendChild(guardar);
  acciones.appendChild(editar);
  acciones.appendChild(tabular);
  acciones.appendChild(estado);
  b.appendChild(acciones);

  // El tabulado vive AL FINAL de la misma ficha; no genera otro mensaje.
  const tabPanel=document.createElement('div');
  tabPanel.className='alta-inline-panel';
  tabPanel.hidden=true;
  const tabTitle=document.createElement('div');
  tabTitle.className='alta-inline-title';
  tabTitle.textContent='Fila tabulada';
  const tabPre=document.createElement('pre');
  tabPre.className='tabulado-flota-pre';
  const tabCopy=document.createElement('button');
  tabCopy.type='button';
  tabCopy.className='tabulado-flota-copy';
  tabCopy.textContent='Copiar';
  tabPanel.appendChild(tabTitle);tabPanel.appendChild(tabPre);tabPanel.appendChild(tabCopy);
  b.appendChild(tabPanel);

  const enviosPanel=document.createElement('div');
  enviosPanel.className='alta-inline-panel';
  enviosPanel.hidden=true;
  const enviosTitle=document.createElement('div');
  enviosTitle.className='alta-inline-title';
  enviosTitle.textContent='Envíos Ya';
  const enviosPre=document.createElement('pre');
  enviosPre.className='tabulado-flota-pre';
  const enviosCopy=document.createElement('button');
  enviosCopy.type='button';
  enviosCopy.className='tabulado-flota-copy';
  enviosCopy.textContent='Copiar';
  enviosPanel.appendChild(enviosTitle);enviosPanel.appendChild(enviosPre);enviosPanel.appendChild(enviosCopy);
  b.appendChild(enviosPanel);

  r.appendChild(b);
  c.appendChild(r);

  const recoger=()=>{
    Object.values(inputs).forEach(input=>{valores[input.dataset.campo]=input.value.trim()});
    valores.NUMERO=telefonoInput.value.trim();
    valores.TELEFONO='';
    valores['ENVIOS YA']='';
    return {...valores};
  };

  const filaTabulada=()=>{
    const v=recoger();
    const orden=['ASEGURADO','NUMERO','VEHICULO','PATENTE','ENVIOS YA','COMPAÑIA','MEDIO DE PAGO','CODIGO POSTAL','EMITIDO DÍA:','IMPORTE APROX','DE DONDE ','MAIL','TELEFONO'];
    const map={
      ASEGURADO:v.ASEGURADO||'',
      NUMERO:v.NUMERO||'',
      VEHICULO:v.VEHICULO||'',
      PATENTE:v.PATENTE||'',
      'ENVIOS YA':'',
      COMPAÑIA:v.CIA||'',
      'MEDIO DE PAGO':v['MEDIO DE PAGO']||'',
      'CODIGO POSTAL':v.CP||'',
      'EMITIDO DÍA:':v['EMITIDO DÍA:']||'',
      'IMPORTE APROX':v['IMPORTE APROX']||'',
      'DE DONDE ':'',
      MAIL:v.MAIL||'',
      TELEFONO:''
    };
    return orden.map(k=>String(map[k]??'')).join('\t');
  };

  editar.addEventListener('click',()=>{
    detalles.hidden=!detalles.hidden;
    editar.textContent=detalles.hidden?'Editar':'Cerrar edición';
    if(!detalles.hidden)inputs.ASEGURADO?.focus();
  });

  tabular.addEventListener('click',()=>{
    tabPre.textContent=filaTabulada();
    tabPanel.hidden=!tabPanel.hidden;
    tabular.textContent=tabPanel.hidden?'Tabulado':'Ocultar tabulado';
  });

  tabCopy.addEventListener('click',async()=>{
    tabPre.textContent=filaTabulada();
    try{await navigator.clipboard.writeText(tabPre.textContent);tabCopy.textContent='¡Copiado!';}
    catch(_){tabPre.focus();const sel=window.getSelection(),range=document.createRange();range.selectNodeContents(tabPre);sel.removeAllRanges();sel.addRange(range);document.execCommand('copy');tabCopy.textContent='¡Copiado!';}
    setTimeout(()=>{tabCopy.textContent='Copiar'},1600);
  });

  enviosCopy.addEventListener('click',async()=>{
    try{await navigator.clipboard.writeText(enviosPre.textContent);enviosCopy.textContent='¡Copiado!';}
    catch(_){enviosPre.focus();const sel=window.getSelection(),range=document.createRange();range.selectNodeContents(enviosPre);sel.removeAllRanges();sel.addRange(range);document.execCommand('copy');enviosCopy.textContent='¡Copiado!';}
    setTimeout(()=>{enviosCopy.textContent='Copiar'},1600);
  });

  guardar.addEventListener('click',async()=>{
    if(guardar.disabled)return;
    const payload=recoger();
    if(!payload.ASEGURADO){estado.textContent='Completá el asegurado.';return;}
    if(!payload.PATENTE){estado.textContent='Completá la patente.';return;}
    guardar.disabled=true;
    editar.disabled=true;
    estado.textContent='Validando…';
    try{
      const valResp=await fetch('/api/validar-excel-fila',{
        method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',
        body:JSON.stringify({campos:payload,libro_id:'1'})
      });
      const val=await leerJsonSeguro(valResp);
      if(val.errores&&val.errores.length)throw Error(val.errores.join(' '));
      if(val.campos&&typeof val.campos==='object')Object.assign(payload,val.campos);
      if(val.avisos&&val.avisos.length){
        const seguir=confirm(val.avisos.join('\n')+'\n\n¿Guardar de todas formas?');
        if(!seguir){guardar.disabled=false;editar.disabled=false;estado.textContent='';return;}
      }
      estado.textContent='Guardando…';
      const resp=await fetch('/api/excel/agregar-fila',{
        method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',
        body:JSON.stringify({campos:payload,libro_id:'1'})
      });
      const d=await leerJsonSeguro(resp);
      if(!resp.ok||d.ok===false)throw Error(d.error||'No se pudo guardar el registro.');

      guardar.textContent='✓ Guardado en Excel';
      estado.textContent='';
      detalles.hidden=true;
      editar.textContent='Editar';
      editar.disabled=true;
      telefonoInput.disabled=true;
      Object.values(inputs).forEach(input=>input.disabled=true);

      if(d.texto_envios_ya){
        enviosPre.textContent=d.texto_envios_ya;
        const btnEnvios=document.createElement('button');
        btnEnvios.type='button';
        btnEnvios.className='alta-secondary-btn';
        btnEnvios.textContent='Envíos Ya';
        btnEnvios.addEventListener('click',()=>{enviosPanel.hidden=!enviosPanel.hidden;btnEnvios.textContent=enviosPanel.hidden?'Envíos Ya':'Ocultar Envíos Ya';});
        acciones.insertBefore(btnEnvios,estado);
      }
    }catch(e){
      estado.textContent=e?.message||'No se pudo guardar.';
      guardar.disabled=false;
      editar.disabled=false;
    }
  });
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
    comando:'/mail',
    descripcion:'Enviar un correo desde OficinaIA indicando destinatario, asunto y mensaje. Podés adjuntar el archivo del turno actual.',
    plantilla:'/mail destinatario@correo.com asunto Asunto mensaje Mensaje'
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
  const i=document.getElementById('mensaje'),b=document.querySelector('.send'),pdf=document.getElementById('archivoInput');
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
    add('user',(archivo?'📎 '+archivo.name+'\n':'')+(t||'Analizá este archivo.'));
    // El archivo ya quedó capturado en la variable `archivo`. Limpiamos el
    // input y la pastilla visual AHORA, al enviar, para que el PDF no quede
    // pegado esperando la respuesta del servidor ni se reenvíe por accidente.
    if(archivo)quitarAdjunto();
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
      if(archivo)fd.append('archivo',archivo,archivo.name);
      const r=await fetch('/api/chat',{method:'POST',body:fd,credentials:'same-origin'});
      const d=await leerJsonSeguro(r);
      if(!r.ok||d.ok===false)throw Error(d.error||'No se pudo consultar el asistente.');
      currentChatId=d.chat_id||currentChatId;
      const texto=d.respuesta||'No recibí una respuesta.';
      const bubble=thinking.querySelector('.bubble');
      bubble.innerHTML=fmt(texto);
      if(d.propuesta_excel)mostrarPropuestaExcel(d.propuesta_excel);
      if(d.propuesta_metadato)mostrarPropuestaMetadato(d.propuesta_metadato);
      if(d.tabulado_flota)mostrarTabuladoFlota(d.tabulado_flota);
      if(d.tabulado_alta_asegurado||d.campos_guardar_alta_asegurado)mostrarOpcionesAltaAsegurado(d.tabulado_alta_asegurado,d.campos_guardar_alta_asegurado);
      if(d.texto_envios_ya)mostrarTextoEnviosYa(d.texto_envios_ya);
      if(pdf)pdf.value='';
      mostrarAdjunto(null);
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

  const pdf=document.getElementById('archivoInput');
  if(pdf)pdf.addEventListener('change',()=>{
    const file=pdf.files?.[0];
    if(file)validarYAdjuntarArchivo(file,pdf);
  });

  wireDragAndDropArchivo();

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
function mostrarAdjunto(file){const box=document.getElementById('archivoAdjunto'),name=document.getElementById('archivoNombre');if(!box||!name)return;if(file){name.textContent=file.name;box.hidden=false}else{box.hidden=true;name.textContent=''}}
function quitarAdjunto(){const input=document.getElementById('archivoInput');if(input)input.value='';mostrarAdjunto(null)}

// Validación única para un archivo adjuntado, ya sea por el botón de clip o
// por drag & drop: mismas reglas (PDF/TXT/imagen y su límite por tipo), mismo aviso al
// usuario y mismo destino final (#archivoInput), para no crear un segundo
// camino de lectura de PDF (Tanda 3).
function validarYAdjuntarArchivo(file,inputEl){
  const input=inputEl||document.getElementById('archivoInput');
  if(!file||!input)return false;
  const ext=(file.name.split('.').pop()||'').toLowerCase();
  const limites={pdf:20,txt:2,png:15,jpg:15,jpeg:15,webp:15};
  const limite=limites[ext];
  if(!limite){
    if(window.showToast)showToast('Podés adjuntar PDF, TXT, PNG, JPG, JPEG o WEBP.','warning');else alert('Formato de archivo no compatible.');
    input.value='';return false;
  }
  if(file.size>limite*1024*1024){
    if(window.showToast)showToast(`El archivo supera el límite de ${limite} MB.`,`warning`);else alert(`El archivo supera el límite de ${limite} MB.`);
    input.value='';return false;
  }
  try{const transferencia=new DataTransfer();transferencia.items.add(file);input.files=transferencia.files}catch(_){}
  mostrarAdjunto(file);return true;
}

// Arrastrar y soltar un archivo directamente sobre el chat (Tanda 3). No
// reemplaza al botón de clip: es una segunda forma de hacer lo mismo,
// usando el mismo input y el mismo procesamiento de adjuntos que ya existe.
//
// FIX: el overlay ("Soltá el archivo acá") se quedaba pegado en
// pantalla cuando el drag terminaba fuera de la zona del chat (se soltaba
// en otra parte de la página, se cancelaba con Esc, o el mouse salía de la
// ventana del navegador arrastrando algo) porque el contador de
// dragenter/dragleave nunca volvía a cero en esos casos. Ahora se usa
// relatedTarget para decidir si realmente se salió de la zona, y se
// agregan redes de seguridad a nivel documento/ventana para ocultar el
// overlay pase lo que pase.
function wireDragAndDropArchivo(){
  const zona=document.getElementById('chatDropZone');
  const overlay=document.getElementById('chatDropOverlay');
  const pdf=document.getElementById('archivoInput');
  if(!zona||!overlay||!pdf)return;
  const contieneArchivo=e=>Array.from(e.dataTransfer?.types||[]).includes('Files');
  const ocultar=()=>{overlay.hidden=true};

  zona.addEventListener('dragenter',e=>{
    if(!contieneArchivo(e))return;
    e.preventDefault();
    overlay.hidden=false;
  });
  zona.addEventListener('dragover',e=>{
    if(!contieneArchivo(e))return;
    e.preventDefault();
    e.dataTransfer.dropEffect='copy';
  });
  zona.addEventListener('dragleave',e=>{
    if(!contieneArchivo(e))return;
    // relatedTarget es el elemento al que entra el mouse. Si sigue dentro
    // de la zona (pasó a un hijo interno), NO hay que ocultar el overlay;
    // sólo se oculta cuando realmente lo abandona.
    if(e.relatedTarget && zona.contains(e.relatedTarget))return;
    ocultar();
  });
  zona.addEventListener('drop',e=>{
    if(!contieneArchivo(e))return;
    e.preventDefault();
    ocultar();
    const archivo=e.dataTransfer.files?.[0];
    if(archivo)validarYAdjuntarArchivo(archivo,pdf);
  });

  // Redes de seguridad: el drag puede terminar sin que la zona reciba
  // ningún evento más (se soltó afuera, se canceló, se salió de la
  // ventana). Cualquiera de estos casos oculta el overlay igual.
  document.addEventListener('dragend',ocultar);
  document.addEventListener('drop',e=>{
    if(e.target!==zona && !zona.contains(e.target))ocultar();
  });
  document.addEventListener('dragleave',e=>{
    // Chrome dispara este evento con clientX/clientY en 0 cuando el drag
    // sale de la ventana del navegador por completo.
    if(e.clientX<=0 && e.clientY<=0)ocultar();
  });
  window.addEventListener('blur',ocultar);
  document.addEventListener('keydown',e=>{if(e.key==='Escape')ocultar()});
}

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
   Apariencia — tema + tipografía fija
   ========================================================== */
(function(){
  const THEME_KEY='oficinaia_theme';
  const DEFAULT_FONT=16;
  function getTheme(){const t=localStorage.getItem(THEME_KEY);if(t==='light'||t==='dark')return t;return window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}
  function applyTheme(theme){document.documentElement.setAttribute('data-theme',theme);document.documentElement.style.colorScheme=theme==='dark'?'dark':'light';const btn=document.getElementById('themeToggle');if(btn){btn.dataset.theme=theme;btn.title=theme==='dark'?'Cambiar a modo claro':'Cambiar a modo oscuro';btn.setAttribute('aria-label',btn.title)}}
  function setTheme(theme){localStorage.setItem(THEME_KEY,theme);applyTheme(theme)}
  function toggleTheme(){setTheme(getTheme()==='dark'?'light':'dark')}
  function getFont(){return DEFAULT_FONT}
  function viewportDensity(){const w=window.innerWidth||document.documentElement.clientWidth||1600;if(w>=1540||w<1050)return 1;if(w>=1360)return 0.84+((w-1360)/180)*0.16;if(w>=1180)return 0.76+((w-1180)/180)*0.08;return 0.74}
  function applyFont(){const general=getFont(),density=viewportDensity(),effective=(general/16)*density;document.documentElement.style.setProperty('--ui-font-size',general+'px');document.documentElement.style.setProperty('--viewport-density',String(density));document.documentElement.style.setProperty('--font-scale',String(effective));document.documentElement.style.setProperty('--sidebar-font-size',general+'px');document.documentElement.style.setProperty('--chat-font-size',general+'px')}
  window.showToast=function(message,type){const host=document.getElementById('toastHost');if(!host)return;const el=document.createElement('div');el.className='toast '+(type||'info');el.setAttribute('role','status');el.textContent=message;host.appendChild(el);const hide=()=>{el.classList.add('leaving');setTimeout(()=>el.remove(),200)};setTimeout(hide,type==='error'?4500:2800);el.addEventListener('click',hide)};
  function initAppearance(){applyTheme(getTheme());applyFont();document.getElementById('themeToggle')?.addEventListener('click',toggleTheme);let resizeTimer=null;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(applyFont,80)},{passive:true});if(window.matchMedia){const mq=window.matchMedia('(prefers-color-scheme: dark)');const onChange=()=>{if(localStorage.getItem(THEME_KEY)===null)applyTheme(mq.matches?'dark':'light')};if(mq.addEventListener)mq.addEventListener('change',onChange);else if(mq.addListener)mq.addListener(onChange)}}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initAppearance);else initAppearance();
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


/* Chat desktop: historial plegable dentro de la ventana flotante. */
(function(){
  const KEY='oficinaia_chat_list';
  function apply(collapsed){
    document.documentElement.setAttribute('data-chat-list', collapsed ? 'collapsed' : 'expanded');
    const btn=document.getElementById('chatListToggle');
    if(btn){
      btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      btn.title=collapsed ? 'Mostrar conversaciones' : 'Ocultar conversaciones';
    }
    try{localStorage.setItem(KEY,collapsed?'collapsed':'expanded')}catch(_){}
  }
  function init(){
    const btn=document.getElementById('chatListToggle');
    if(!btn)return;
    let collapsed=false;
    try{collapsed=localStorage.getItem(KEY)==='collapsed'}catch(_){}
    apply(collapsed);
    btn.addEventListener('click',()=>{
      const now=document.documentElement.getAttribute('data-chat-list')==='collapsed';
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

/* Módulos de UI: badge, chips contextuales, plantillas y tips */
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
    if (t.includes('/mail') || t.includes('correo') || t.includes('gmail')) return 'Mail';
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
    inyectarPlantillasMetadato();
  });

  /* ---------- Tips de descubrimiento (arriba del chat) ---------- */
  const TIPS_OFICINAIA = [
    'Tirame una póliza, imagen o TXT al chat y puedo analizarlo.',
    'Si tirás una póliza individual, puedo reconocerla y prepararte el alta automáticamente.',
    'También podés usar /alta para procesar una póliza individual a mano.',
    'De una póliza puedo sacar asegurado, vehículo, patente, compañía, medio de pago, precio y fecha de emisión.',
    'El teléfono del alta queda siempre manual: nunca lo tomo del número de póliza ni de otros números del PDF.',
    'Antes de guardar un alta, siempre podés revisar los datos que encontré.',
    'Puedo prepararte los datos de una póliza tabulados, listos para pegar en Excel.',
    'Si una póliza trae varios vehículos, la distingo de una póliza individual.',
    'Podés adjuntar PDF, TXT o imágenes con el 📎 o arrastrarlos directo sobre el chat.',
    'Si mandás un archivo sin escribir nada, igual lo proceso.',
    'Los PDFs admiten hasta 20 MB; las imágenes hasta 15 MB y los TXT hasta 2 MB.',
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
