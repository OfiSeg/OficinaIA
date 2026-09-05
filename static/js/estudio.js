(() => {
  const qs = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const labels = {TOMAR:'Tomar',REVISAR:'Revisar',NO_TOMAR:'No tomar',INCOMPLETO:'Incompleto'};
  let files = [], loteId = null, casos = [];

  document.querySelectorAll('[data-estudio-tab]').forEach(btn => btn.onclick = () => {
    document.querySelectorAll('[data-estudio-tab]').forEach(x => x.classList.toggle('active', x===btn));
    document.querySelectorAll('[data-estudio-panel]').forEach(x => x.classList.toggle('active', x.dataset.estudioPanel===btn.dataset.estudioTab));
    if(btn.dataset.estudioTab==='ejemplos') loadExamples();
    if(btn.dataset.estudioTab==='historial') loadHistory();
  });

  const input=qs('#estudioFiles'), drop=qs('#estudioDrop'), start=qs('#estudioStart'), clear=qs('#estudioClear');
  const setFiles = list => {
    files=[...list].filter(f => f.type==='application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
    qs('#estudioFileSummary').textContent = files.length ? `${files.length} PDF${files.length===1?'':'s'} · ${(files.reduce((a,f)=>a+f.size,0)/1048576).toFixed(1)} MB` : 'Todavía no seleccionaste archivos.';
    start.disabled=!files.length;
  };
  input?.addEventListener('change',()=>setFiles(input.files));
  ['dragenter','dragover'].forEach(ev=>drop?.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('drag')}));
  ['dragleave','drop'].forEach(ev=>drop?.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('drag')}));
  drop?.addEventListener('drop',e=>setFiles(e.dataTransfer.files));
  clear?.addEventListener('click',()=>{files=[]; if(input)input.value=''; setFiles([]);});

  start?.addEventListener('click', async () => {
    if(!files.length) return;
    start.disabled=true; clear.disabled=true; casos=[];
    qs('#estudioResults').hidden=true; qs('#estudioProgress').hidden=false;
    const loteResp=await fetch('/api/estudio/lotes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({titulo:`Análisis ${new Date().toLocaleString('es-AR')}`})});
    const lote=await loteResp.json();
    if(!loteResp.ok){alert(lote.error||'No se pudo crear el lote.');start.disabled=false;clear.disabled=false;return;}
    loteId=lote.id;
    for(let i=0;i<files.length;i++){
      const f=files[i]; const pct=Math.round(i/files.length*100);
      qs('#estudioProgressBar').style.width=pct+'%'; qs('#estudioProgressText').textContent=`Analizando ${i+1} de ${files.length}: ${f.name}`;
      const fd=new FormData(); fd.append('lote_id',loteId); fd.append('pdf',f);
      try{
        const r=await fetch('/api/estudio/analizar',{method:'POST',body:fd}); const d=await r.json();
        if(r.ok && d.ok) casos.push(d.caso); else casos.push({id:'error-'+i,nombre_archivo:f.name,clasificacion:'INCOMPLETO',titulo:f.name,resumen:d.error||'No se pudo analizar.',motivo:d.error||'Error de análisis.',confianza:0,datos:{}});
      }catch(e){casos.push({id:'error-'+i,nombre_archivo:f.name,clasificacion:'INCOMPLETO',titulo:f.name,resumen:'No se pudo analizar por un error de conexión.',motivo:'Error de conexión.',confianza:0,datos:{}});}
    }
    qs('#estudioProgressBar').style.width='100%'; qs('#estudioProgressText').textContent=`Listo: ${files.length} PDF${files.length===1?'':'s'} procesados.`;
    renderResults(); start.disabled=false; clear.disabled=false;
  });

  function renderResults(){
    const box=qs('#estudioResults'); if(!box)return; box.hidden=false;
    const counts={TOMAR:0,REVISAR:0,NO_TOMAR:0,INCOMPLETO:0}; casos.forEach(c=>counts[c.clasificacion]=(counts[c.clasificacion]||0)+1);
    qs('#estudioResultSummary').textContent=`${casos.length} casos procesados`;
    qs('#estudioStats').innerHTML=Object.entries(counts).map(([k,v])=>`<button type="button" class="estudio-stat ${k.toLowerCase()}" data-download="${k}" ${!v?'disabled':''}><b>${v}</b><span>${labels[k]}</span><small>Descargar</small></button>`).join('');
    qs('#estudioCases').innerHTML=casos.map((c,i)=>renderCase(c)).join('');
    qs('#estudioStats').querySelectorAll('[data-download]').forEach(b=>b.onclick=()=>download(b.dataset.download));
    qs('#estudioCases').querySelectorAll('select[data-case-id]').forEach(sel=>sel.onchange=async()=>{
      const r=await fetch('/api/estudio/casos/'+sel.dataset.caseId,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({clasificacion:sel.value})}); const d=await r.json();
      if(r.ok&&d.ok){const idx=casos.findIndex(x=>x.id===d.caso.id);if(idx>=0)casos[idx]=d.caso;renderResults();}
    });
    box.scrollIntoView({behavior:'smooth',block:'start'});
  }

  const hasValue=v=>Array.isArray(v)?v.some(Boolean):(v&&typeof v==='object'?Object.values(v).some(Boolean):String(v??'').trim()!=='');
  const itemList=v=>{
    const xs=Array.isArray(v)?v.filter(Boolean):(hasValue(v)?[v]:[]);
    return xs.length?`<ul class="case-list">${xs.map(x=>`<li>${esc(typeof x==='object'?formatContact(x):x)}</li>`).join('')}</ul>`:'<span class="case-empty">No surge del documento.</span>';
  };
  const field=(label,value)=>hasValue(value)?`<div class="case-data"><span>${esc(label)}</span><b>${esc(value)}</b></div>`:'';
  const section=(title,body,cls='')=>body?`<section class="case-section ${cls}"><h4>${title}</h4>${body}</section>`:'';
  function renderCase(c){
    const d=c.datos||{}, contacto=d.contacto||{};
    const contactFields=contacto&&typeof contacto==='object'
      ? Object.entries(contacto).filter(([,v])=>hasValue(v)).map(([k,v])=>field(prettyLabel(k),smartText(v))).join('')
      : field('Contacto',smartText(contacto));
    const identity=[field('Fecha del hecho',d.fecha_hecho),field('Lugar',d.lugar),field('N.º de siniestro',d.numero_siniestro),field('N.º de póliza',d.numero_poliza)].join('');
    const refs=[field('Compañía',smartText(d.companias)),field('Vehículos / patentes',smartText(d.vehiculos))].join('');

    const keyItems=[];
    (Array.isArray(d.lesiones)?d.lesiones:[]).filter(Boolean).forEach(x=>keyItems.push(`Lesiones: ${smartText(x)}`));
    (Array.isArray(d.danos)?d.danos:[]).filter(Boolean).forEach(x=>keyItems.push(`Daños: ${smartText(x)}`));
    (Array.isArray(d.documentacion_faltante)?d.documentacion_faltante:[]).filter(Boolean).slice(0,4).forEach(x=>keyItems.push(`Falta: ${smartText(x)}`));
    (Array.isArray(d.puntos_favorables)?d.puntos_favorables:[]).filter(Boolean).slice(0,3).forEach(x=>keyItems.push(`A favor del reclamo: ${smartText(x)}`));
    (Array.isArray(d.puntos_desfavorables)?d.puntos_desfavorables:[]).filter(Boolean).slice(0,3).forEach(x=>keyItems.push(`A revisar: ${smartText(x)}`));

    const compactReason=`<p>${esc(c.motivo||'No surge.')}</p>${hasValue(d.mecanica)?`<p class="case-mechanics-inline"><b>Mecánica:</b> ${esc(d.mecanica)}</p>`:''}`;
    const criterion=hasValue(d.criterio_juridico)?`<p>${esc(d.criterio_juridico)}</p>`:'';
    return `<article class="estudio-case">
      <div class="estudio-case-top"><span class="estudio-pill ${c.clasificacion.toLowerCase()}">${labels[c.clasificacion]}</span><b>${esc(c.titulo||c.nombre_archivo)}</b><span class="case-confidence" title="Confianza del análisis">${Number(c.confianza||0)}%</span></div>
      <p class="case-summary">${esc(c.resumen||'')}</p>
      <details class="case-analysis"><summary><span>Ver análisis</span><small>Datos y criterio esencial</small></summary>
        <div class="case-analysis-body compact-analysis">
          ${section('Lectura del caso',compactReason,'reason')}
          ${(contactFields||identity||refs)?`<section class="case-section"><h4>Datos útiles</h4><div class="case-data-grid">${contactFields}${identity}${refs}</div></section>`:''}
          ${keyItems.length?section('Puntos clave',itemList(keyItems),'key-section'):''}
          ${criterion?section('Criterio preliminar',criterion,'muted-section'):''}
        </div>
      </details>
      ${!String(c.id).startsWith('error-')?`<label class="estudio-reclass"><span>Clasificación</span><select data-case-id="${c.id}">${['TOMAR','REVISAR','NO_TOMAR','INCOMPLETO'].map(k=>`<option value="${k}" ${c.clasificacion===k?'selected':''}>${labels[k]}</option>`).join('')}</select></label>`:''}
    </article>`;
  }

  const prettyLabel=k=>String(k||'').replaceAll('_',' ').replace(/\b\w/g,m=>m.toUpperCase()).replace(/Dni/g,'DNI').replace(/Cuit/g,'CUIT').replace(/Email/g,'Email');
  const smartText=v=>{
    if(Array.isArray(v)) return v.filter(x=>hasValue(x)).map(smartText).join(' · ');
    if(v&&typeof v==='object') return Object.entries(v).filter(([,x])=>hasValue(x)).map(([k,x])=>`${prettyLabel(k)}: ${smartText(x)}`).join(' · ');
    return String(v??'').trim()||'No surge.';
  };
  const listText=v=>smartText(v);
  const formatContact=v=>smartText(v);
  function download(tipo=''){ if(!loteId)return; const q=tipo?`?clasificacion=${encodeURIComponent(tipo)}`:''; window.location.href=`/api/estudio/lotes/${loteId}/descargar${q}`; }
  qs('#estudioDownloadAll')?.addEventListener('click',()=>download());

  async function loadExamples(){
    const box=qs('#ejemplosList'); if(!box)return; box.innerHTML='<p>Cargando...</p>';
    const r=await fetch('/api/estudio/ejemplos'); const d=await r.json(); const xs=d.ejemplos||[];
    box.innerHTML=xs.length?xs.map(e=>`<div class="estudio-example-row"><span class="estudio-pill ${e.clasificacion.toLowerCase()}">${labels[e.clasificacion]}</span><div><b>${esc(e.nombre)}</b><p>${esc(e.fundamento||'')}</p>${e.nombre_archivo?`<small>${esc(e.nombre_archivo)}</small>`:''}</div><button class="danger" data-del-example="${e.id}">Eliminar</button></div>`).join(''):'<div class="settings-empty">Todavía no hay ejemplos cargados.</div>';
    box.querySelectorAll('[data-del-example]').forEach(b=>b.onclick=async()=>{if(!confirm('¿Eliminar este ejemplo?'))return;await fetch('/api/estudio/ejemplos/'+b.dataset.delExample,{method:'DELETE'});loadExamples();});
  }
  let examplePdfFile = null;
  const exampleInput=qs('#ejemploPdf'), exampleDrop=qs('#examplePdfDrop'), exampleSelected=qs('#examplePdfSelected');
  function renderExamplePdf(file){
    examplePdfFile=file||null;
    if(!exampleSelected)return;
    exampleSelected.hidden=!examplePdfFile;
    if(exampleDrop)exampleDrop.hidden=!!examplePdfFile;
    if(examplePdfFile){
      qs('#examplePdfName').textContent=examplePdfFile.name;
      qs('#examplePdfMeta').textContent=`${(examplePdfFile.size/1048576).toFixed(1)} MB`;
    }
  }
  function validPdf(file){ return !!file && (file.type==='application/pdf' || file.name.toLowerCase().endsWith('.pdf')); }
  exampleInput?.addEventListener('change',()=>{const f=exampleInput.files?.[0]; if(validPdf(f))renderExamplePdf(f); else renderExamplePdf(null);});
  ['dragenter','dragover'].forEach(ev=>exampleDrop?.addEventListener(ev,e=>{e.preventDefault();exampleDrop.classList.add('drag')}));
  ['dragleave','drop'].forEach(ev=>exampleDrop?.addEventListener(ev,e=>{e.preventDefault();exampleDrop.classList.remove('drag')}));
  exampleDrop?.addEventListener('drop',e=>{const f=e.dataTransfer.files?.[0]; if(validPdf(f))renderExamplePdf(f);});
  qs('#examplePdfClear')?.addEventListener('click',()=>{examplePdfFile=null;if(exampleInput)exampleInput.value='';renderExamplePdf(null);});

  qs('#ejemploForm')?.addEventListener('submit',async e=>{
    e.preventDefault(); const state=qs('#ejemploEstado'); state.textContent='Guardando...';
    const fd=new FormData();fd.append('nombre',qs('#ejemploNombre').value.trim());fd.append('clasificacion',qs('#ejemploClasificacion').value);fd.append('fundamento',qs('#ejemploFundamento').value.trim());if(examplePdfFile)fd.append('pdf',examplePdfFile);
    const r=await fetch('/api/estudio/ejemplos',{method:'POST',body:fd});const d=await r.json();
    if(!r.ok){state.textContent=d.error||'No se pudo guardar';return;} state.textContent='Guardado'; e.target.reset(); examplePdfFile=null; renderExamplePdf(null); loadExamples(); setTimeout(()=>state.textContent='',1800);
  });

  async function loadHistory(){
    const box=qs('#estudioHistory'); if(!box)return; box.innerHTML='<p>Cargando...</p>'; const r=await fetch('/api/estudio/lotes');const d=await r.json();const xs=d.lotes||[];
    box.innerHTML=xs.length?xs.map(x=>`<div class="estudio-history-row"><div><b>${esc(x.titulo||'Análisis')}</b><small>${esc(String(x.creado_en||''))} · ${Number(x.cantidad||0)} PDF</small></div><button class="secondary" data-lote="${x.id}">Abrir</button><a class="primary" href="/api/estudio/lotes/${x.id}/descargar">Descargar</a></div>`).join(''):'<div class="settings-empty">Todavía no hay análisis anteriores.</div>';
    box.querySelectorAll('[data-lote]').forEach(b=>b.onclick=async()=>{const rr=await fetch('/api/estudio/lotes/'+b.dataset.lote);const dd=await rr.json(); if(rr.ok){loteId=b.dataset.lote;casos=dd.casos||[];document.querySelector('[data-estudio-tab="analizar"]').click();renderResults();}});
  }
})();
