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
 * Posiciona la vista al comienzo de un mensaje del asistente,
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
  limpiarMetadataVisualMensajes(r);
  return r;
}


function nombreArchivoSeguro(file,indice=0){
  return String(file?.name||`Adjunto ${indice+1}`).trim()||`Adjunto ${indice+1}`;
}
function tipoArchivoVisual(file){
  const mime=String(file?.type||'').toLowerCase();
  const nombre=String(file?.name||'').toLowerCase();
  if(mime.startsWith('image/')||/\.(png|jpe?g|webp|gif|bmp)$/i.test(nombre))return 'image';
  if(mime.includes('pdf')||nombre.endsWith('.pdf'))return 'pdf';
  if(mime.startsWith('text/')||/\.(txt|csv|md)$/i.test(nombre))return 'text';
  if(/\.(xlsx|xlsm|xls|ods)$/i.test(nombre))return 'sheet';
  return 'file';
}
function formatoTamArchivo(bytes){
  const n=Number(bytes||0);
  if(!Number.isFinite(n)||n<=0)return '';
  if(n>=1024*1024)return (n/(1024*1024)).toFixed(n>=10*1024*1024?0:1).replace('.',',')+' MB';
  if(n>=1024)return Math.round(n/1024)+' KB';
  return n+' B';
}
function abrirLightboxImagen(src,alt='Imagen ampliada'){
  const modal=document.getElementById('chatImageLightbox');
  const img=document.getElementById('chatImageLightboxImg');
  if(!modal||!img||!src)return;
  // El visor debe cubrir TODO el viewport. Dentro de .chat-window podía quedar
  // recortado por el overflow del contenedor (la franja superior seguía nítida).
  if(modal.parentElement!==document.body)document.body.appendChild(modal);
  img.src=src;
  img.alt=alt||'Imagen ampliada';
  modal.hidden=false;
  modal.setAttribute('aria-hidden','false');
  document.body.classList.add('chat-lightbox-open');
}
function cerrarLightboxImagen(){
  const modal=document.getElementById('chatImageLightbox');
  const img=document.getElementById('chatImageLightboxImg');
  if(!modal)return;
  modal.hidden=true;
  modal.setAttribute('aria-hidden','true');
  if(img)img.removeAttribute('src');
  document.body.classList.remove('chat-lightbox-open');
}
function inicializarLightboxChat(){
  const modal=document.getElementById('chatImageLightbox');
  if(!modal)return;
  // Sacarlo de chat-window evita cualquier clipping por overflow y hace que el
  // blur/oscurecido incluya también barra superior, sidebar y conversaciones.
  if(modal.parentElement!==document.body)document.body.appendChild(modal);
  const close=document.getElementById('chatImageLightboxClose');
  if(modal.dataset.wired==='1')return;
  modal.dataset.wired='1';
  close?.addEventListener('click',cerrarLightboxImagen);
  modal.addEventListener('click',e=>{if(e.target===modal)cerrarLightboxImagen()});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!modal.hidden)cerrarLightboxImagen()});
}

function iconoAdjuntoWhatsApp(tipo){
  if(tipo==='pdf')return 'PDF';
  if(tipo==='sheet')return 'XLS';
  if(tipo==='text')return 'TXT';
  if(tipo==='image')return 'IMG';
  return 'DOC';
}
function crearVistaAdjuntoWhatsApp(file,indice=0,{compact=false,sent=false}={}){
  const tipo=tipoArchivoVisual(file);
  const card=document.createElement('div');
  card.className='wa-attachment-card wa-attachment-'+tipo+(compact?' is-compact':'')+(sent?' is-sent':'');
  card.dataset.fileType=tipo;

  if(tipo==='image'){
    const img=document.createElement('img');
    img.className='wa-photo-preview';
    img.alt=nombreArchivoSeguro(file,indice);
    try{
      const objectUrl=URL.createObjectURL(file);
      img.src=objectUrl;
      img.dataset.objectUrl=objectUrl;
      const abrir=()=>abrirLightboxImagen(objectUrl,img.alt);
      img.addEventListener('click',abrir);
      img.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();abrir()}});
      img.tabIndex=0;
      img.role='button';
      img.title='Abrir imagen';
    }catch(_){card.classList.add('wa-no-preview')}
    card.appendChild(img);
  }

  const info=document.createElement('div');
  info.className='wa-attachment-info';
  const icon=document.createElement('span');
  icon.className='wa-attachment-icon';
  icon.textContent=iconoAdjuntoWhatsApp(tipo);
  const texto=document.createElement('span');
  texto.className='wa-attachment-text';
  const nombre=document.createElement('strong');
  nombre.textContent=nombreArchivoSeguro(file,indice);
  nombre.title=nombre.textContent;
  const meta=document.createElement('small');
  meta.textContent=[tipo==='image'?'Imagen':tipo==='pdf'?'Documento PDF':tipo==='sheet'?'Planilla':tipo==='text'?'Texto':'Archivo',formatoTamArchivo(file?.size)].filter(Boolean).join(' · ');
  texto.append(nombre,meta);
  info.append(icon,texto);
  card.appendChild(info);
  return card;
}
function crearVistaAdjuntoHistoricoWhatsApp(nombre,indice=0){
  const limpio=String(nombre||'').trim();
  if(!limpio)return null;
  const fake={name:limpio,size:0,type:/\.(png|jpe?g|webp|gif)$/i.test(limpio)?'image/unknown':/\.pdf$/i.test(limpio)?'application/pdf':''};
  const card=crearVistaAdjuntoWhatsApp(fake,indice,{compact:true,sent:true});
  card.classList.add('is-historical');
  card.querySelector('img')?.remove();
  return card;
}
function crearVistaAdjuntoPersistenteWhatsApp(asset,indice=0){
  if(!asset||typeof asset!=='object')return null;
  const fake={name:asset.name||`Adjunto ${indice+1}`,size:Number(asset.size||0),type:asset.mime||''};
  const tipo=tipoArchivoVisual(fake);
  const card=crearVistaAdjuntoWhatsApp(fake,indice,{compact:true,sent:true});
  card.classList.add('is-persisted');
  const url=String(asset.url||'');
  if(tipo==='image'&&url){
    let img=card.querySelector('img');
    if(!img){img=document.createElement('img');img.className='wa-photo-preview';card.prepend(img)}
    img.src=url;img.alt=fake.name;
    const abrir=()=>abrirLightboxImagen(url,fake.name);
    img.addEventListener('click',abrir);
    img.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();abrir()}});
    img.tabIndex=0;img.role='button';img.title='Abrir imagen';
  }else if(url){
    card.tabIndex=0;card.role='button';card.title='Abrir adjunto';
    const abrir=()=>window.open(url,'_blank','noopener');
    card.addEventListener('click',abrir);
    card.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();abrir()}});
  }
  return card;
}
function parsearAdjuntosHistoricosUsuario(texto){
  const s=String(texto??'');
  const m=s.match(/^\[(Adjunto|Adjuntos):\s*([^\]]+)\]\s*\n?/i);
  if(!m)return {adjuntos:[],texto:s};
  return {adjuntos:m[2].split(',').map(x=>x.trim()).filter(Boolean),texto:s.slice(m[0].length)};
}
function agregarMensajeUsuarioConAdjuntos(texto,archivos=[]){
  const c=chatContainer();
  if(!c)return null;
  const lista=Array.from(archivos||[]);
  if(!lista.length)return add('user',texto||'');
  const r=document.createElement('div');
  r.className='msg user';
  const b=document.createElement('div');
  b.className='bubble';
  const stack=document.createElement('div');
  stack.className='wa-sent-attachments'+(lista.some(f=>tipoArchivoVisual(f)==='image')?' has-images':'');
  lista.forEach((file,idx)=>stack.appendChild(crearVistaAdjuntoWhatsApp(file,idx,{sent:true})));
  b.appendChild(stack);
  const cuerpo=String(texto||'').trim();
  if(cuerpo){
    const txt=document.createElement('div');
    txt.className='wa-user-message-text';
    txt.textContent=cuerpo;
    b.appendChild(txt);
  }
  r.appendChild(b);
  c.appendChild(r);
  limpiarMetadataVisualMensajes(r);
  return r;
}
function agregarMensajeUsuarioHistorico(texto,metadata={}){
  const md=(metadata&&typeof metadata==='object')?metadata:{};
  const persistidos=Array.isArray(md.attachments)?md.attachments:[];
  const parsed=parsearAdjuntosHistoricosUsuario(texto);
  const adjuntos=persistidos.length?persistidos:parsed.adjuntos;
  const displayText=Object.prototype.hasOwnProperty.call(md,'display_text')?String(md.display_text||''):String(parsed.texto||'');
  if(!adjuntos.length)return add('user',displayText||texto||'');
  const c=chatContainer();if(!c)return null;
  const r=document.createElement('div');r.className='msg user';
  const b=document.createElement('div');b.className='bubble';
  const stack=document.createElement('div');stack.className='wa-sent-attachments is-historical';
  adjuntos.forEach((item,idx)=>{
    const card=(item&&typeof item==='object')?crearVistaAdjuntoPersistenteWhatsApp(item,idx):crearVistaAdjuntoHistoricoWhatsApp(item,idx);
    if(card)stack.appendChild(card);
  });
  if(stack.children.length)b.appendChild(stack);
  const cuerpo=displayText.trim();
  if(cuerpo){const txt=document.createElement('div');txt.className='wa-user-message-text';txt.textContent=cuerpo;b.appendChild(txt)}
  r.appendChild(b);c.appendChild(r);limpiarMetadataVisualMensajes(r);return r;
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
// Evita que initChat() y el primer envío creen/abran conversaciones al mismo tiempo.
// El envío espera a que termine únicamente la inicialización ya en curso;
// el botón no se bloquea ni cambia de estado mientras espera.
let chatInitInProgress=false;
let chatInitReadyPromise=Promise.resolve();
let resolveChatInitReady=null;
let archivosAdjuntosChat=[];
let composerEditSeq=0;
// Dictado a texto: Web Speech API del navegador. No llama al backend ni envía solo.
let dictationRecognition=null;
let dictationActive=false;
let dictationBaseText='';
let dictationFinalText='';
let dictationCancelRequested=false;
let dictationProgrammaticUpdate=false;
let attachmentEditSeq=0;
function historialParaApi(){const c=document.getElementById('chat');return c?[...c.querySelectorAll('.msg')].map(x=>({rol:x.classList.contains('user')?'user':'assistant',contenido:(x.querySelector('.bubble')?.textContent?.trim()||'').slice(0,2000)})).filter(x=>x.contenido).slice(-8):[]}
let _chatsCache=[];
let _chatSearchQuery='';

const CHAT_WALLPAPER_KEY='oficinaia_chat_wallpaper';
const CHAT_WALLPAPERS=['soft','clean'];

function aplicarFondoChat(valor){
  const chat=document.getElementById('chatDropZone');
  const elegido=CHAT_WALLPAPERS.includes(valor)?valor:'soft';
  if(chat)chat.dataset.wallpaper=elegido;
  try{localStorage.setItem(CHAT_WALLPAPER_KEY,elegido)}catch(_){}
  document.querySelectorAll('#chatWallpaperMenu [data-wallpaper]').forEach(btn=>{
    const activo=btn.dataset.wallpaper===elegido;
    btn.classList.toggle('active',activo);
    btn.setAttribute('aria-current',activo?'true':'false');
  });
}

function ocultarMenuFondosChat(){
  const menu=document.getElementById('chatWallpaperMenu');
  const btn=document.getElementById('chatWallpaperBtn');
  if(menu)menu.hidden=true;
  if(btn)btn.setAttribute('aria-expanded','false');
}

function inicializarVisualChatWhatsApp(){
  const btn=document.getElementById('chatWallpaperBtn');
  const menu=document.getElementById('chatWallpaperMenu');
  let guardado='soft';
  try{guardado=localStorage.getItem(CHAT_WALLPAPER_KEY)||'soft'}catch(_){}
  aplicarFondoChat(guardado);
  if(!btn||!menu||btn.dataset.wired==='1')return;
  btn.dataset.wired='1';
  btn.addEventListener('click',e=>{
    e.preventDefault();
    e.stopPropagation();
    const abrir=menu.hidden;
    menu.hidden=!abrir;
    btn.setAttribute('aria-expanded',abrir?'true':'false');
  });
  menu.addEventListener('click',e=>{
    const item=e.target.closest('[data-wallpaper]');
    if(!item)return;
    e.preventDefault();
    aplicarFondoChat(item.dataset.wallpaper);
    ocultarMenuFondosChat();
  });
  document.addEventListener('click',e=>{
    if(menu.hidden)return;
    if(e.target.closest('#chatWallpaperMenu')||e.target.closest('#chatWallpaperBtn'))return;
    ocultarMenuFondosChat();
  });
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape')ocultarMenuFondosChat();
  });
}

function limpiarMetadataVisualMensajes(root){
  const scope=root||document;
  try{
    scope.querySelectorAll('.msg-time,.message-time,.bubble-time,.chat-msg-time,.read-receipt,.seen-receipt,.delivery-receipt,.message-status,.msg-status,.wa-check,.wa-checks,.checkmarks').forEach(el=>el.remove());
  }catch(_){}
}

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
    d.mensajes.forEach(m=>{
      if(m.rol==='user')agregarMensajeUsuarioHistorico(m.contenido,m.metadata||{});
      else{
        const ui=(m?.metadata?.ui&&typeof m.metadata.ui==='object')?m.metadata.ui:{};
        const visible=textoVisibleAsistente(m.contenido,ui);
        if(visible)add(m.rol,visible);
        renderizarUiPersistida(m);
      }
    });
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

