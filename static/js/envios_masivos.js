(()=>{
  const qs=s=>document.querySelector(s);
  const esc=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const input=qs('#enviosFiles'), drop=qs('#enviosDrop'), selected=qs('#enviosSelected');
  const processBtn=qs('#enviosProcess'), clearBtn=qs('#enviosClear');
  const progress=qs('#enviosProgress'), bar=qs('#enviosProgressBar'), progressText=qs('#enviosProgressText');
  const mappingBox=qs('#enviosMapping'), mappingRows=qs('#enviosMappingRows'), applyMapping=qs('#enviosApplyMapping');
  let files=[]; let preview=[]; let pendingMappings=[];

  const validExt=f=>/\.(xlsx|xlsm|csv)$/i.test(f?.name||'');
  const fmtSize=n=>n<1048576?`${Math.max(1,Math.round(n/1024))} KB`:`${(n/1048576).toFixed(1)} MB`;
  const dedupeMode=()=>document.querySelector('input[name="enviosDedupe"]:checked')?.value||'all';

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
  clearBtn?.addEventListener('click',()=>{files=[];preview=[];pendingMappings=[];renderFiles();qs('#enviosResults').hidden=true;mappingBox.hidden=true;progress.hidden=true;});

  function stat(value,label,kind=''){
    return `<div class="envios-stat ${kind}"><b>${Number(value||0).toLocaleString('es-AR')}</b><span>${label}</span></div>`;
  }
  function renderSources(xs){
    qs('#enviosSources').innerHTML=(xs||[]).map(x=>{
      const cols=Object.entries(x.columnas||{}).map(([n,c])=>`<span><b>Col. ${esc(n)}</b> ${esc(c.replaceAll('_',' '))}</span>`).join('');
      return `<article class="envios-source-row"><div class="envios-source-main"><b>${esc(x.nombre)}</b><small>${Number(x.filas||0).toLocaleString('es-AR')} filas · ${x.encabezados?'con encabezados':'sin encabezados'}</small></div><div class="envios-column-map">${cols||'<span>Mapeo manual.</span>'}</div></article>`;
    }).join('')||'<div class="envios-empty">Sin archivos procesados.</div>';
  }
  function renderPreview(filter='TODOS'){
    document.querySelectorAll('[data-envios-filter]').forEach(b=>b.classList.toggle('active',b.dataset.enviosFilter===filter));
    const xs=preview.filter(x=>filter==='TODOS'||x.estado===filter);
    qs('#enviosPreview').innerHTML=xs.length?xs.map(x=>`<tr class="${x.estado==='REVISAR'?'review':''}"><td><span class="envios-status ${x.estado.toLowerCase()}" title="${esc(x.motivo||'')}">${x.estado==='VALIDO'?'Listo':'Revisar'}</span></td><td>${esc(x.apellido)}</td><td>${esc(x.nombre)}</td><td class="phone">${esc(x.celular)}</td><td>${esc(x.fecha)}</td><td class="source">${esc(x.fuente)}</td></tr>`).join(''):'<tr><td colspan="6" class="envios-no-rows">No hay registros para este filtro.</td></tr>';
  }
  document.querySelectorAll('[data-envios-filter]').forEach(b=>b.addEventListener('click',()=>renderPreview(b.dataset.enviosFilter)));

  function selectOptions(cols, selectedIdx){
    return `<option value="">— Elegir —</option>`+(cols||[]).map(c=>`<option value="${c.index}" ${String(c.index)===String(selectedIdx)?'selected':''}>${esc(c.label)}</option>`).join('');
  }
  function renderMapping(requests){
    pendingMappings=requests||[];
    mappingRows.innerHTML=pendingMappings.map(m=>{
      const d=m.detectado||{};
      const opts=idx=>selectOptions(m.columnas,idx);
      return `<article class="envios-source-row envios-map-row" data-map-file="${m.file_index}"><div class="envios-source-main"><b>${esc(m.nombre)}</b><small>Elegí columnas separadas o una sola columna de nombre completo.</small></div><div class="envios-manual-grid"><label>Apellido<select data-field="apellido">${opts(d.apellido)}</select></label><label>Nombre<select data-field="nombre">${opts(d.nombre)}</select></label><label>Nombre completo<select data-field="nombre_completo">${opts(d.nombre_completo)}</select></label><label>Celular<select data-field="celular">${opts(d.celular)}</select></label></div></article>`;
    }).join('');
    mappingBox.hidden=false;
    mappingBox.scrollIntoView({behavior:'smooth',block:'start'});
  }
  function collectMapping(){
    const out={};
    mappingRows.querySelectorAll('[data-map-file]').forEach(row=>{
      const one={};
      row.querySelectorAll('select[data-field]').forEach(s=>{if(s.value!=='')one[s.dataset.field]=Number(s.value);});
      out[row.dataset.mapFile]=one;
    });
    return out;
  }

  async function process(manualMapping={}){
    if(!files.length)return;
    processBtn.disabled=true; clearBtn.disabled=true; if(applyMapping)applyMapping.disabled=true;
    progress.hidden=false; bar.style.width='18%';progressText.textContent='Leyendo la planilla y detectando columnas…';
    const fd=new FormData(); files.forEach(f=>fd.append('bases',f,f.name));
    fd.append('manual_mapping',JSON.stringify(manualMapping||{}));
    fd.append('dedupe_mode',dedupeMode());
    try{
      const r=await fetch('/api/envios-masivos/procesar',{method:'POST',body:fd});
      bar.style.width='70%'; progressText.textContent='Normalizando contactos y preparando el CSV…';
      const ct=r.headers.get('content-type')||'';
      const d=ct.includes('application/json')?await r.json():{ok:false,error:'El servidor devolvió una respuesta inesperada.'};
      if(!r.ok||!d.ok)throw new Error(d.error||'No pude procesar la planilla.');
      if(d.requiere_mapeo){
        progress.hidden=true;
        renderMapping(d.mapeos||[]);
        return;
      }
      mappingBox.hidden=true;
      const s=d.resumen||{}; preview=d.preview||[];
      qs('#enviosResultSummary').textContent=`${Number(s.exportables||0).toLocaleString('es-AR')} listos para exportar · fecha ${d.fecha||''}`;
      qs('#enviosStats').innerHTML=stat(s.contactos_detectados,'Contactos encontrados')+stat(s.exportables,'Listos para exportar','ok')+stat(s.revisar,'Con datos incompletos','warn')+stat(s.duplicados,'Posibles duplicados','dup');
      qs('#enviosDownload').href='/api/envios-masivos/descargar/'+encodeURIComponent(d.token);
      renderSources(d.archivos||[]);renderPreview('TODOS');
      qs('#enviosResults').hidden=false;
      bar.style.width='100%';progressText.textContent='Listo. El CSV ya puede importarse directamente en Envíos Ya.';
      qs('#enviosResults').scrollIntoView({behavior:'smooth',block:'start'});
    }catch(e){
      bar.style.width='100%';progressText.textContent=e.message||'No pude procesar la planilla.';
    }finally{processBtn.disabled=!files.length;clearBtn.disabled=false;if(applyMapping)applyMapping.disabled=false;}
  }

  processBtn?.addEventListener('click',()=>process({}));
  applyMapping?.addEventListener('click',()=>process(collectMapping()));
  renderFiles();
})();
