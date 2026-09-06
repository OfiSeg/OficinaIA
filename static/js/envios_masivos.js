(()=>{
  const qs=s=>document.querySelector(s);
  const esc=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const input=qs('#enviosFiles'), drop=qs('#enviosDrop'), selected=qs('#enviosSelected');
  const processBtn=qs('#enviosProcess'), clearBtn=qs('#enviosClear');
  const progress=qs('#enviosProgress'), bar=qs('#enviosProgressBar'), progressText=qs('#enviosProgressText');
  let files=[]; let preview=[];

  const validExt=f=>/\.(xlsx|xlsm|csv)$/i.test(f?.name||'');
  const fmtSize=n=>n<1048576?`${Math.max(1,Math.round(n/1024))} KB`:`${(n/1048576).toFixed(1)} MB`;

  function renderFiles(){
    processBtn.disabled=!files.length;
    if(!files.length){selected.innerHTML='<div class="envios-empty">Todavía no seleccionaste archivos.</div>';return;}
    selected.innerHTML=files.map((f,i)=>`<div class="envios-file-row"><span class="envios-file-icon">${f.name.toLowerCase().endsWith('.csv')?'CSV':'XLS'}</span><div><b>${esc(f.name)}</b><small>${fmtSize(f.size)}</small></div><button type="button" data-remove="${i}" aria-label="Quitar ${esc(f.name)}">×</button></div>`).join('');
    selected.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{files.splice(Number(b.dataset.remove),1);renderFiles();});
  }

  function addFiles(list){
    const incoming=[...list].filter(validExt);
    for(const f of incoming){
      if(files.length>=12)break;
      if(!files.some(x=>x.name===f.name&&x.size===f.size))files.push(f);
    }
    renderFiles();
  }
  input?.addEventListener('change',()=>{addFiles(input.files||[]);input.value='';});
  ['dragenter','dragover'].forEach(ev=>drop?.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('drag')}));
  ['dragleave','drop'].forEach(ev=>drop?.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('drag')}));
  drop?.addEventListener('drop',e=>addFiles(e.dataTransfer.files||[]));
  clearBtn?.addEventListener('click',()=>{files=[];preview=[];renderFiles();qs('#enviosResults').hidden=true;progress.hidden=true;});

  function stat(value,label,kind=''){
    return `<div class="envios-stat ${kind}"><b>${Number(value||0).toLocaleString('es-AR')}</b><span>${label}</span></div>`;
  }
  function renderSources(xs){
    qs('#enviosSources').innerHTML=(xs||[]).map(x=>{
      const cols=Object.entries(x.columnas||{}).map(([n,c])=>`<span><b>Col. ${esc(n)}</b> ${esc(c.replaceAll('_',' '))}</span>`).join('');
      return `<article class="envios-source-row"><div class="envios-source-main"><b>${esc(x.nombre)}</b><small>${Number(x.filas||0).toLocaleString('es-AR')} filas · ${x.encabezados?'con encabezados':'sin encabezados'}${x.compania_detectada?` · fuente: ${esc(x.compania_detectada)}`:''}</small></div><div class="envios-column-map">${cols||'<span>No se pudieron identificar columnas.</span>'}</div></article>`;
    }).join('')||'<div class="envios-empty">Sin archivos procesados.</div>';
  }
  function renderPreview(filter='TODOS'){
    document.querySelectorAll('[data-envios-filter]').forEach(b=>b.classList.toggle('active',b.dataset.enviosFilter===filter));
    const xs=preview.filter(x=>filter==='TODOS'||x.estado===filter);
    qs('#enviosPreview').innerHTML=xs.length?xs.map(x=>`<tr class="${x.estado==='REVISAR'?'review':''}"><td><span class="envios-status ${x.estado.toLowerCase()}" title="${esc(x.motivo||'')}">${x.estado==='VALIDO'?'Listo':'Revisar'}</span></td><td>${esc(x.apellido)}</td><td>${esc(x.nombre)}</td><td class="phone">${esc(x.celular)}</td><td>${esc(x.email)}</td><td>${esc(x.localidad)}</td><td>${esc(x.cp)}</td><td>${esc(x.compania)}</td><td>${esc(x.patente)}</td><td>${esc(x.tipo)}</td><td class="source">${esc(x.fuente)}</td></tr>`).join(''):'<tr><td colspan="11" class="envios-no-rows">No hay registros para este filtro.</td></tr>';
  }
  document.querySelectorAll('[data-envios-filter]').forEach(b=>b.addEventListener('click',()=>renderPreview(b.dataset.enviosFilter)));

  processBtn?.addEventListener('click',async()=>{
    if(!files.length)return;
    processBtn.disabled=true; clearBtn.disabled=true; progress.hidden=false; bar.style.width='16%';progressText.textContent='Leyendo y entendiendo las bases…';
    const fd=new FormData(); files.forEach(f=>fd.append('bases',f,f.name)); fd.append('fecha_modo',qs('#enviosFechaVencimiento')?.checked?'vencimiento':'conservar'); fd.append('usar_compania_fuente',qs('#enviosCompaniaFuente')?.checked?'1':'0');
    try{
      const r=await fetch('/api/envios-masivos/procesar',{method:'POST',body:fd});
      bar.style.width='76%'; progressText.textContent='Limpiando teléfonos y eliminando duplicados…';
      const ct=r.headers.get('content-type')||'';
      const d=ct.includes('application/json')?await r.json():{ok:false,error:'El servidor devolvió una respuesta inesperada.'};
      if(!r.ok||!d.ok)throw new Error(d.error||'No pude procesar las bases.');
      const s=d.resumen||{}; preview=d.preview||[];
      qs('#enviosResultSummary').textContent=`${Number(s.exportables||0).toLocaleString('es-AR')} contactos listos para cargar en EnvíosYA`;
      qs('#enviosStats').innerHTML=stat(s.contactos_detectados,'Contactos detectados')+stat(s.exportables,'Contactos EnvíosYA','ok')+stat(s.notificaciones_aptas,'Notificaciones listas','ok')+stat(s.con_email,'Con email','dup')+stat(s.duplicados,'Duplicados eliminados','dup')+stat(s.revisar,'Para revisar','warn')+stat(s.caracteres_reparados,'Ñ reparadas','dup');
      qs('#enviosDownload').href='/api/envios-masivos/descargar/'+encodeURIComponent(d.token); qs('#enviosNotifDownload').href='/api/envios-masivos/descargar-notificaciones/'+encodeURIComponent(d.token); qs('#enviosMasterDownload').href='/api/envios-masivos/descargar-maestro/'+encodeURIComponent(d.token); const nd=qs('#enviosNotifDownload'); if(nd){nd.classList.toggle('disabled',!d.notificaciones_disponibles); nd.setAttribute('aria-disabled',d.notificaciones_disponibles?'false':'true'); if(!d.notificaciones_disponibles)nd.removeAttribute('href');} const nt=qs('#enviosNotifText'); if(nt){nt.textContent=d.notificaciones_disponibles?'Formato exacto de “Importar notificaciones”: apellido, nombre, celular, fecha, XXX, XXX, XXX, patente, XXX, póliza. El Email no forma parte de ese CSV.':'No hay registros con apellido + nombre + celular válido + fecha de vencimiento. Si la fecha genérica de la base es un vencimiento, seleccioná esa opción y procesá nuevamente.';} const qn=qs('#enviosQualityNote'); if(qn){const rep=Number(s.caracteres_reparados||0), bad=Number(s.texto_danado||0); if(rep||bad){qn.hidden=false; qn.innerHTML=`${rep?`<b>${rep.toLocaleString('es-AR')} registros reparados:</b> el archivo de origen usaba <code>#</code> donde correspondía <code>Ñ</code>. `:''}${bad?`<b>${bad.toLocaleString('es-AR')} registros</b> todavía contienen algún carácter ilegible del archivo original y quedan identificados para revisión en la base completa.`:''}`;}else{qn.hidden=true;qn.textContent='';}}
      renderSources(d.archivos||[]);renderPreview('TODOS');
      qs('#enviosResults').hidden=false;
      bar.style.width='100%';progressText.textContent='Listo. Contactos, notificaciones y base completa ya están preparados.';
      qs('#enviosResults').scrollIntoView({behavior:'smooth',block:'start'});
    }catch(e){
      bar.style.width='100%';progressText.textContent=e.message||'No pude procesar las bases.';
    }finally{processBtn.disabled=!files.length;clearBtn.disabled=false;}
  });

  renderFiles();
})();