async function copiarTextoSeguro(texto){
  const valor=String(texto??'');
  try{await navigator.clipboard.writeText(valor);return true}catch(_){}
  try{
    const ta=document.createElement('textarea');
    ta.value=valor;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);
    ta.select();const ok=document.execCommand('copy');ta.remove();return !!ok;
  }catch(_){return false}
}

function estadoCriticoConfiable(estado){
  const e=String(estado||'').toLowerCase();
  return e==='verificado'||e==='alta'||e==='confirmado_productor';
}
function etiquetaConfianza(estado,coincidencias=0,{noDisponible='⚠ No disponible'}={}){
  const e=String(estado||'').toLowerCase();
  const n=Number(coincidencias||0);
  if(e==='confirmado_productor')return '✓ Confirmado por productor';
  if(e==='verificado'||e==='alta')return '✅ Verificado · Alta confianza — 3/3 lecturas coincidentes';
  if(e==='media'||n>=2)return '⚠ Revisar';
  if(e==='no_legible')return '⚠ No legible';
  if(e==='no_disponible')return noDisponible;
  return '⚠ Revisar';
}
function botonCopiarCampo(texto,label,{revisar=false}={}){
  if(!String(texto||'').trim())return null;
  const btn=document.createElement('button');btn.type='button';btn.className='alta-secondary-btn';btn.textContent=label;
  btn.addEventListener('click',async()=>{
    if(revisar&&!confirm('Este dato necesita revisión. ¿Querés continuar?'))return;
    const ok=await copiarTextoSeguro(String(texto));
    if(ok){const old=btn.textContent;btn.textContent='¡Copiado!';setTimeout(()=>btn.textContent=old,1500)}
  });
  return btn;
}

function normalizarAlternativasCedula(datos,clave){
  const raw=Array.isArray(datos['alternativas_'+clave])?datos['alternativas_'+clave]:[];
  const out=[];
  raw.forEach(v=>{
    const t=String(v||'').trim();
    if(!t||t.includes('?')||out.includes(t))return;
    out.push(t);
  });
  const actual=String(datos[clave]||'').trim();
  if(actual&&!actual.includes('?')&&!out.includes(actual))out.unshift(actual);
  return out.slice(0,8);
}
function normalizarManualCedula(valor){
  return String(valor||'').trim().toUpperCase().replace(/\s+/g,'');
}
function crearConfirmacionCedula({datos,clave,etiqueta,box,code,badge,onConfirmada}){
  const alternativas=normalizarAlternativasCedula(datos,clave);
  const wrap=document.createElement('div');wrap.className='cedula-confirmation';
  const intro=document.createElement('div');intro.className='cedula-confirmation-title';
  intro.textContent='Corroborá el documento y confirmá el dato.';
  wrap.appendChild(intro);

  const grupo=document.createElement('div');grupo.className='cedula-options';
  const nombre='cedula-'+clave+'-'+Math.random().toString(36).slice(2);
  let manualInput=null;
  const agregarOpcion=(valor,labelTexto,{manual=false}={})=>{
    const label=document.createElement('label');label.className='cedula-option';
    const radio=document.createElement('input');radio.type='radio';radio.name=nombre;radio.value=manual?'__manual__':valor;
    const texto=document.createElement('span');texto.textContent=labelTexto;
    label.append(radio,texto);grupo.appendChild(label);
    if(manual){
      manualInput=document.createElement('input');manualInput.type='text';manualInput.className='cedula-manual-input';manualInput.placeholder='Ingresar dato correcto';manualInput.autocomplete='off';manualInput.disabled=true;
      label.appendChild(manualInput);
      radio.addEventListener('change',()=>{manualInput.disabled=!radio.checked;if(radio.checked)manualInput.focus()});
    }
    return radio;
  };
  let primerRadio=null;
  alternativas.forEach((alt,i)=>{const r=agregarOpcion(alt,alt);if(i===0)primerRadio=r});
  const manualRadio=agregarOpcion('','Ingresar manualmente',{manual:true});
  if(primerRadio)primerRadio.checked=true; else {manualRadio.checked=true;manualInput.disabled=false}
  grupo.querySelectorAll('input[type="radio"]').forEach(r=>r.addEventListener('change',()=>{
    if(manualInput)manualInput.disabled=manualRadio!==r||!manualRadio.checked;
  }));
  wrap.appendChild(grupo);

  const confirmar=document.createElement('button');confirmar.type='button';confirmar.className='alta-secondary-btn cedula-confirm-btn';
  confirmar.textContent=alternativas.length>1?'Seleccionar lectura':'Confirmar dato';
  confirmar.addEventListener('click',()=>{
    const elegido=grupo.querySelector('input[type="radio"]:checked');
    if(!elegido){alert('Seleccioná una lectura o ingresá el dato manualmente.');return}
    let valor=elegido.value==='__manual__'?normalizarManualCedula(manualInput&&manualInput.value):String(elegido.value||'').trim();
    if(!valor){alert('Ingresá el dato correcto antes de confirmar.');return}
    datos[clave]=valor;
    datos['estado_'+clave]='confirmado_productor';
    datos['fuente_verificacion_'+clave]='producer';
    code.textContent=valor;
    badge.textContent='✓ Confirmado por productor';
    box.classList.remove('is-warning');box.classList.add('is-ok','is-confirmed');
    wrap.replaceChildren();
    const ok=document.createElement('div');ok.className='cedula-confirmed-note';ok.textContent='Confirmado por productor después de corroborar el documento.';wrap.appendChild(ok);
    const copiar=botonCopiarCampo(valor,'Copiar '+etiqueta.toLowerCase());if(copiar)wrap.appendChild(copiar);
    if(typeof onConfirmada==='function')onConfirmada();
  });
  wrap.appendChild(confirmar);
  return wrap;
}

async function persistirConfirmacionesCedula(messageId,datos){
  const id=Number(messageId||0);
  if(!id||!currentChatId||!datos||typeof datos!=='object')return;
  const confirmaciones={};
  ['patente','motor','chasis'].forEach(clave=>{
    if(String(datos['estado_'+clave]||'').toLowerCase()!=='confirmado_productor')return;
    const valor=String(datos[clave]||'').trim();
    if(valor)confirmaciones[clave]=valor;
  });
  if(!Object.keys(confirmaciones).length)return;
  try{
    await fetch(`/api/chats/${currentChatId}/messages/${id}/ui-state`,{
      method:'PATCH',headers:{'Content-Type':'application/json'},credentials:'same-origin',
      body:JSON.stringify({ui_state:{cedula_confirmaciones:confirmaciones}})
    });
  }catch(_){}
}

function aplicarConfirmacionesCedulaPersistidas(datos,uiState){
  if(!datos||typeof datos!=='object')return datos;
  const confirmaciones=(uiState&&typeof uiState.cedula_confirmaciones==='object')?uiState.cedula_confirmaciones:{};
  ['patente','motor','chasis'].forEach(clave=>{
    const valor=String(confirmaciones[clave]||'').trim();
    if(!valor)return;
    datos[clave]=valor;
    datos['estado_'+clave]='confirmado_productor';
    datos['fuente_verificacion_'+clave]='producer';
  });
  return datos;
}

function prefillAltaDesdeCedula(datos,base={}){
  const campos={...(base&&typeof base==='object'?base:{})};
  campos.LIBRO_ID=String(campos.LIBRO_ID||'1');
  campos.ASEGURADO=String(datos?.titular||campos.ASEGURADO||'').trim();
  const vehiculo=[datos?.marca,datos?.modelo,datos?.anio].map(x=>String(x||'').trim()).filter(Boolean).filter((v,i,a)=>a.findIndex(x=>x.toUpperCase()===v.toUpperCase())===i).join(' ');
  if(vehiculo)campos.VEHICULO=vehiculo;
  if(String(datos?.patente||'').trim())campos.PATENTE=String(datos.patente).trim().toUpperCase().replace(/\s+/g,'');
  ['POLIZA','NUMERO','ENVIOS YA','CIA','MEDIO DE PAGO','CP','EMITIDO DÍA:','IMPORTE APROX','MAIL','TELEFONO'].forEach(k=>{if(campos[k]==null)campos[k]=''});
  return campos;
}
function revisionesAltaDesdeCedula(datos,base={}){
  const revisiones={...(base&&typeof base==='object'?base:{})};
  if(estadoCriticoConfiable(datos?.estado_patente))delete revisiones.PATENTE;
  else if(String(datos?.patente||'').trim())revisiones.PATENTE=revisiones.PATENTE||'Lectura de patente para confirmar con la cédula antes de guardar.';
  return revisiones;
}

function mostrarCedulaDetectada(datos,advertencias=[],opciones={}){
  const c=document.getElementById('chat');
  if(!c||!datos||typeof datos!=='object')return;
  const opts=(opciones&&typeof opciones==='object')?opciones:{};
  const messageId=Number(opts.messageId||0);
  const uiState=(opts.uiState&&typeof opts.uiState==='object')?opts.uiState:{};
  aplicarConfirmacionesCedulaPersistidas(datos,uiState);

  const r=document.createElement('div');r.className='msg assistant';
  const b=document.createElement('div');b.className='bubble cedula-card';
  const titulo=document.createElement('div');titulo.className='alta-compact-title';titulo.textContent='Cédula detectada'+(datos.caras_combinadas?' · frente + dorso':'');b.appendChild(titulo);

  const meta=[];
  const vehiculo=[datos.marca,datos.modelo,datos.anio].filter(Boolean).join(' ');
  if(vehiculo)meta.push(['Vehículo',vehiculo]);
  if(datos.tipo)meta.push(['Tipo',datos.tipo]);
  if(datos.uso)meta.push(['Uso',datos.uso]);
  if(datos.vencimiento)meta.push(['Vencimiento',datos.vencimiento]);
  if(datos.control||datos.numero_cedula)meta.push(['Control / N° cédula',datos.control||datos.numero_cedula]);
  if(datos.titular)meta.push(['Titular',datos.titular]);
  if(meta.length){
    const resumen=document.createElement('div');resumen.className='cedula-summary';
    meta.forEach(([k,v])=>{const item=document.createElement('div');item.className='cedula-summary-item';const sp=document.createElement('span');sp.textContent=k;const st=document.createElement('strong');st.textContent=v;item.append(sp,st);resumen.appendChild(item)});
    b.appendChild(resumen);
  }

  const acciones=document.createElement('div');acciones.className='alta-compact-actions cedula-copy-actions';
  const refrescarAcciones=()=>{
    acciones.replaceChildren();
    const confiable=k=>estadoCriticoConfiable(datos['estado_'+k]);
    const motor=String(datos.motor||'').trim(),chasis=String(datos.chasis||'').trim();
    if(motor&&chasis&&confiable('motor')&&confiable('chasis')){
      const btn=botonCopiarCampo(motor+'\n'+chasis,'Copiar motor y chasis');if(btn)acciones.appendChild(btn);
    }
    const todos=[];
    [['Patente','patente'],['Marca','marca'],['Modelo','modelo'],['Tipo','tipo'],['Uso','uso'],['Año','anio'],['Vencimiento','vencimiento'],['Control / N° cédula','control'],['Motor','motor'],['Chasis','chasis']].forEach(([lab,k])=>{const v=String(datos[k]||'').trim();if(v)todos.push(lab+': '+v)});
    const criticosListos=['patente','motor','chasis'].every(k=>confiable(k));
    if(todos.length&&criticosListos){
      const btn=botonCopiarCampo(todos.join('\n'),'Copiar todos los datos');if(btn)acciones.appendChild(btn);
    }
    acciones.hidden=!acciones.children.length;
  };

  const ids=document.createElement('div');ids.className='cedula-identifiers cedula-identifiers-three';
  const crearCampo=(clave,etiqueta)=>{
    const valor=String(datos[clave]||'').trim();
    const estado=String(datos['estado_'+clave]||'revisar');
    const coincidencias=Number(datos['coincidencias_'+clave]||0);
    const dudas=Array.isArray(datos['dudas_'+clave])?datos['dudas_'+clave]:[];
    const recorte=String(datos['recorte_'+clave]||'');
    const confiable=estadoCriticoConfiable(estado);
    const box=document.createElement('div');box.className='cedula-identifier '+(confiable?'is-ok':'is-warning');
    if(estado==='confirmado_productor')box.classList.add('is-confirmed');
    const head=document.createElement('div');head.className='cedula-identifier-head';
    const lab=document.createElement('strong');lab.textContent=etiqueta;
    const badge=document.createElement('span');badge.className='cedula-status';badge.textContent=etiquetaConfianza(estado,coincidencias);
    head.append(lab,badge);box.appendChild(head);
    const code=document.createElement('code');code.className='cedula-code';code.textContent=valor||'—';box.appendChild(code);

    if(!confiable){
      const aviso=document.createElement('div');aviso.className='cedula-review-brief';
      aviso.textContent=estado.toLowerCase()==='no_legible'?'⚠ Lectura para confirmar · no pude leer este dato con seguridad.':'⚠ Lectura para confirmar · verificá este dato antes de utilizarlo.';
      box.appendChild(aviso);
      if(dudas.length){
        const details=document.createElement('details');details.className='cedula-review-details';
        const summary=document.createElement('summary');summary.textContent='¿Por qué debo revisarlo?';
        const det=document.createElement('div');det.className='cedula-doubt';
        dudas.slice(0,8).forEach(d=>{const linea=document.createElement('div');linea.textContent=String(d);det.appendChild(linea)});
        details.addEventListener('toggle',()=>{summary.textContent=details.open?'Ocultar detalles':'¿Por qué debo revisarlo?'});
        details.append(summary,det);box.appendChild(details);
      }
    }

    // MOTOR/CHASIS: conservar la evidencia visual derivada del documento real.
    // No se realiza una nueva consulta a Gemini: sólo se renderiza el crop que
    // ya vino en cedula_detectada y se abre con el lightbox común del chat.
    if(recorte&&(clave==='motor'||clave==='chasis')){
      const details=document.createElement('details');details.className='cedula-crop-details';
      const summary=document.createElement('summary');summary.textContent='Ver recorte';
      const img=document.createElement('img');img.className='cedula-crop';img.alt='Recorte de '+etiqueta;img.src=recorte;
      const abrir=()=>abrirLightboxImagen(recorte,img.alt);
      img.addEventListener('click',abrir);
      img.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();abrir()}});
      img.tabIndex=0;img.role='button';img.title='Abrir imagen';
      details.append(summary,img);box.appendChild(details);
    }

    if(confiable){
      const btn=botonCopiarCampo(valor,'Copiar '+etiqueta.toLowerCase());if(btn)box.appendChild(btn);
    }else{
      box.appendChild(crearConfirmacionCedula({datos,clave,etiqueta,box,code,badge,onConfirmada:()=>{
        refrescarAcciones();
        if(messageId)persistirConfirmacionesCedula(messageId,datos);
      }}));
    }
    return box;
  };
  ids.appendChild(crearCampo('patente','PATENTE'));
  ids.appendChild(crearCampo('motor','MOTOR'));
  ids.appendChild(crearCampo('chasis','CHASIS'));
  b.appendChild(ids);

  refrescarAcciones();
  b.appendChild(acciones);

  if(!opts.altaYaPreparada){
    const altaAcciones=document.createElement('div');altaAcciones.className='cedula-alta-actions';
    const prepararAlta=document.createElement('button');prepararAlta.type='button';prepararAlta.className='excel-proposal-save cedula-preparar-alta';prepararAlta.textContent='Preparar alta';
    const altaAyuda=document.createElement('small');altaAyuda.textContent='Abre el mismo Alta / asegurado para revisar, completar y recién después guardar en Excel.';
    prepararAlta.addEventListener('click',()=>{
      const campos=prefillAltaDesdeCedula(datos,opts.altaPrefill||{});
      const revisiones=revisionesAltaDesdeCedula(datos,opts.altaRevisiones||{});
      mostrarOpcionesAltaAsegurado(null,campos,{origen:'cedula',revisiones});
      prepararAlta.disabled=true;prepararAlta.textContent='✓ Alta preparada';
      const cards=document.querySelectorAll('.alta-compact-card[data-alta-activa="1"]');
      const ultima=cards[cards.length-1];if(ultima)ultima.scrollIntoView({behavior:'smooth',block:'nearest'});
    });
    altaAcciones.append(prepararAlta,altaAyuda);b.appendChild(altaAcciones);
  }
  if(Array.isArray(advertencias)&&advertencias.length){
    const generales=advertencias.filter(a=>{
      const t=String(a||'').trim();
      return t && !/^Revisá (PATENTE|MOTOR|CHASIS)\b/i.test(t) &&
        !/^La lectura focalizada no pudo completarse/i.test(t) &&
        !/^La verificación independiente no pudo completarse/i.test(t);
    });
    if(generales.length){const w=document.createElement('div');w.className='cedula-warning';w.textContent=generales.slice(0,2).join(' ');b.appendChild(w)}
  }
  r.appendChild(b);c.appendChild(r);
}

