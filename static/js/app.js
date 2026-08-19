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
function fmt(s){let h=esc(s).replace(/(https?:\/\/[^\s<]+)/g,'<a href="$1" target="_blank" rel="noopener">$1</a>').replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>');return h.split(/\n+/).filter(Boolean).map(x=>/^[-•]\s/.test(x)?'<p class="bullet">• '+x.replace(/^[-•]\s/,'')+'</p>':'<p>'+x+'</p>').join('')||'<p></p>'}
function add(role,content,raw=false){const c=document.getElementById('chat');if(!c)return;const r=document.createElement('div');r.className='msg '+role;const x=document.createElement('div');x.className='bubble';x.innerHTML=raw?content:(role==='assistant'?fmt(content):esc(content));r.appendChild(x);c.appendChild(r);return r}
function scroll(){const c=document.getElementById('chat');if(c)requestAnimationFrame(()=>c.scrollTop=c.scrollHeight)}
function size(){const i=document.getElementById('mensaje');if(i){i.style.height='auto';i.style.height=Math.min(i.scrollHeight,110)+'px'}}
function usarSugerencia(t){const i=document.getElementById('mensaje');if(i){i.value=t;size();i.focus()}}
let currentChatId=null;
function historialParaApi(){const c=document.getElementById('chat');return c?[...c.querySelectorAll('.msg')].map(x=>({rol:x.classList.contains('user')?'user':'assistant',contenido:x.querySelector('.bubble')?.textContent?.trim()||''})).filter(x=>x.contenido).slice(-10):[]}
async function cargarListaChats(){const box=document.getElementById('chatList');if(!box)return;const r=await fetch('/api/chats',{credentials:'same-origin'});const d=await leerJsonSeguro(r);if(!r.ok||d.ok===false)throw new Error(d.error||'No se pudo cargar el historial.');box.innerHTML='';if(!d.chats.length){box.innerHTML='<div class="chat-empty">No hay conversaciones guardadas.</div>';return}d.chats.forEach(x=>{const row=document.createElement('div');row.className='chat-item-row';const b=document.createElement('button');b.type='button';b.className='chat-item '+(x.id===currentChatId?'active':'');b.innerHTML='<span>'+esc(x.titulo)+'</span><small>'+new Date(x.actualizado_en.replace(' ','T')+'Z').toLocaleDateString('es-AR')+'</small>';b.onclick=()=>abrirChat(x.id);const del=document.createElement('button');del.type='button';del.className='chat-delete';del.title='Eliminar conversación';del.setAttribute('aria-label','Eliminar conversación: '+x.titulo);del.textContent='🗑';del.onclick=e=>{e.stopPropagation();eliminarChat(x.id)};row.appendChild(b);row.appendChild(del);box.appendChild(row)})}
async function abrirChat(id){const r=await fetch('/api/chats/'+id,{credentials:'same-origin'});const d=await leerJsonSeguro(r);if(!r.ok||!d.ok)throw new Error(d.error||'No se pudo abrir la conversación.');currentChatId=id;const c=document.getElementById('chat');c.innerHTML='';if(!d.mensajes.length)c.innerHTML='<div id="chatWelcome" class="welcome"><strong>✦</strong><h2>¿Qué necesitás resolver?</h2><p>Preguntame por una póliza, un procedimiento, una compañía o cualquier dato disponible.</p></div>';else d.mensajes.forEach(m=>add(m.rol,m.contenido));await cargarListaChats();scroll()}
async function nuevoChat(){const r=await fetch('/api/chats',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({titulo:'Nueva conversación'}),credentials:'same-origin'});const d=await leerJsonSeguro(r);if(d.ok)await abrirChat(d.id)}
async function eliminarChat(id){const r=await fetch('/api/chats/'+id,{method:'DELETE'});if(!r.ok)return;if(currentChatId===id){currentChatId=null;const c=document.getElementById('chat');if(c)c.innerHTML='<div id="chatWelcome" class="welcome"><strong>✦</strong><h2>¿Qué necesitás resolver?</h2><p>Podés iniciar una nueva conversación cuando quieras.</p></div>'}await cargarListaChats()}
async function borrarChatActual(){if(!currentChatId){return}await eliminarChat(currentChatId)}
let enviandoMensaje=false;
function mostrarPropuestaExcel(propuesta){
  const c=document.getElementById('chat');
  if(!c||!propuesta||typeof propuesta!=='object')return;
  const campos=Object.entries(propuesta).filter(([k,v])=>String(k).trim()&&String(v).trim());
  if(!campos.length)return;
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
  ayuda.textContent='Revisá y corregí los datos antes de guardar.';
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
    input.value=String(valor);
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
  const estado=document.createElement('span');
  estado.className='excel-proposal-status';
  acciones.appendChild(guardar);
  acciones.appendChild(estado);
  b.appendChild(acciones);
  r.appendChild(b);
  c.appendChild(r);
  guardar.addEventListener('click',async()=>{
    if(guardar.disabled)return;
    const valores={};
    form.querySelectorAll('input[data-campo]').forEach(input=>{valores[input.dataset.campo]=input.value.trim()});
    if(!Object.values(valores).some(Boolean)){estado.textContent='Completá al menos un campo.';return}
    guardar.disabled=true;
    estado.textContent='Guardando…';
    try{
      const resp=await fetch('/api/excel/agregar-fila',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({campos:valores})});
      const d=await leerJsonSeguro(resp);
      if(!resp.ok||d.ok===false)throw Error(d.error||'No se pudo guardar el registro.');
      estado.textContent='Guardado correctamente en Excel.';
      estado.classList.add('success');
      guardar.textContent='Guardado';
    }catch(e){
      estado.textContent=e?.message||'No se pudo guardar.';
      guardar.disabled=false;
    }
  });
  scroll();
}
async function enviarMensaje(){
  const i=document.getElementById('mensaje'),b=document.querySelector('.send'),pdf=document.getElementById('pdfInput');
  if(!i||enviandoMensaje)return;
  const t=i.value.trim(),archivo=pdf?.files?.[0]||null;
  if(!t&&!archivo)return;
  enviandoMensaje=true;
  if(b)b.disabled=true;
  try{
    if(!currentChatId){await nuevoChat();}
    const historial=historialParaApi();
    document.getElementById('chatWelcome')?.remove();
    add('user',(archivo?'📎 '+archivo.name+'\n':'')+(t||'Analizá este PDF.'));
    i.value='';size();scroll();
    const thinking=add('assistant','<span class="typing"><i></i><i></i><i></i></span>',true);
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
      thinking.querySelector('.bubble').innerHTML=fmt(d.respuesta||'No recibí una respuesta.');
      if(d.propuesta_excel)mostrarPropuestaExcel(d.propuesta_excel);
      if(pdf)pdf.value='';
      mostrarPdf(null);
      try{await cargarListaChats()}catch(_){}
    }catch(e){
      const mensaje=e?.message||'No se pudo procesar la consulta. Intentá nuevamente.';
      thinking.querySelector('.bubble').innerHTML='<p>'+esc(mensaje)+'</p>';
    }
    scroll();
  }finally{
    enviandoMensaje=false;
    if(b)b.disabled=false;
    i.focus();
  }
}
async function initChat(){const i=document.getElementById('mensaje');if(!i)return;i.oninput=size;i.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();enviarMensaje()}};const pdf=document.getElementById('pdfInput');if(pdf)pdf.addEventListener('change',()=>{const file=pdf.files?.[0];if(file){if(!file.name.toLowerCase().endsWith('.pdf')){alert('Solo podés adjuntar archivos PDF.');pdf.value='';return}if(file.size>20*1024*1024){alert('El PDF supera el límite de 20 MB.');pdf.value='';return}mostrarPdf(file)}});const r=await fetch('/api/chats',{credentials:'same-origin'}),d=await leerJsonSeguro(r);if(!r.ok||!d.ok)throw new Error(d.error||'No se pudo cargar el historial.');if(window.FORZAR_CHAT_NUEVO||!d.chats.length){const x=await fetch('/api/chats',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({titulo:'Nueva conversación'}),credentials:'same-origin'}),j=await leerJsonSeguro(x);if(j.ok)await abrirChat(j.id);window.FORZAR_CHAT_NUEVO=false}else{await abrirChat(d.chats[0].id)}size();scroll()}
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