function mostrarDocumentoPersonalDetectado(datos,advertencias=[]){
  const c=document.getElementById('chat');
  if(!c||!datos||typeof datos!=='object')return;
  const tipo=String(datos.tipo_documento||'dni').toLowerCase();
  const nombreTipo=tipo==='licencia'?'Licencia':'DNI';
  const r=document.createElement('div');r.className='msg assistant';
  const b=document.createElement('div');b.className='bubble cedula-card personal-document-card';
  const titulo=document.createElement('div');titulo.className='alta-compact-title';
  titulo.textContent=nombreTipo+' detectad'+(tipo==='licencia'?'a':'o')+(datos.caras_combinadas?' · frente + dorso':'');
  b.appendChild(titulo);

  const nombreCompleto=[datos.nombre,datos.apellido].filter(Boolean).join(' ').trim();
  if(nombreCompleto){
    const resumen=document.createElement('div');resumen.className='cedula-summary';
    const item=document.createElement('div');item.className='cedula-summary-item';
    const sp=document.createElement('span');sp.textContent='Titular';const st=document.createElement('strong');st.textContent=nombreCompleto;
    item.append(sp,st);resumen.appendChild(item);b.appendChild(resumen);
  }

  const fields=document.createElement('div');fields.className='personal-fields';
  const agregar=(clave,label,{critico=false,displayKey=null,ausente='No disponible en el documento'}={})=>{
    const raw=String(datos[clave]||'').trim();
    const mostrado=String(datos[displayKey||clave]||raw).trim();
    const estado=String(datos['estado_'+clave]||'');
    const necesitaRevision=estado==='revisar'||estado==='media'||estado==='no_legible';
    const altaCritica=!critico||estado==='alta';
    const box=document.createElement('div');box.className='cedula-identifier '+((altaCritica&&!necesitaRevision)?'is-ok':'is-warning');
    const head=document.createElement('div');head.className='cedula-identifier-head';
    const lab=document.createElement('strong');lab.textContent=label;head.appendChild(lab);
    if(critico||necesitaRevision){
      const badge=document.createElement('span');badge.className='cedula-status';
      badge.textContent=critico?etiquetaConfianza(estado,datos['coincidencias_'+clave],{noDisponible:'No disponible'}):'⚠ Revisar';
      head.appendChild(badge);
    }
    box.appendChild(head);
    const code=document.createElement('code');code.className='cedula-code personal-value';code.textContent=mostrado||(necesitaRevision?'Revisar':ausente);box.appendChild(code);
    const dudas=Array.isArray(datos['dudas_'+clave])?datos['dudas_'+clave]:[];
    if(dudas.length){const det=document.createElement('div');det.className='cedula-doubt';det.textContent=dudas.join(' ');box.appendChild(det)}
    if(raw){
      const revisar=(critico&&estado!=='alta')||necesitaRevision;
      const copiable=clave==='fecha_nacimiento'?(mostrado||raw):raw;
      const btn=botonCopiarCampo(copiable,'Copiar '+label.toLowerCase(),{revisar});if(btn)box.appendChild(btn);
    }
    fields.appendChild(box);
  };
  agregar('dni','DNI',{critico:true,displayKey:'dni_mostrar'});
  agregar('fecha_nacimiento','FECHA DE NACIMIENTO',{critico:true,displayKey:'fecha_nacimiento_mostrar'});
  agregar('cuil','CUIL',{critico:true,displayKey:'cuil_mostrar',ausente:tipo==='licencia'?'No disponible en el documento':'No disponible en la imagen enviada'});
  agregar('domicilio','DOMICILIO');
  agregar('localidad','LOCALIDAD');
  if(tipo==='licencia'){
    agregar('otorgamiento','OTORGAMIENTO',{displayKey:'otorgamiento_mostrar'});
    agregar('vencimiento','VENCIMIENTO',{displayKey:'vencimiento_mostrar'});
    if(Array.isArray(datos.clases)&&datos.clases.length){
      const box=document.createElement('div');box.className='cedula-identifier is-ok personal-classes';
      const head=document.createElement('div');head.className='cedula-identifier-head';const lab=document.createElement('strong');lab.textContent='CLASES';head.appendChild(lab);box.appendChild(head);
      const code=document.createElement('code');code.className='cedula-code personal-value';code.textContent=datos.clases.join(' · ');box.appendChild(code);
      const btn=botonCopiarCampo(datos.clases.join('\n'),'Copiar clases');if(btn)box.appendChild(btn);fields.appendChild(box);
    }
    if(Array.isArray(datos.observaciones)&&datos.observaciones.length){
      const box=document.createElement('div');box.className='cedula-identifier is-warning personal-observations';
      const head=document.createElement('div');head.className='cedula-identifier-head';const lab=document.createElement('strong');lab.textContent='OBSERVACIONES';head.appendChild(lab);box.appendChild(head);
      const code=document.createElement('code');code.className='cedula-code personal-value';code.textContent=datos.observaciones.join(' · ');box.appendChild(code);fields.appendChild(box);
    }
  }
  b.appendChild(fields);

  const principales=[];
  [['DNI','dni'],['Fecha de nacimiento','fecha_nacimiento'],['CUIL','cuil'],['Domicilio','domicilio'],['Localidad','localidad'],['Otorgamiento','otorgamiento'],['Vencimiento','vencimiento']].forEach(([lab,k])=>{let v=String(datos[k]||'').trim();if(!v)return;if(k==='fecha_nacimiento')v=String(datos.fecha_nacimiento_mostrar||v);if(k==='dni')v=String(datos.dni_mostrar||v);if(k==='cuil')v=String(datos.cuil_mostrar||v);if(k==='otorgamiento')v=String(datos.otorgamiento_mostrar||v);if(k==='vencimiento')v=String(datos.vencimiento_mostrar||v);principales.push(lab+': '+v)});
  if(principales.length){
    const acciones=document.createElement('div');acciones.className='alta-compact-actions cedula-copy-actions';
    const revisar=['dni','fecha_nacimiento','cuil'].some(k=>String(datos[k]||'').trim()&&String(datos['estado_'+k]||'')!=='alta');
    const btn=botonCopiarCampo(principales.join('\n'),'Copiar datos principales',{revisar});if(btn)acciones.appendChild(btn);
    b.appendChild(acciones);
  }
  if(Array.isArray(advertencias)&&advertencias.length){const w=document.createElement('div');w.className='cedula-warning';w.textContent=advertencias.slice(0,3).join(' ');b.appendChild(w)}
  r.appendChild(b);c.appendChild(r);
}

function actualizarFormularioAltaActivo(campos){
  const card=document.querySelector('.alta-compact-card[data-alta-activa="1"]');
  if(!card||!campos||typeof campos!=='object')return false;
  const inputs=card.querySelectorAll('[data-campo]');
  let tocado=false;
  inputs.forEach(input=>{
    const k=input.dataset.campo;
    if(Object.prototype.hasOwnProperty.call(campos,k)){
      input.value=String(campos[k]??'');input.dispatchEvent(new Event('input',{bubbles:true}));tocado=true;
    }
  });
  return tocado;
}

async function prepararSalidasAlta(campos){
  const resp=await fetch('/api/alta/preparar-salidas',{
    method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',
    body:JSON.stringify({campos,chat_id:currentChatId})
  });
  const d=await leerJsonSeguro(resp);
  if(!resp.ok||d.ok===false)throw Error(d.error||'No pude preparar las salidas del alta.');
  return d;
}

function mostrarOpcionesAltaAsegurado(_tabuladoInicial,camposGuardar,opciones={}){
  const c=document.getElementById('chat');
  if(!c||!camposGuardar||typeof camposGuardar!=='object')return;
  document.querySelectorAll('.alta-compact-card[data-alta-activa="1"]').forEach(x=>x.dataset.altaActiva='0');

  const valores={...camposGuardar};
  valores.LIBRO_ID=String(valores.LIBRO_ID||'1');
  // NUMERO conserva su semántica histórica: teléfono manual del Excel. Si la
  // ficha se reconstruye después de una corrección contextual, conservar ese
  // valor en vez de borrarlo. La extracción inicial desde póliza ya llega vacía.
  valores.NUMERO=String(valores.NUMERO||valores.TELEFONO||'');
  valores.TELEFONO='';
  valores['ENVIOS YA']='';

  const r=document.createElement('div');r.className='msg assistant';
  const b=document.createElement('div');b.className='bubble alta-compact-card';b.dataset.altaActiva='1';
  const messageId=Number(opciones?.messageId||0);
  if(messageId)b.dataset.messageId=String(messageId);

  const revisiones={...(opciones?.revisiones&&typeof opciones.revisiones==='object'?opciones.revisiones:{})};
  const origen=String(opciones?.origen||'').trim().toLowerCase();
  const titulo=document.createElement('div');titulo.className='alta-compact-title';
  const refrescarTitulo=()=>{const nombre=String(valores.ASEGURADO||'').trim();const base=origen==='cedula'?'Alta desde cédula':(origen==='cedula+poliza'?'Alta desde cédula + póliza':'Alta detectada');titulo.textContent=nombre?`${base} — ${nombre}`:base};
  refrescarTitulo();b.appendChild(titulo);
  const revisionAviso=document.createElement('div');revisionAviso.className='alta-prefill-warning';
  const refrescarRevisionAviso=()=>{const pendientes=Object.values(revisiones).filter(Boolean);revisionAviso.textContent=pendientes.length?'⚠ Lectura para confirmar · '+pendientes.join(' '):'';revisionAviso.hidden=!pendientes.length};
  refrescarRevisionAviso();b.appendChild(revisionAviso);

  const resumen=document.createElement('div');resumen.className='alta-compact-summary';
  const resumenRefs={};
  const camposResumen=[['VEHICULO','Vehículo'],['PATENTE','Patente'],['CIA','Compañía'],['MEDIO DE PAGO','Medio de pago'],['IMPORTE APROX','Precio'],['EMITIDO DÍA:','Emisión']];
  const valorVisible=(clave,valor)=>{const raw=String(valor??'').trim();if(!raw)return '—';if(clave==='IMPORTE APROX'){const n=Number(raw.replace(',','.'));if(Number.isFinite(n)){try{return new Intl.NumberFormat('es-AR',{style:'currency',currency:'ARS',maximumFractionDigits:2}).format(n)}catch(_){}}}return raw};
  camposResumen.forEach(([clave,label])=>{const item=document.createElement('div');item.className='alta-compact-item'+(revisiones[clave]?' needs-review':'');item.dataset.resumenCampo=clave;const k=document.createElement('span');k.className='alta-compact-key';k.textContent=label;const v=document.createElement('strong');v.className='alta-compact-value';v.textContent=valorVisible(clave,valores[clave]);resumenRefs[clave]=v;item.append(k,v);resumen.appendChild(item)});
  b.appendChild(resumen);

  const telefonoWrap=document.createElement('label');telefonoWrap.className='alta-phone-field';
  const telefonoLabel=document.createElement('span');telefonoLabel.textContent='Teléfono';
  const telefonoInput=document.createElement('input');telefonoInput.type='text';telefonoInput.inputMode='tel';telefonoInput.autocomplete='off';telefonoInput.placeholder='Lo completás vos';telefonoInput.value=String(valores.NUMERO||'');telefonoInput.dataset.campo='NUMERO';
  const telefonoNota=document.createElement('small');telefonoNota.textContent='Manual · se normaliza al copiar Envíos Ya';
  telefonoWrap.append(telefonoLabel,telefonoInput,telefonoNota);b.appendChild(telefonoWrap);

  const detalles=document.createElement('div');detalles.className='alta-edit-panel';detalles.hidden=true;
  const editables=[['ASEGURADO','Asegurado','text'],['POLIZA','N.º póliza','text'],['VEHICULO','Vehículo','text'],['PATENTE','Patente','text'],['CIA','Compañía','text'],['MEDIO DE PAGO','Medio de pago','select'],['CP','Código postal','text'],['EMITIDO DÍA:','Día de emisión','text'],['IMPORTE APROX','Precio','text'],['MAIL','Mail','email']];
  const inputs={};
  editables.forEach(([clave,label,tipo])=>{const wrap=document.createElement('label');wrap.className='alta-edit-field'+(revisiones[clave]?' needs-review':'');const span=document.createElement('span');span.textContent=label;let input;if(tipo==='select'){input=document.createElement('select');[['','—'],['CUPONERA','CUPONERA'],['CBU','CBU'],['CREDITO','CREDITO']].forEach(([value,text])=>{const opt=document.createElement('option');opt.value=value;opt.textContent=text;if(String(valores[clave]||'').toUpperCase()===value)opt.selected=true;input.appendChild(opt)})}else{input=document.createElement('input');input.type=tipo;input.value=String(valores[clave]??'')}input.dataset.campo=clave;inputs[clave]=input;let reviewNote=null;if(revisiones[clave]){reviewNote=document.createElement('small');reviewNote.className='alta-field-review-note';reviewNote.textContent='⚠ '+revisiones[clave]}const sync=(e)=>{valores[clave]=input.value.trim();if(resumenRefs[clave])resumenRefs[clave].textContent=valorVisible(clave,valores[clave]);if(clave==='ASEGURADO')refrescarTitulo();if(e?.isTrusted&&revisiones[clave]){delete revisiones[clave];wrap.classList.remove('needs-review');reviewNote?.remove();const item=resumen.querySelector(`[data-resumen-campo="${clave}"]`);item?.classList.remove('needs-review');refrescarRevisionAviso()}};input.addEventListener('input',sync);input.addEventListener('change',sync);wrap.append(span,input);if(reviewNote)wrap.appendChild(reviewNote);detalles.appendChild(wrap)});
  b.appendChild(detalles);

  const acciones=document.createElement('div');acciones.className='alta-compact-actions';
  const guardar=document.createElement('button');guardar.type='button';guardar.className='excel-proposal-save';guardar.textContent='Guardar en Excel';
  const editar=document.createElement('button');editar.type='button';editar.className='alta-secondary-btn';editar.textContent='Editar';
  const tabular=document.createElement('button');tabular.type='button';tabular.className='alta-secondary-btn';tabular.textContent='Tabulado';
  const enviosBtn=document.createElement('button');enviosBtn.type='button';enviosBtn.className='alta-secondary-btn';enviosBtn.textContent='Copiar Envíos Ya';
  const estado=document.createElement('span');estado.className='excel-proposal-status';
  acciones.append(guardar,editar,tabular,enviosBtn,estado);b.appendChild(acciones);
  if(opciones?.uiState?.saved_excel){guardar.textContent='✓ Guardado en Excel';guardar.disabled=true;editar.disabled=true;telefonoInput.disabled=true;Object.values(inputs).forEach(input=>input.disabled=true);b.dataset.altaActiva='0';}

  const tabPanel=document.createElement('div');tabPanel.className='alta-inline-panel';tabPanel.hidden=true;
  const tabTitle=document.createElement('div');tabTitle.className='alta-inline-title';tabTitle.textContent='Fila tabulada';
  const tabPre=document.createElement('pre');tabPre.className='tabulado-flota-pre';
  const tabCopy=document.createElement('button');tabCopy.type='button';tabCopy.className='tabulado-flota-copy';tabCopy.textContent='Copiar';
  tabPanel.append(tabTitle,tabPre,tabCopy);b.appendChild(tabPanel);

  const enviosPanel=document.createElement('div');enviosPanel.className='alta-inline-panel';enviosPanel.hidden=true;
  const enviosTitle=document.createElement('div');enviosTitle.className='alta-inline-title';enviosTitle.textContent='Datos para Envíos Ya';
  const enviosPre=document.createElement('pre');enviosPre.className='tabulado-flota-pre';
  const enviosAviso=document.createElement('div');enviosAviso.className='alta-envios-warning';enviosAviso.hidden=true;
  enviosPanel.append(enviosTitle,enviosPre,enviosAviso);b.appendChild(enviosPanel);
  r.appendChild(b);c.appendChild(r);

  const recoger=()=>{Object.values(inputs).forEach(input=>{valores[input.dataset.campo]=input.value.trim()});valores.NUMERO=telefonoInput.value.trim();valores.TELEFONO='';valores['ENVIOS YA']='';return {...valores}};
  const payloadExcel=()=>{const v=recoger();delete v.POLIZA;delete v.NUMERO_POLIZA;return v};
  const filaTabulada=()=>{const v=recoger();const orden=['ASEGURADO','NUMERO','VEHICULO','PATENTE','ENVIOS YA','COMPAÑIA','MEDIO DE PAGO','CODIGO POSTAL','EMITIDO DÍA:','IMPORTE APROX','DE DONDE ','MAIL','TELEFONO'];const map={ASEGURADO:v.ASEGURADO||'',NUMERO:v.NUMERO||'',VEHICULO:v.VEHICULO||'',PATENTE:v.PATENTE||'','ENVIOS YA':'',COMPAÑIA:v.CIA||'','MEDIO DE PAGO':v['MEDIO DE PAGO']||'','CODIGO POSTAL':v.CP||'','EMITIDO DÍA:':v['EMITIDO DÍA:']||'','IMPORTE APROX':v['IMPORTE APROX']||'','DE DONDE ':'',MAIL:v.MAIL||'',TELEFONO:''};return orden.map(k=>String(map[k]??'')).join('\t')};

  editar.addEventListener('click',()=>{detalles.hidden=!detalles.hidden;editar.textContent=detalles.hidden?'Editar':'Cerrar edición';if(!detalles.hidden)inputs.ASEGURADO?.focus()});
  tabular.addEventListener('click',()=>{tabPre.textContent=filaTabulada();tabPanel.hidden=!tabPanel.hidden;tabular.textContent=tabPanel.hidden?'Tabulado':'Ocultar tabulado'});
  tabCopy.addEventListener('click',async()=>{tabPre.textContent=filaTabulada();if(await copiarTextoSeguro(tabPre.textContent)){tabCopy.textContent='¡Copiado!';setTimeout(()=>tabCopy.textContent='Copiar',1600)}});

  enviosBtn.addEventListener('click',async()=>{
    estado.textContent='Preparando Envíos Ya…';
    try{
      const d=await prepararSalidasAlta(recoger());
      enviosPre.textContent=String(d.texto_envios_ya??'');
      const avisos=Array.isArray(d.envios_ya_advertencias)?d.envios_ya_advertencias:[];
      enviosAviso.textContent=avisos.join(' ');enviosAviso.hidden=!avisos.length;enviosPanel.hidden=false;
      if(!d.envios_ya_telefono_valido){estado.textContent=avisos.join(' ')||'Revisá el teléfono.';return}
      const ok=await copiarTextoSeguro(d.texto_envios_ya);estado.textContent=ok?'Envíos Ya copiado.':'No pude copiar automáticamente.';
      if(ok){enviosBtn.textContent='¡Copiado!';setTimeout(()=>enviosBtn.textContent='Copiar Envíos Ya',1600)}
    }catch(e){estado.textContent=e?.message||'No pude preparar Envíos Ya.'}
  });

  guardar.addEventListener('click',async()=>{
    if(guardar.disabled)return;
    const pendientes=Object.values(revisiones).filter(Boolean);
    if(pendientes.length){const seguirRevision=confirm('Hay datos que siguen marcados para revisar:\n\n'+pendientes.join('\n')+'\n\n¿Ya los corroboraste y querés guardar de todas formas?');if(!seguirRevision){detalles.hidden=false;editar.textContent='Cerrar edición';const primera=Object.keys(revisiones)[0];inputs[primera]?.focus();return}}
    const payload=payloadExcel();if(!payload.ASEGURADO){estado.textContent='Completá el asegurado.';return}if(!payload.PATENTE){estado.textContent='Completá la patente.';return}
    guardar.disabled=true;editar.disabled=true;estado.textContent='Validando…';
    try{
      const valResp=await fetch('/api/validar-excel-fila',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({campos:payload,libro_id:'1'})});
      const val=await leerJsonSeguro(valResp);if(val.errores&&val.errores.length)throw Error(val.errores.join(' '));if(val.campos&&typeof val.campos==='object')Object.assign(payload,val.campos);
      if(val.avisos&&val.avisos.length){const seguir=confirm(val.avisos.join('\n')+'\n\n¿Guardar de todas formas?');if(!seguir){guardar.disabled=false;editar.disabled=false;estado.textContent='';return}}
      estado.textContent='Guardando…';
      // Se manda el estado completo para que la respuesta pueda preparar Envíos Ya,
      // pero backend separa POLIZA antes de escribir en el Excel.
      const completo=recoger();Object.assign(completo,payload);
      const resp=await fetch('/api/excel/agregar-fila',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({campos:completo,libro_id:'1'})});
      const d=await leerJsonSeguro(resp);if(!resp.ok||d.ok===false)throw Error(d.error||'No se pudo guardar el registro.');
      guardar.textContent='✓ Guardado en Excel';estado.textContent='';detalles.hidden=true;editar.textContent='Editar';editar.disabled=true;telefonoInput.disabled=true;Object.values(inputs).forEach(input=>input.disabled=true);b.dataset.altaActiva='0';
      if(messageId){try{await fetch(`/api/chats/${currentChatId}/messages/${messageId}/ui-state`,{method:'PATCH',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({ui_state:{saved_excel:true}})})}catch(_){}}
      if(d.texto_envios_ya){enviosPre.textContent=d.texto_envios_ya;enviosPanel.hidden=false;const avisos=Array.isArray(d.envios_ya_advertencias)?d.envios_ya_advertencias:[];enviosAviso.textContent=avisos.join(' ');enviosAviso.hidden=!avisos.length}
    }catch(e){estado.textContent=e?.message||'No se pudo guardar.';guardar.disabled=false;editar.disabled=false}
  });
}

function mostrarFichaOperativaAsegurado(ficha){
  const c=document.getElementById('chat');
  if(!c||!ficha||ficha.status!=='found')return;
  const r=document.createElement('div');r.className='msg assistant insured-profile-row';
  const card=document.createElement('section');card.className='insured-profile-card';
  const header=document.createElement('div');header.className='insured-profile-header';
  const title=document.createElement('div');title.innerHTML=`<small>FICHA OPERATIVA</small><strong></strong>`;
  title.querySelector('strong').textContent=String(ficha.asegurado||'Asegurado');header.appendChild(title);
  const badge=document.createElement('span');badge.className='insured-profile-badge';badge.textContent=`${Number(ficha.total_registros||0)} registro${Number(ficha.total_registros||0)===1?'':'s'}`;header.appendChild(badge);card.appendChild(header);
  const contacto=ficha.contacto||{},facts=[];
  if(contacto.telefono)facts.push(['Teléfono',contacto.telefono]);if(contacto.mail)facts.push(['Mail',contacto.mail]);if(contacto.dni)facts.push(['DNI',contacto.dni]);if(contacto.cuit)facts.push(['CUIT/CUIL',contacto.cuit]);
  if(Array.isArray(ficha.companias)&&ficha.companias.length)facts.push(['Compañía',ficha.companias.join(' · ')]);if(Array.isArray(ficha.polizas)&&ficha.polizas.length)facts.push(['Póliza',ficha.polizas.join(' · ')]);
  if(facts.length){const grid=document.createElement('div');grid.className='insured-profile-grid';facts.forEach(([k,v])=>{const item=document.createElement('div');item.className='insured-profile-fact';const lab=document.createElement('span');lab.textContent=k;const val=document.createElement('b');val.textContent=v;item.append(lab,val);grid.appendChild(item)});card.appendChild(grid)}
  const vehiculos=Array.isArray(ficha.vehiculos)?ficha.vehiculos:[];
  if(vehiculos.length){const st=document.createElement('div');st.className='insured-profile-section-title';st.textContent=vehiculos.length===1?'Vehículo':'Vehículos';card.appendChild(st);const list=document.createElement('div');list.className='insured-profile-vehicles';vehiculos.forEach(v=>{const row=document.createElement('div');row.className='insured-profile-vehicle';const main=document.createElement('div');main.className='insured-profile-vehicle-main';const name=document.createElement('strong');name.textContent=String(v.vehiculo||v.patente||'Vehículo');main.appendChild(name);const meta=[v.patente,v.compania,v.poliza&&`Pól. ${v.poliza}`,v.cobertura].filter(Boolean).join(' · ');if(meta){const sm=document.createElement('small');sm.textContent=meta;main.appendChild(sm)}row.appendChild(main);list.appendChild(row)});card.appendChild(list)}
  const actions=document.createElement('div');actions.className='insured-profile-actions';const btn=document.createElement('button');btn.type='button';btn.className='alta-secondary-btn';btn.textContent='Copiar resumen';btn.addEventListener('click',async()=>{const lines=[String(ficha.asegurado||'')];facts.forEach(([k,v])=>lines.push(`${k}: ${v}`));vehiculos.forEach(v=>lines.push([v.vehiculo,v.patente,v.compania,v.poliza&&`Póliza ${v.poliza}`].filter(Boolean).join(' · ')));const ok=await copiarTextoSeguro(lines.filter(Boolean).join('\n'));if(ok){const prev=btn.textContent;btn.textContent='✓ Copiado';setTimeout(()=>btn.textContent=prev,1400)}});actions.appendChild(btn);card.appendChild(actions);r.appendChild(card);c.appendChild(r);
}

function mostrarEnviosChat(payload,opciones={}){
  const c=document.getElementById('chat');
  if(!c||!payload||typeof payload!=='object')return;
  const existente=opciones.card instanceof HTMLElement?opciones.card:null;
  const card=existente||document.createElement('div');card.className='envios-chat-card';card.replaceChildren();
  if(!existente){const r=document.createElement('div');r.className='msg assistant';const b=document.createElement('div');b.className='bubble';b.appendChild(card);r.appendChild(b);c.appendChild(r)}

  const estado=String(payload.estado||'');const resumen=payload.resumen||{};
  const title=document.createElement('b');title.textContent=estado==='mapeo'?'Confirmá las columnas':'Contactos detectados';card.appendChild(title);
  const stats=document.createElement('div');stats.className='envios-chat-summary';
  const agregarStat=(v,label)=>{const x=document.createElement('div');x.className='envios-chat-stat';const b=document.createElement('b');b.textContent=Number(v||0).toLocaleString('es-AR');const sp=document.createElement('span');sp.textContent=label;x.append(b,sp);stats.appendChild(x)};
  if(estado==='mapeo')agregarStat(resumen.contactos_detectados||0,'detectados hasta ahora');
  else{agregarStat(resumen.exportables||0,'válidos');agregarStat(resumen.revisar||0,'para revisar');agregarStat(resumen.omitidos_sin_celular||0,'sin celular')}
  card.appendChild(stats);

  if(estado==='mapeo'){
    const wrap=document.createElement('div');wrap.className='envios-chat-map';
    (payload.mapeos||[]).forEach(m=>{
      const art=document.createElement('article');art.dataset.mapFile=String(m.file_index);
      const h=document.createElement('b');h.textContent=String(m.nombre||'Planilla');art.appendChild(h);
      const grid=document.createElement('div');grid.className='envios-chat-map-grid';
      const detect=m.detectado||{};
      ['apellido','nombre','nombre_completo','celular'].forEach(campo=>{
        const lab=document.createElement('label');lab.textContent=campo==='nombre_completo'?'Nombre completo':campo.charAt(0).toUpperCase()+campo.slice(1);
        const sel=document.createElement('select');sel.dataset.field=campo;
        const none=document.createElement('option');none.value='';none.textContent='— Elegir —';sel.appendChild(none);
        (m.columnas||[]).forEach(col=>{const opt=document.createElement('option');opt.value=String(col.index);opt.textContent=String(col.label||`Columna ${Number(col.index)+1}`);if(String(detect[campo])===String(col.index))opt.selected=true;sel.appendChild(opt)});
        lab.appendChild(sel);grid.appendChild(lab);
      });
      art.appendChild(grid);wrap.appendChild(art);
    });
    card.appendChild(wrap);
    const actions=document.createElement('div');actions.className='envios-chat-actions';const btn=document.createElement('button');btn.type='button';btn.className='envios-chat-primary';btn.textContent='Aplicar y continuar';actions.appendChild(btn);card.appendChild(actions);
    btn.addEventListener('click',async()=>{
      const manual={};card.querySelectorAll('[data-map-file]').forEach(row=>{const one={};row.querySelectorAll('select[data-field]').forEach(sel=>{if(sel.value!=='')one[sel.dataset.field]=Number(sel.value)});manual[row.dataset.mapFile]=one});
      btn.disabled=true;btn.textContent='Procesando…';
      try{const r=await fetch('/api/chat/envios/reprocesar',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:payload.token,manual_mapping:manual})});const d=await leerJsonSeguro(r);if(!r.ok||d.ok===false)throw Error(d.error||'No pude aplicar el mapeo.');mostrarEnviosChat(d.envios_chat,{card})}catch(e){btn.disabled=false;btn.textContent='Aplicar y continuar';window.showToast?.(e?.message||'No pude aplicar el mapeo.','warning')}
    });
    return;
  }

  const note=document.createElement('div');note.className='tabulado-flota-help';note.textContent='Revisá el resumen y confirmá para generar el CSV final de Envíos Ya.';card.appendChild(note);
  const actions=document.createElement('div');actions.className='envios-chat-actions';const btn=document.createElement('button');btn.type='button';btn.className='envios-chat-primary';btn.textContent='Generar CSV';actions.appendChild(btn);card.appendChild(actions);
  btn.addEventListener('click',async()=>{
    btn.disabled=true;btn.textContent='Generando…';
    try{const r=await fetch('/api/chat/envios/generar',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:payload.token})});const d=await leerJsonSeguro(r);if(!r.ok||d.ok===false)throw Error(d.error||'No pude generar el CSV.');const a=document.createElement('a');a.className='envios-chat-primary';a.href=d.download_url;a.textContent='Descargar CSV para Envíos Ya';a.setAttribute('download','');actions.replaceChildren(a)}catch(e){btn.disabled=false;btn.textContent='Generar CSV';window.showToast?.(e?.message||'No pude generar el CSV.','warning')}
  });
}

function tieneUiPrincipal(d){
  if(!d||typeof d!=='object')return false;
  return !!(
    d.cedula_detectada||d.documento_personal_detectado||
    d.actualizacion_alta_asegurado||d.tabulado_alta_asegurado||d.campos_guardar_alta_asegurado||
    d.texto_envios_ya||d.ficha_operativa_asegurado||d.tabulado_flota||d.envios_chat
  );
}
function textoVisibleAsistente(texto,d){
  const t=String(texto||'').trim();
  if(!t||!tieneUiPrincipal(d))return t;
  // Las advertencias/errores siguen visibles. Sólo se oculta la prosa de éxito
  // redundante cuando la tarjeta estructurada ya contiene la respuesta.
  const alerta=/\b(no pude|no encontr|error|fall[oó]|revis[aá]|falt[aó]|diferentes|no combin|no disponible|no legible|advertencia)\b/i.test(t);
  if(alerta)return t;
  return t.length<=700?'':t;
}

function renderizarUiPersistida(mensaje){
  const md=(mensaje?.metadata&&typeof mensaje.metadata==='object')?mensaje.metadata:{};
  const d=(md.ui&&typeof md.ui==='object')?md.ui:{};
  const uiState=(md.ui_state&&typeof md.ui_state==='object')?md.ui_state:{};
  const messageId=Number(mensaje?.id||0);
  if(d.propuesta_excel)mostrarPropuestaExcel(d.propuesta_excel);
  if(d.propuesta_metadato)mostrarPropuestaMetadato(d.propuesta_metadato);
  if(d.tabulado_flota)mostrarTabuladoFlota(d.tabulado_flota);
  if(d.cedula_detectada)mostrarCedulaDetectada(d.cedula_detectada,d.cedula_advertencias,{messageId,uiState,altaPrefill:d.borrador_alta_desde_cedula,altaRevisiones:d.alta_revisiones,altaYaPreparada:!!d.campos_guardar_alta_asegurado});
  if(d.documento_personal_detectado)mostrarDocumentoPersonalDetectado(d.documento_personal_detectado,d.documento_personal_advertencias);
  if(d.actualizacion_alta_asegurado){
    const actualizado=actualizarFormularioAltaActivo(d.actualizacion_alta_asegurado);
    if(!actualizado)mostrarOpcionesAltaAsegurado(d.tabulado_alta_asegurado,d.actualizacion_alta_asegurado,{messageId,uiState,revisiones:d.alta_revisiones,origen:d.alta_origen});
  }else if(d.tabulado_alta_asegurado||d.campos_guardar_alta_asegurado){
    mostrarOpcionesAltaAsegurado(d.tabulado_alta_asegurado,d.campos_guardar_alta_asegurado,{messageId,uiState,revisiones:d.alta_revisiones,origen:d.alta_origen});
  }
  if(d.texto_envios_ya&&!d.actualizacion_alta_asegurado&&!d.campos_guardar_alta_asegurado)mostrarTextoEnviosYa(d.texto_envios_ya);
  if(d.ficha_operativa_asegurado)mostrarFichaOperativaAsegurado(d.ficha_operativa_asegurado);
  if(d.envios_chat)mostrarEnviosChat(d.envios_chat,{messageId});
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
    comando:'/ficha',
    descripcion:'Ver ficha operativa del asegurado',
    plantilla:'/ficha '
  },
  {
    comando:'/flota',
    descripcion:'Cargar datos de una póliza para completar una flota',
    plantilla:'/flota'
  },
  {
    comando:'/coti',
    descripcion:'Abrir Cotización ATM',
    plantilla:'/coti'
  },
  {
    comando:'/mail',
    descripcion:'Enviar un correo desde OficinaIA indicando destinatario, asunto y mensaje. Podés adjuntar el archivo del turno actual.',
    plantilla:'/mail destinatario@correo.com asunto Asunto mensaje Mensaje'
  },
  {
    comando:'/cuit',
    descripcion:'Buscar CUIT/CUIL en ARCA',
    plantilla:'/cuit '
  },
  {
    comando:'/cuil',
    descripcion:'Buscar CUIT/CUIL en ARCA',
    plantilla:'/cuil '
  }
];
function ejecutarClickComando(cmd,input){
  if(cmd.comando==='/coti'){
    input.value='';
    indiceComando=-1;
    cerrarMenuComandos();
    size();
    abrirCotizadorATM();
    return;
  }
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
  ejecutarClickComando(cmd,input);
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

function cerrarMenuAccionesChat(){
  const menu=document.getElementById('chatActionMenu');
  const btn=document.getElementById('chatActionBtn');
  if(menu)menu.hidden=true;
  if(btn)btn.setAttribute('aria-expanded','false');
}

function abrirSelectorArchivoChat(modo){
  const input=document.getElementById('archivoInput');
  if(!input)return;
  input.accept=modo==='photos'
    ?'image/png,.png,image/jpeg,.jpg,.jpeg,image/webp,.webp'
    :'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,.xlsx,.xlsm,application/pdf,.pdf,text/plain,.txt,text/csv,.csv,image/png,.png,image/jpeg,.jpg,.jpeg,image/webp,.webp';
  input.value='';
  input.click();
}

function prepararAccionComposer(texto){
  const input=document.getElementById('mensaje');
  if(!input)return;
  input.value=texto;
  composerEditSeq++;
  if(typeof size==='function')size();
  input.focus();
}

function SpeechRecognitionCtor(){return window.SpeechRecognition||window.webkitSpeechRecognition||null}
function dictadoDisponible(){return !!SpeechRecognitionCtor()}
function unirTextoDictado(base,dictado){
  const a=String(base||'').trimEnd(),b=String(dictado||'').trim();
  if(!a)return b;if(!b)return a;return a+' '+b;
}
function actualizarBotonDictado(){
  const btn=document.getElementById('dictationBtn');
  if(!btn)return;
  const disponible=dictadoDisponible();
  btn.classList.toggle('is-listening',dictationActive);
  btn.classList.toggle('is-unavailable',!disponible);
  btn.setAttribute('aria-pressed',dictationActive?'true':'false');
  btn.setAttribute('aria-label',dictationActive?'Detener dictado':'Dictar mensaje');
  btn.title=dictationActive?'Detener dictado (Esc cancela)':'Dictar mensaje';
}
function escribirResultadoDictado(interim=''){
  const input=document.getElementById('mensaje');if(!input)return;
  dictationProgrammaticUpdate=true;
  input.value=unirTextoDictado(dictationBaseText,[dictationFinalText,interim].filter(Boolean).join(' '));
  composerEditSeq++;if(typeof size==='function')size();dictationProgrammaticUpdate=false;
}
function finalizarDictado({cancelar=false}={}){
  const input=document.getElementById('mensaje');
  if(cancelar&&input){dictationProgrammaticUpdate=true;input.value=dictationBaseText;composerEditSeq++;if(typeof size==='function')size();dictationProgrammaticUpdate=false}
  dictationCancelRequested=!!cancelar;
  if(dictationRecognition){try{dictationRecognition.abort()}catch(_){try{dictationRecognition.stop()}catch(__){}}}
  dictationActive=false;actualizarBotonDictado();
  if(cancelar&&window.showToast)showToast('Dictado cancelado.','info');
  input?.focus();
}
function iniciarDictado(){
  const Ctor=SpeechRecognitionCtor(),input=document.getElementById('mensaje');if(!input)return;
  if(!Ctor){if(window.showToast)showToast('Dictado no disponible en este navegador.','warning');else alert('Dictado no disponible en este navegador.');return}
  if(dictationActive){try{dictationRecognition?.stop()}catch(_){finalizarDictado()}return}
  cerrarMenuAccionesChat();cerrarMenuComandos();
  dictationBaseText=input.value;dictationFinalText='';dictationCancelRequested=false;
  const rec=new Ctor();dictationRecognition=rec;rec.lang='es-AR';rec.continuous=true;rec.interimResults=true;rec.maxAlternatives=1;
  rec.onstart=()=>{dictationActive=true;actualizarBotonDictado();if(window.showToast)showToast('Escuchando… hablá normalmente.','info')};
  rec.onresult=e=>{let interim='';for(let n=e.resultIndex;n<e.results.length;n++){const texto=String(e.results[n][0]?.transcript||'').trim();if(!texto)continue;if(e.results[n].isFinal)dictationFinalText=(dictationFinalText+' '+texto).trim();else interim=(interim+' '+texto).trim()}escribirResultadoDictado(interim)};
  rec.onerror=e=>{const tipo=String(e?.error||'');if(tipo==='aborted'||dictationCancelRequested)return;if(tipo==='not-allowed'||tipo==='service-not-allowed'){window.showToast?.('Necesito permiso de micrófono para dictar.','warning')}else if(tipo==='no-speech'){window.showToast?.('No escuché voz. Podés intentarlo de nuevo.','info')}else{window.showToast?.('No se pudo continuar el dictado.','warning')}};
  rec.onend=()=>{const cancelado=dictationCancelRequested;dictationActive=false;dictationRecognition=null;dictationCancelRequested=false;actualizarBotonDictado();if(!cancelado)input.focus()};
  try{rec.start()}catch(_){dictationRecognition=null;dictationActive=false;actualizarBotonDictado();window.showToast?.('No se pudo iniciar el dictado.','warning')}
}
function inicializarDictadoChat(){
  const btn=document.getElementById('dictationBtn');if(!btn||btn.dataset.wired==='1')return;
  btn.dataset.wired='1';btn.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();iniciarDictado()});actualizarBotonDictado();
}
function ejecutarAccionRapidaChat(accion){
  cerrarMenuAccionesChat();
  if(accion==='document'){abrirSelectorArchivoChat('document');return}
  if(accion==='photos'){abrirSelectorArchivoChat('photos');return}
  if(accion==='dictation'){iniciarDictado();return}
  if(accion==='portfolio'){prepararAccionComposer('Buscá en mi cartera ');return}
  if(accion==='cuit'){prepararAccionComposer('/cuit ');return}
  if(accion==='atm'){abrirCotizadorATM();return}
  if(accion==='mail'){prepararAccionComposer('/mail ');return}
  if(accion==='alta'){
    const input=document.getElementById('mensaje'),cmd=COMANDOS_CHAT.find(x=>x.comando==='/guardar asegurado');
    if(input&&cmd)ejecutarClickComando(cmd,input);return;
  }
  if(accion==='notes'){document.getElementById('notasBtn')?.click()}
}
let atmCoberturasDetectadas=[];
let atmCatalogoCoberturas=[];
let atmTabActual='capture';
let atmRecalculoTimer=null;

const ATM_CODIGOS_ORDEN=['A','A1','B','B1','B2','B3','B4','B5','C','CPr','CB','TR'];

async function asegurarCatalogoATM(){
  if(atmCatalogoCoberturas.length)return atmCatalogoCoberturas;
  try{
    const resp=await fetch('/api/atm/catalogo',{credentials:'same-origin'});
    const d=await leerJsonSeguro(resp);
    if(resp.ok&&d.ok!==false&&Array.isArray(d.coberturas))atmCatalogoCoberturas=d.coberturas;
  }catch(_){/* El lector sigue pudiendo cargar el catálogo devuelto por la captura. */}
  if(!atmCatalogoCoberturas.length){
    atmCatalogoCoberturas=ATM_CODIGOS_ORDEN.map((codigo,i)=>({codigo,tooltip:codigo,orden:(i+1)*10,detectable:true,franquicia:codigo==='TR'}));
  }
  return atmCatalogoCoberturas;
}
function entradaCatalogoATM(codigo){return atmCatalogoCoberturas.find(x=>x.codigo===codigo)||null}
function detectadasPorCodigoATM(codigo){return atmCoberturasDetectadas.filter(c=>String(c.codigo||'')===codigo)}
function coberturaDisponibleATM(codigo){return detectadasPorCodigoATM(codigo).length>0}
function seleccionadasATM(){
  return atmCoberturasDetectadas.filter(c=>!!c.ofrecer).sort((a,b)=>{
    const oa=Number(a.orden||entradaCatalogoATM(a.codigo)?.orden||999),ob=Number(b.orden||entradaCatalogoATM(b.codigo)?.orden||999);
    if(oa!==ob)return oa-ob;
    return Number(a.franquicia_pct||0)-Number(b.franquicia_pct||0);
  });
}
function invalidarPropuestaATM(){
  const wrap=document.getElementById('atmProposal'),area=document.getElementById('atmProposalText');
  if(wrap)wrap.hidden=true;if(area)area.value='';
  const status=document.getElementById('atmCaptureStatus');
  if(status&&String(status.textContent||'').includes('Propuesta lista'))estadoCapturaATM('');
}

async function abrirCotizadorATM(lectura=null){
  const modal=document.getElementById('atmCotiModal');
  if(!modal)return;
  modal.hidden=false;
  modal.setAttribute('aria-hidden','false');
  const error=document.getElementById('atmCotiError');if(error)error.hidden=true;
  await asegurarCatalogoATM();
  const descuento=document.getElementById('atmDescuento');if(descuento&&!descuento.value.trim())descuento.value='50';
  invalidarPropuestaATM();
  if(lectura&&typeof lectura==='object')cargarLecturaATMCapture(lectura);
  else{
    cambiarTabATM('capture');
    renderMatrizCoberturasATM();
    renderResumenSeleccionATM();
  }
  setTimeout(()=>document.getElementById(atmTabActual==='capture'?'atmCaptureDrop':'atmPrecioBase')?.focus(),0);
}
function cerrarCotizadorATM(){
  const modal=document.getElementById('atmCotiModal');
  if(!modal)return;
  modal.hidden=true;
  modal.setAttribute('aria-hidden','true');
  document.getElementById('mensaje')?.focus();
}
function cambiarTabATM(tab){
  atmTabActual=tab==='manual'?'manual':'capture';
  document.querySelectorAll('[data-atm-tab]').forEach(btn=>btn.classList.toggle('active',btn.dataset.atmTab===atmTabActual));
  document.querySelectorAll('[data-atm-panel]').forEach(panel=>panel.hidden=panel.dataset.atmPanel!==atmTabActual);
  const descuento=document.querySelector('.atm-coti-discountbar');
  if(descuento){
    if(atmTabActual==='capture'){
      const drop=document.getElementById('atmCaptureDrop');if(drop)drop.insertAdjacentElement('afterend',descuento);
    }else{
      const panel=document.querySelector('[data-atm-panel="manual"]');if(panel)panel.prepend(descuento);
    }
  }
}
function mostrarErrorATM(msg){
  const e=document.getElementById('atmCotiError');if(!e)return;
  e.textContent=msg||'No se pudo calcular.';e.hidden=false;
}
async function cotizarPrecioATM(precio){
  const descuento=document.getElementById('atmDescuento')?.value?.trim()||'';
  const resp=await fetch('/api/atm/cotizar',{
    method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({precio_base:String(precio||''),descuento:descuento||null})
  });
  const d=await leerJsonSeguro(resp);
  if(!resp.ok||d.ok===false)throw Error(d.error||'No se pudo calcular la cotización ATM.');
  return d;
}
async function calcularCotizacionATM(){
  const precio=document.getElementById('atmPrecioBase')?.value?.trim()||'';
  const error=document.getElementById('atmCotiError');if(error)error.hidden=true;
  try{
    const d=await cotizarPrecioATM(precio);
    document.getElementById('atmResBaseDto').textContent=d.precio_base_descuento_formateado;
    document.getElementById('atmResAdheridoDto').textContent=d.precio_adherido_descuento_formateado;
    document.getElementById('atmCotiBadge').textContent=d.descuento_formateado;
    document.getElementById('atmCotiResult').hidden=false;
  }catch(e){mostrarErrorATM(e?.message||'No se pudo calcular.')}
}
function estadoCapturaATM(texto,tipo=''){
  const el=document.getElementById('atmCaptureStatus');if(!el)return;
  el.textContent=texto||'';el.hidden=!texto;el.className='atm-capture-status'+(tipo?' '+tipo:'');
}
function actualizarDropCapturaATM(cargada=false){
  const title=document.getElementById('atmCaptureDropTitle');
  if(title)title.textContent=cargada?'✓ Captura cargada · Ctrl+V para reemplazar':'Pegá con Ctrl+V o elegí una imagen';
  document.getElementById('atmCaptureDrop')?.classList.toggle('has-file',!!cargada);
}
function tooltipCodigoATM(codigo,detectadas=[]){
  if(detectadas.length){
    const titulos=[...new Set(detectadas.map(c=>String(c.titulo_leido||c.tooltip||'').trim()).filter(Boolean))];
    if(titulos.length)return titulos.join(' / ');
  }
  const cat=entradaCatalogoATM(codigo);
  return String(cat?.tooltip||cat?.titulo_atm||codigo);
}
function codigoSeleccionadoATM(codigo){return detectadasPorCodigoATM(codigo).some(c=>!!c.ofrecer)}
function togglearCodigoATM(codigo){
  const items=detectadasPorCodigoATM(codigo);
  if(!items.length)return;
  invalidarPropuestaATM();
  if(codigo==='TR'){
    const alguno=items.some(c=>c.ofrecer);
    items.forEach(c=>c.ofrecer=false);
    if(!alguno){
      const preferida=items.find(c=>String(c.franquicia_pct||'').trim()==='3')||items[0];
      if(preferida)preferida.ofrecer=true;
    }
  }else{
    const nuevo=!items[0].ofrecer;
    items.forEach(c=>c.ofrecer=false);
    items[0].ofrecer=nuevo;
  }
  renderMatrizCoberturasATM();
  renderResumenSeleccionATM();
  programarRecalculoSeleccionATM();
}
function togglearFranquiciaATM(pct){
  const items=detectadasPorCodigoATM('TR');
  const item=items.find(c=>String(c.franquicia_pct||'').trim()===String(pct));
  if(!item)return;
  invalidarPropuestaATM();
  const yaActivo=!!item.ofrecer;
  items.forEach(c=>c.ofrecer=false);
  if(!yaActivo)item.ofrecer=true;
  renderMatrizCoberturasATM();renderResumenSeleccionATM();programarRecalculoSeleccionATM();
}
function crearCeldaCodigoATM(codigo){
  const items=detectadasPorCodigoATM(codigo),cat=entradaCatalogoATM(codigo);
  const disponible=items.length>0;
  const btn=document.createElement('button');
  btn.type='button';btn.className='atm-code-cell';btn.textContent=codigo;
  btn.dataset.atmCode=codigo;
  const tooltip=tooltipCodigoATM(codigo,items);
  btn.title=tooltip;
  btn.setAttribute('aria-label',`${codigo}: ${tooltip}`);
  btn.setAttribute('aria-disabled',disponible?'false':'true');
  if(!disponible)btn.classList.add('is-unavailable');
  if(codigoSeleccionadoATM(codigo))btn.classList.add('active');
  if(items.some(c=>c.requiere_revision))btn.classList.add('is-review');
  if(cat?.detectable===false)btn.classList.add('is-pending-map');
  btn.addEventListener('click',()=>{if(disponible)togglearCodigoATM(codigo)});
  return btn;
}
function crearCeldaFranquiciaATM(pct){
  const item=detectadasPorCodigoATM('TR').find(c=>String(c.franquicia_pct||'').trim()===String(pct));
  const btn=document.createElement('button');
  btn.type='button';btn.className='atm-code-cell atm-franchise-chip';btn.textContent=`${pct}%`;
  btn.dataset.atmFranquicia=String(pct);
  const tooltip=`Todo Riesgo · Franquicia ${pct}%`;
  btn.title=tooltip;btn.setAttribute('aria-label',tooltip);
  btn.setAttribute('aria-disabled',item?'false':'true');
  if(!item)btn.classList.add('is-unavailable');
  if(item?.ofrecer)btn.classList.add('active');
  btn.addEventListener('click',()=>{if(item)togglearFranquiciaATM(pct)});
  return btn;
}
function renderMatrizCoberturasATM(){
  const matrix=document.getElementById('atmCoverageMatrix');if(!matrix)return;
  matrix.innerHTML='';
  ATM_CODIGOS_ORDEN.forEach(codigo=>{
    const wrap=document.createElement('div');wrap.className='atm-code-slot';
    wrap.appendChild(crearCeldaCodigoATM(codigo));matrix.appendChild(wrap);
  });
  ['3','6'].forEach(pct=>{
    const wrap=document.createElement('div');wrap.className='atm-code-slot atm-franchise-slot';
    wrap.appendChild(crearCeldaFranquiciaATM(pct));matrix.appendChild(wrap);
  });
}
function nombreSeleccionATM(c){
  const codigo=String(c.codigo||c.nombre_corto||'').trim()||'Cobertura';
  if(codigo==='TR'&&String(c.franquicia_pct||'').trim())return `TR ${c.franquicia_pct}%`;
  return codigo;
}
function renderResumenSeleccionATM(){
  const wrap=document.getElementById('atmSelectedSummary'),actions=document.getElementById('atmCaptureActions');if(!wrap)return;
  const seleccion=seleccionadasATM();wrap.innerHTML='';
  seleccion.forEach(c=>{
    const item=document.createElement('div');item.className='atm-selected-item';
    const code=document.createElement('b');code.textContent=nombreSeleccionATM(c);code.title=String(c.titulo_leido||c.tooltip||'');
    const ef=document.createElement('span');ef.innerHTML=`<small>Cupones</small><strong>${esc(c.precio_efectivo_comercial||'—')}</strong>`;
    const ad=document.createElement('span');ad.innerHTML=`<small>CBU / tarjeta</small><strong>${esc(c.precio_adherido_comercial||'—')}</strong>`;
    item.append(code,ef,ad);wrap.appendChild(item);
  });
  wrap.hidden=!seleccion.length;
  if(actions)actions.hidden=!atmCoberturasDetectadas.length;
  const gen=document.getElementById('atmGenerateProposal');if(gen)gen.disabled=!seleccion.length;
}
function cargarLecturaATMCapture(lectura){
  const lista=Array.isArray(lectura?.coberturas)?lectura.coberturas:[];
  atmCoberturasDetectadas=lista.map(x=>({...x,ofrecer:false}));
  invalidarPropuestaATM();
  cambiarTabATM('capture');
  renderMatrizCoberturasATM();renderResumenSeleccionATM();actualizarDropCapturaATM(!!lista.length);
  const adv=Array.isArray(lectura?.advertencias)?lectura.advertencias.filter(Boolean):[];
  const sinCodigo=lista.filter(x=>!x.codigo).length;
  if(lista.length){
    let msg=`✓ ${lista.length} cobertura${lista.length===1?'':'s'} detectada${lista.length===1?'':'s'}`;
    if(sinCodigo)msg+=` · ${sinCodigo} sin código confirmado`;
    if(adv.length)msg+=` · ${adv.slice(0,1).join(' ')}`;
    estadoCapturaATM(msg,sinCodigo||adv.length?'':'ok');
  }else estadoCapturaATM('No pude confirmar coberturas y precios en esa captura.','error');
}
async function leerCapturaATM(file){
  if(!file)return;
  estadoCapturaATM('Leyendo captura…');actualizarDropCapturaATM(true);
  atmCoberturasDetectadas=[];renderMatrizCoberturasATM();renderResumenSeleccionATM();
  invalidarPropuestaATM();
  try{
    const fd=new FormData();fd.append('captura',file,file.name||'captura-atm.png');
    const resp=await fetch('/api/atm/leer-captura',{method:'POST',body:fd,credentials:'same-origin'});
    const d=await leerJsonSeguro(resp);
    if(!resp.ok||d.ok===false)throw Error(d.error||'No pude leer la captura ATM.');
    cargarLecturaATMCapture(d);
  }catch(e){actualizarDropCapturaATM(false);estadoCapturaATM(e?.message||'No pude leer la captura ATM.','error')}
}
async function calcularCoberturasSeleccionadasATM(){
  const seleccion=seleccionadasATM();if(!seleccion.length){renderResumenSeleccionATM();return true}
  try{
    await Promise.all(seleccion.map(async c=>{
      const d=await cotizarPrecioATM(c.precio_base);
      c.precio_efectivo_exacto=d.precio_base_descuento;
      c.precio_adherido_exacto=d.precio_adherido_descuento;
      c.precio_efectivo_comercial=d.precio_base_descuento_comercial_formateado||'';
      c.precio_adherido_comercial=d.precio_adherido_descuento_comercial_formateado||'';
      c.precio_efectivo_final=d.precio_base_descuento_formateado;
      c.precio_adherido_final=d.precio_adherido_descuento_formateado;
      c.descuento_formateado=d.descuento_formateado;
    }));
    renderResumenSeleccionATM();return true;
  }catch(e){estadoCapturaATM(e?.message||'No pude calcular los precios finales.','error');return false}
}
function programarRecalculoSeleccionATM(){
  clearTimeout(atmRecalculoTimer);
  if(!seleccionadasATM().length)return;
  atmRecalculoTimer=setTimeout(()=>calcularCoberturasSeleccionadasATM(),180);
}
function numeroPrecioATM(valor,formateado=''){
  const exacto=Number(String(valor??'').replace(',','.'));
  if(Number.isFinite(exacto)&&exacto>0)return exacto;
  const limpio=String(formateado||'').replace(/[^0-9,.-]/g,'').replace(/\./g,'').replace(',','.');
  const fallback=Number(limpio);return Number.isFinite(fallback)?fallback:NaN;
}
function redondearComercialMilesATM(valor){
  const n=Number(valor);if(!Number.isFinite(n))return NaN;
  return Math.floor((n+500)/1000)*1000;
}
function formatearPrecioComercialATM(valorExacto,formateadoExacto=''){
  const n=numeroPrecioATM(valorExacto,formateadoExacto);if(!Number.isFinite(n))return formateadoExacto||'—';
  return '$'+redondearComercialMilesATM(n).toLocaleString('es-AR');
}
function nombreClientePropuestaATM(c){
  const codigo=String(c.codigo||'');
  if(codigo==='TR'){
    const pct=String(c.franquicia_pct||'').trim();
    return `Todo Riesgo – Franquicia ${pct}%`;
  }
  return String(c.nombre_cliente||entradaCatalogoATM(codigo)?.nombre_cliente||c.titulo_leido||c.nombre||'Cobertura').trim();
}
function descripcionPropuestaATM(c){
  const codigo=String(c.codigo||'');
  if(codigo==='TR'){
    const pct=String(c.franquicia_pct||'').trim();
    return `Incluye responsabilidad civil, incendio total y parcial, robo total y parcial, destrucción total y daños parciales por accidente. Además incluye ruedas, vidrios, granizo, cerraduras y grúa.\n\nEn caso de un daño parcial, queda a cargo del asegurado una franquicia equivalente al ${pct}% de la suma asegurada. Todo gasto que supere ese importe queda a cargo de la compañía.`;
  }
  return String(c.descripcion_cliente||c.descripcion||entradaCatalogoATM(codigo)?.descripcion_cliente||entradaCatalogoATM(codigo)?.descripcion||'').trim();
}
async function generarPropuestaATM(){
  const seleccion=seleccionadasATM();
  if(!seleccion.length){estadoCapturaATM('Elegí al menos una cobertura para generar la propuesta.','error');return}
  for(const c of seleccion){
    if(c.codigo==='TR'&&!String(c.franquicia_pct||'').trim()){
      estadoCapturaATM('Elegí la franquicia de Todo Riesgo.','error');return;
    }
  }
  const ok=await calcularCoberturasSeleccionadasATM();if(!ok)return;
  const finalSeleccion=seleccionadasATM();
  const lines=['¡Hola! Te paso algunas opciones de cobertura para tu vehículo para que puedas compararlas y elegir la que mejor te sirva:',''];
  finalSeleccion.forEach((c,i)=>{
    lines.push(nombreClientePropuestaATM(c));
    const desc=descripcionPropuestaATM(c);if(desc)lines.push(desc);
    const cupones=c.precio_efectivo_comercial||formatearPrecioComercialATM(c.precio_efectivo_exacto,c.precio_efectivo_final);
    const adherido=c.precio_adherido_comercial||formatearPrecioComercialATM(c.precio_adherido_exacto,c.precio_adherido_final);
    lines.push(`${cupones} con cupones · ${adherido} con CBU o tarjeta adherida`);
    if(i<finalSeleccion.length-1)lines.push('');
  });
  const text=lines.join('\n');
  const area=document.getElementById('atmProposalText'),wrap=document.getElementById('atmProposal');
  if(area)area.value=text;if(wrap)wrap.hidden=false;
  estadoCapturaATM('Propuesta lista para copiar.','ok');
}
async function copiarPropuestaATM(){
  const text=document.getElementById('atmProposalText')?.value||'';if(!text)return;
  const ok=await copiarTextoSeguro(text);window.showToast?.(ok?'Propuesta copiada.':'No pude copiar automáticamente.',ok?'success':'warning');
}
function inicializarCotizadorATM(){
  const modal=document.getElementById('atmCotiModal');
  if(!modal||modal.dataset.wired==='1')return;
  modal.dataset.wired='1';
  asegurarCatalogoATM().then(()=>renderMatrizCoberturasATM());
  document.getElementById('atmCotiClose')?.addEventListener('click',cerrarCotizadorATM);
  document.getElementById('atmCotiSubmit')?.addEventListener('click',calcularCotizacionATM);
  document.getElementById('atmGenerateProposal')?.addEventListener('click',generarPropuestaATM);
  document.getElementById('atmCopyProposal')?.addEventListener('click',copiarPropuestaATM);
  document.querySelectorAll('[data-atm-tab]').forEach(btn=>btn.addEventListener('click',()=>cambiarTabATM(btn.dataset.atmTab)));
  document.querySelectorAll('[data-atm-descuento]').forEach(btn=>btn.addEventListener('click',()=>{const input=document.getElementById('atmDescuento');if(input){input.value=btn.dataset.atmDescuento;invalidarPropuestaATM();programarRecalculoSeleccionATM();input.focus()}}));
  document.getElementById('atmDescuento')?.addEventListener('input',()=>{invalidarPropuestaATM();programarRecalculoSeleccionATM()});
  modal.addEventListener('click',e=>{if(e.target===modal)cerrarCotizadorATM()});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!modal.hidden)cerrarCotizadorATM()});
  document.getElementById('atmPrecioBase')?.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();calcularCotizacionATM()}});

  const capture=document.getElementById('atmCaptureInput'),drop=document.getElementById('atmCaptureDrop');
  drop?.setAttribute('tabindex','0');
  capture?.addEventListener('change',()=>{const f=capture.files?.[0];if(f)leerCapturaATM(f);capture.value=''});
  ['dragenter','dragover'].forEach(ev=>drop?.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('drag')}));
  ['dragleave','drop'].forEach(ev=>drop?.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('drag')}));
  drop?.addEventListener('drop',e=>{const f=[...(e.dataTransfer?.files||[])].find(x=>String(x.type||'').startsWith('image/'));if(f)leerCapturaATM(f)});
  modal.addEventListener('paste',e=>{
    if(modal.hidden||atmTabActual!=='capture')return;
    const item=[...(e.clipboardData?.items||[])].find(x=>String(x.type||'').startsWith('image/'));
    const blob=item?.getAsFile?.();if(!blob)return;
    e.preventDefault();
    const ext=String(blob.type||'').includes('jpeg')?'jpg':String(blob.type||'').includes('webp')?'webp':'png';
    leerCapturaATM(new File([blob],`captura-atm.${ext}`,{type:blob.type||'image/png'}));
  });
  const descuento=document.getElementById('atmDescuento');if(descuento&&!descuento.value.trim())descuento.value='50';
  cambiarTabATM('capture');
}

function inicializarMenuAccionesChat(){
  const btn=document.getElementById('chatActionBtn'),menu=document.getElementById('chatActionMenu');
  if(!btn||!menu||btn.dataset.wired==='1')return;
  btn.dataset.wired='1';
  btn.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();const abrir=menu.hidden;cerrarMenuComandos();menu.hidden=!abrir;btn.setAttribute('aria-expanded',abrir?'true':'false')});
  menu.addEventListener('click',e=>{const item=e.target.closest('[data-chat-action]');if(!item)return;e.preventDefault();ejecutarAccionRapidaChat(item.dataset.chatAction)});
  document.addEventListener('click',e=>{if(menu.hidden)return;if(e.target.closest('#chatActionMenu')||e.target.closest('#chatActionBtn'))return;cerrarMenuAccionesChat()});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')cerrarMenuAccionesChat()});
}

async function enviarMensaje(){
  const i=document.getElementById('mensaje'),b=document.querySelector('.send'),pdf=document.getElementById('archivoInput');
  if(!i||enviandoMensaje)return;
  // La inicialización y el primer envío nunca crean chats en paralelo.
  if(chatInitInProgress){try{await chatInitReadyPromise}catch(_){}}
  if(enviandoMensaje)return;
  const textoOriginal=i.value;
  const editSeqAlEnviar=composerEditSeq;
  const t=textoOriginal.trim();
  const archivos=archivosAdjuntosChat.length?[...archivosAdjuntosChat]:Array.from(pdf?.files||[]).slice(0,MAX_CHAT_ATTACHMENTS);
  if(!t&&!archivos.length)return;
  enviandoMensaje=true;
  if(b)b.disabled=true;
  const c=chatContainer();
  const seguirConversacion=isNearBottom(c);
  try{
    if(!currentChatId){await nuevoChat();}
    const historial=historialParaApi();
    document.getElementById('chatWelcome')?.remove();
    try{document.getElementById('chat')?.classList.remove('history-empty')}catch(_){}

    // Lo visible es exactamente lo que escribió/adjuntó el usuario. Los prompts
    // operativos del backend nunca se pintan en el chat.
    agregarMensajeUsuarioConAdjuntos(t,archivos);

    // Snapshot inmutable de este envío. El composer se limpia INMEDIATAMENTE;
    // la request conserva sus File objects en memoria aunque ya no estén visibles.
    limpiarComposerDespuesDeEnvio(i,textoOriginal,editSeqAlEnviar);
    if(archivos.length)quitarAdjuntosEnviados(archivos);
    const composerSeqLimpio=composerEditSeq;
    const adjuntosSeqLimpios=attachmentEditSeq;

    if(seguirConversacion)scrollToBottom(false);
    const thinking=add('assistant','<span class="typing"><i></i><i></i><i></i></span>',true);
    if(seguirConversacion)scrollToMessageStart(thinking,false);
    try{
      const fd=new FormData();
      fd.append('mensaje',t);
      fd.append('historial',JSON.stringify(historial));
      fd.append('chat_id',String(currentChatId||''));
      archivos.forEach(a=>fd.append('archivo',a,a.name));
      const r=await fetch('/api/chat',{method:'POST',body:fd,credentials:'same-origin'});
      const d=await leerJsonSeguro(r);
      if(!r.ok||d.ok===false)throw Error(d.error||'No se pudo consultar el asistente.');
      currentChatId=d.chat_id||currentChatId;

      const visible=textoVisibleAsistente(d.respuesta||'No recibí una respuesta.',d);
      if(visible){thinking.querySelector('.bubble').innerHTML=fmt(visible)}else{thinking.remove()}
      if(d.propuesta_excel)mostrarPropuestaExcel(d.propuesta_excel);
      if(d.propuesta_metadato)mostrarPropuestaMetadato(d.propuesta_metadato);
      if(d.tabulado_flota)mostrarTabuladoFlota(d.tabulado_flota);
      if(d.cedula_detectada)mostrarCedulaDetectada(d.cedula_detectada,d.cedula_advertencias,{messageId:d.assistant_message_id,altaPrefill:d.borrador_alta_desde_cedula,altaRevisiones:d.alta_revisiones,altaYaPreparada:!!d.campos_guardar_alta_asegurado});
      if(d.documento_personal_detectado)mostrarDocumentoPersonalDetectado(d.documento_personal_detectado,d.documento_personal_advertencias);
      if(d.actualizacion_alta_asegurado){
        const actualizado=actualizarFormularioAltaActivo(d.actualizacion_alta_asegurado);
        if(!actualizado)mostrarOpcionesAltaAsegurado(d.tabulado_alta_asegurado,d.actualizacion_alta_asegurado,{messageId:d.assistant_message_id,revisiones:d.alta_revisiones,origen:d.alta_origen});
      }else if(d.tabulado_alta_asegurado||d.campos_guardar_alta_asegurado){
        mostrarOpcionesAltaAsegurado(d.tabulado_alta_asegurado,d.campos_guardar_alta_asegurado,{messageId:d.assistant_message_id,revisiones:d.alta_revisiones,origen:d.alta_origen});
      }
      if(d.texto_envios_ya&&!d.actualizacion_alta_asegurado&&!d.campos_guardar_alta_asegurado)mostrarTextoEnviosYa(d.texto_envios_ya);
      if(d.ficha_operativa_asegurado)mostrarFichaOperativaAsegurado(d.ficha_operativa_asegurado);
      if(d.envios_chat)mostrarEnviosChat(d.envios_chat,{messageId:d.assistant_message_id});
      if(d.abrir_cotizador_atm)abrirCotizadorATM(d.atm_cotizacion_detectada||null);
      try{await cargarListaChats()}catch(_){}
    }catch(e){
      // Si el usuario no empezó un borrador nuevo mientras esperaba, devolvemos
      // el snapshot al editor. Nunca obligamos a volver a seleccionar archivos.
      if(composerEditSeq===composerSeqLimpio && attachmentEditSeq===adjuntosSeqLimpios && !i.value.trim() && !archivosAdjuntosChat.length){
        if(textoOriginal){i.value=textoOriginal;composerEditSeq++;size()}
        if(archivos.length){
          archivosAdjuntosChat=[...archivos];
          attachmentEditSeq++;
          _sincronizarInputAdjuntos(pdf);
          mostrarAdjuntos(archivosAdjuntosChat);
        }
      }
      const mensaje=e?.message||'No se pudo procesar la consulta. Intentá nuevamente.';
      if(thinking.isConnected)thinking.querySelector('.bubble').innerHTML='<p>'+esc(mensaje)+'</p>';
    }
    if(seguirConversacion && thinking.isConnected)scrollToMessageStart(thinking,true);
  }finally{
    enviandoMensaje=false;
    if(b)b.disabled=false;
    i.focus();
  }
}

async function initChat(){
  const i=document.getElementById('mensaje');
  if(!i)return;
  chatInitInProgress=true;
  chatInitReadyPromise=new Promise(resolve=>{resolveChatInitReady=resolve});
  try{
  inicializarVisualChatWhatsApp();
  inicializarLightboxChat();
  inicializarMenuAccionesChat();
  inicializarDictadoChat();
  inicializarCotizadorATM();
  limpiarMetadataVisualMensajes(document.getElementById('chat'));
  wireWelcomeWorkflows(document);try{const h=document.getElementById('chat');if(h&&h.querySelector('#chatWelcome')){h.classList.add('history-empty');h.scrollTop=0}}catch(_){};

  i.oninput=()=>{
    if(dictationActive&&!dictationProgrammaticUpdate){try{dictationRecognition?.stop()}catch(_){}}
    composerEditSeq++;
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
      if(dictationActive){e.preventDefault();finalizarDictado({cancelar:true});return}
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
    const files=Array.from(pdf.files||[]);
    if(files.length)validarYAdjuntarArchivos(files,pdf,{reemplazar:false});
  });

  // Permite pegar una foto (por ejemplo copiada desde WhatsApp Web) con Ctrl+V.
  // El texto pegado conserva su comportamiento normal: sólo interceptamos items de imagen.
  i.addEventListener('paste',e=>{
    if(enviandoMensaje)return;
    const items=Array.from(e.clipboardData?.items||[])
      .filter(item=>String(item.type||'').toLowerCase().startsWith('image/'));
    if(!items.length||!pdf)return;
    const ahora=Date.now();
    const files=items.map((item,idx)=>{
      const blob=item.getAsFile();
      if(!blob)return null;
      const mime=String(blob.type||'image/png').toLowerCase();
      const ext=mime.includes('jpeg')?'jpg':mime.includes('webp')?'webp':'png';
      return new File([blob],`imagen-pegada-${ahora}-${idx+1}.${ext}`,{type:mime,lastModified:ahora+idx});
    }).filter(Boolean);
    if(files.length&&validarYAdjuntarArchivos(files,pdf,{reemplazar:false})){
      e.preventDefault();
      if(window.showToast)showToast(files.length>1?`${files.length} imágenes adjuntadas.`:'Imagen adjuntada desde el portapapeles.','success');
    }
  });

  wireDragAndDropArchivo();

  document.addEventListener('click',e=>{
    const menu=document.getElementById('chatCommandMenu');
    if(menu&&!menu.hidden&&!e.target.closest('#chatCommandMenu')&&e.target!==i){
      cerrarMenuComandos();
    }
  });


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
  }finally{
    chatInitInProgress=false;
    try{resolveChatInitReady?.()}catch(_){}
    resolveChatInitReady=null;
  }
}

async function buscar(q){const box=document.getElementById('resultadosBusqueda');if(!box)return;if(!q){box.innerHTML='<div class="empty"><b>Empezá a buscar</b><small>Los resultados aparecerán aquí.</small></div>';return}box.innerHTML='<div class="empty"><b>Buscando…</b></div>';try{const r=await fetch('/api/buscar?q='+encodeURIComponent(q)),d=await r.json();box.innerHTML=d.length?d.map(x=>`<div class="result"><b>${esc((x.extension||'FILE').replace('.','').toUpperCase())}</b><span><strong>${esc(x.nombre)}</strong><small>${esc(x.compania)} · ${esc(x.tamaño)} KB</small></span></div>`).join(''):'<div class="empty"><b>No encontramos coincidencias</b></div>'}catch{box.innerHTML='<div class="empty"><b>Error de búsqueda</b></div>'}}
const MAX_CHAT_ATTACHMENTS=5;
const MAX_CHAT_ATTACHMENTS_TOTAL_BYTES=40*1024*1024;
function _firmaArchivoFrontend(file){
  return [file?.name||'',Number(file?.size||0),Number(file?.lastModified||0),file?.type||''].join('|');
}
function mostrarAdjuntos(files){
  const box=document.getElementById('archivoAdjunto'),listaEl=document.getElementById('archivoListaAdjuntos');
  if(!box||!listaEl)return;
  const lista=Array.from(files||[]);
  listaEl.innerHTML='';
  lista.forEach((file,indice)=>{
    const item=document.createElement('div');
    item.className='file-attached-item wa-composer-attachment';
    item.dataset.attachmentIndex=String(indice);
    item.appendChild(crearVistaAdjuntoWhatsApp(file,indice,{compact:true}));
    const quitar=document.createElement('button');
    quitar.type='button';
    quitar.className='file-attached-remove';
    quitar.textContent='×';
    quitar.title=`Quitar ${file.name||'archivo'}`;
    quitar.setAttribute('aria-label',quitar.title);
    quitar.addEventListener('click',()=>quitarAdjunto(indice));
    item.appendChild(quitar);
    listaEl.appendChild(item);
  });
  box.hidden=!lista.length;
  document.querySelector('.composer')?.classList.toggle('has-attachments',!!lista.length);
}
function mostrarAdjunto(file){mostrarAdjuntos(file?[file]:[])}
function _sincronizarInputAdjuntos(input){
  if(!input)return;
  try{
    const dt=new DataTransfer();
    archivosAdjuntosChat.forEach(f=>dt.items.add(f));
    input.files=dt.files;
  }catch(_){}
}
function quitarAdjunto(indice){
  if(Number.isInteger(indice)&&indice>=0&&indice<archivosAdjuntosChat.length){
    archivosAdjuntosChat.splice(indice,1);
  }else{
    archivosAdjuntosChat=[];
  }
  attachmentEditSeq++;
  const input=document.getElementById('archivoInput');
  _sincronizarInputAdjuntos(input);
  mostrarAdjuntos(archivosAdjuntosChat);
}
function quitarAdjuntosEnviados(enviados,seqAlEnviar){
  const enviadosSet=new Set(Array.from(enviados||[]));
  if(!enviadosSet.size)return;
  const antes=archivosAdjuntosChat.length;
  archivosAdjuntosChat=archivosAdjuntosChat.filter(f=>!enviadosSet.has(f));
  if(archivosAdjuntosChat.length!==antes)attachmentEditSeq++;
  const input=document.getElementById('archivoInput');
  _sincronizarInputAdjuntos(input);
  mostrarAdjuntos(archivosAdjuntosChat);
}
function limpiarComposerDespuesDeEnvio(input,valorEnviado,seqAlEnviar){
  if(!input)return;
  if(composerEditSeq===seqAlEnviar && input.value===valorEnviado){
    input.value='';
    composerEditSeq++;
    size();
  }else{
    size();
  }
}
function _archivoAdjuntoValido(file){
  if(!file)return {ok:false,error:'Archivo inválido.'};
  const ext=(file.name.split('.').pop()||'').toLowerCase();
  const limites={pdf:20,txt:2,csv:20,xlsx:20,xlsm:20,png:15,jpg:15,jpeg:15,webp:15};
  const limite=limites[ext];
  if(!limite)return {ok:false,error:'Podés adjuntar Excel (XLSX/XLSM), PDF, TXT, CSV, PNG, JPG, JPEG o WEBP.'};
  if(file.size>limite*1024*1024)return {ok:false,error:`El archivo supera el límite de ${limite} MB.`};
  return {ok:true};
}
function validarYAdjuntarArchivos(files,inputEl,{reemplazar=false}={}){
  const input=inputEl||document.getElementById('archivoInput');
  if(!input)return false;
  const nuevos=Array.from(files||[]).filter(Boolean);
  if(!nuevos.length)return false;
  const base=reemplazar?[]:[...archivosAdjuntosChat];
  const firmas=new Set(base.map(_firmaArchivoFrontend));
  const unidos=[...base];
  let duplicados=0;
  for(const file of nuevos){
    const firma=_firmaArchivoFrontend(file);
    if(firmas.has(firma)){duplicados++;continue}
    firmas.add(firma);
    unidos.push(file);
  }
  if(unidos.length>MAX_CHAT_ATTACHMENTS){
    if(window.showToast)showToast(`Podés adjuntar hasta ${MAX_CHAT_ATTACHMENTS} archivos por mensaje.`,'warning');
    else alert(`Podés adjuntar hasta ${MAX_CHAT_ATTACHMENTS} archivos por mensaje.`);
    _sincronizarInputAdjuntos(input);return false;
  }
  let total=0;
  for(const file of unidos){
    const v=_archivoAdjuntoValido(file);
    if(!v.ok){
      if(window.showToast)showToast(v.error,'warning');else alert(v.error);
      _sincronizarInputAdjuntos(input);return false;
    }
    total+=Number(file.size||0);
  }
  if(total>MAX_CHAT_ATTACHMENTS_TOTAL_BYTES){
    const msg='El conjunto de adjuntos supera el límite de 40 MB por mensaje.';
    if(window.showToast)showToast(msg,'warning');else alert(msg);
    _sincronizarInputAdjuntos(input);return false;
  }
  archivosAdjuntosChat=unidos;
  attachmentEditSeq++;
  _sincronizarInputAdjuntos(input);
  mostrarAdjuntos(archivosAdjuntosChat);
  if(duplicados&&window.showToast)showToast('Ese archivo ya estaba adjuntado.','info');
  return true;
}
function validarYAdjuntarArchivo(file,inputEl){
  return validarYAdjuntarArchivos([file],inputEl,{reemplazar:false});
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
    const archivos=Array.from(e.dataTransfer.files||[]);
    if(archivos.length)validarYAdjuntarArchivos(archivos,pdf,{reemplazar:false});
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
    'Podés adjuntar Excel, PDF, TXT, CSV o imágenes desde el + o arrastrarlos directo sobre el chat.',
    'Si mandás un archivo sin escribir nada, igual lo proceso.',
    'Los PDFs, CSV y Excel admiten hasta 20 MB; las imágenes hasta 15 MB y los TXT hasta 2 MB.',
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
    'Cotización ATM está visible directamente en el menú +.',
    'En Cotización ATM podés calcular un precio manual o leer una captura del cotizador.',
    'Si adjuntás un Excel de contactos al chat, puedo prepararlo y generar el CSV final para Envíos Ya.',
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
