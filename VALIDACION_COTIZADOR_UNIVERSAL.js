/* Regresiones funcionales puras del modelo JS de Cotizaciones, sin navegador. */
const fs = require('fs');
const vm = require('vm');

const noop = () => {};
const storage = {getItem: () => null, setItem: noop, removeItem: noop};
const documentStub = {
  addEventListener: noop,
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => null,
  documentElement: {getAttribute: () => '', setAttribute: noop, style: {setProperty: noop}},
  body: {classList: {contains: () => false, add: noop, remove: noop, toggle: noop}, appendChild: noop},
};
const context = {
  console,
  document: documentStub,
  localStorage: storage,
  sessionStorage: storage,
  navigator: {},
  location: {pathname: '/', search: '', hash: ''},
  history: {},
  setTimeout,
  clearTimeout,
  URL,
  Blob,
  FormData,
  File: class {},
  window: null,
};
context.window = context;
context.window.addEventListener = noop;
context.window.matchMedia = () => ({matches: false, addEventListener: noop});
context.window.getComputedStyle = () => ({});
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/js/app.js', 'utf8'), context);

function evaluate(source) {
  return vm.runInContext(source, context);
}
function check(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  evaluate(`quoteCompanyCatalog=[
    {key:'agrosalta',nombre:'Agrosalta',logo_url:'/static/img/companias/agrosalta.png',aliases:['AgroSalta','AGROSALTA']},
    {key:'rivadavia',nombre:'Rivadavia',logo_url:'/static/img/companias/rivadavia.png',aliases:['Seguros Rivadavia']},
    {key:'federacion_patronal',nombre:'Federación Patronal',aliases:['Federación','Federacion','Fed','FedPat']},
    {key:'zurich',nombre:'Zurich',aliases:['Zurich Seguros']}
  ]`);
  check(evaluate("resolverCompaniaCotizacion('AGRO SALTA')?.key") === 'agrosalta', 'Falló alias AgroSalta.');
  check(evaluate("resolverCompaniaCotizacion('Seguros Rivadavia')?.logo_url").endsWith('rivadavia.png'), 'Falló logo Rivadavia.');
  const manualFed = evaluate("parsearAlternativaManual('Fed CF SA 71500000 precio 152000')");
  check(manualFed?.compania === 'Federación Patronal' && manualFed?.codigo === 'CF', 'La alternativa manual dejó de reconocer alias central de Federación.');
  const manualZurich = evaluate("parsearAlternativaManual('Zurich Z9 SA 40000000 precio 120000')");
  check(manualZurich?.compania === 'Zurich' && manualZurich?.codigo === 'Z9', 'Una compañía registrada sin parser específico no entra por alternativa manual.');
  check(manualZurich?.descripcion === '', 'Se inventó un speech para una compañía/código sin conocimiento confirmado.');

  evaluate(`quoteSources=[inicializarIdentidadFuente({id:'atm',compania:'ATM',compania_detectada:'ATM',opciones:[
    {codigo:'A',tipo_vehiculo:'auto',nombre_cliente:'Responsabilidad Civil',grua:true},
    {codigo:'A1',tipo_vehiculo:'auto',nombre_cliente:'Responsabilidad Civil',grua:false}
  ]},'ATM')]`);
  check(evaluate("modeloComercialOpcion(quoteSources[0],quoteSources[0].opciones[0]).titulo_comercial") === 'Responsabilidad Civil · CON GRÚA', 'Falta CON GRÚA.');
  check(evaluate("modeloComercialOpcion(quoteSources[0],quoteSources[0].opciones[1]).titulo_comercial") === 'Responsabilidad Civil · SIN GRÚA', 'Falta SIN GRÚA.');
  check(evaluate("modeloComercialOpcion(quoteSources[0],{codigo:'TR',tipo_vehiculo:'auto',nombre_cliente:'Todo Riesgo',franquicia_pct:'3%%'}).titulo_comercial") === 'Todo Riesgo · FRANQUICIA 3%', 'Falló franquicia TR.');

  // La familia normalizada no puede aplastar una variante comercial ya
  // resuelta por la fuente/catálogo (caso ATM Plus/Premium/Black).
  check(evaluate("modeloComercialOpcion(quoteSources[0],{codigo:'CPr',familia:'C_PLUS',perfil_normalizado:'C_PLUS',nombre_cliente:'Terceros Completo Premium'}).titulo_comercial") === 'Terceros Completo Premium', 'ATM Premium volvió a ser aplastado por C_PLUS.');
  check(evaluate("modeloComercialOpcion(quoteSources[0],{codigo:'CB',familia:'C_PLUS',perfil_normalizado:'C_PLUS',nombre_cliente:'Terceros Completo Black'}).titulo_comercial") === 'Terceros Completo Black', 'ATM Black volvió a ser aplastado por C_PLUS.');
  const atmBParcial = evaluate(`datosCoberturaPropuesta({
    compania:'ATM',codigo:'B',familia:'B',nombre:'Robo e Incendio Total y/o Parcial + Accidente Total',
    nombreComercial:'Robo e Incendio Total y/o Parcial + Accidente Total',
    riesgosDetectados:['RESPONSABILIDAD_CIVIL','INCENDIO_TOTAL','INCENDIO_PARCIAL','ROBO_HURTO_TOTAL','ROBO_HURTO_PARCIAL','DESTRUCCION_TOTAL_ACCIDENTE'],
    descripcion:'',precio:'$100.000'
  })`);
  const atmBTextos=atmBParcial.contenidos.filter(x=>x.tipo!=='nota').map(x=>x.texto);
  check(atmBTextos.includes('Incendio Total y Parcial')&&atmBTextos.includes('Robo/Hurto Total y Parcial'), 'La familia B volvió a pisar riesgos estructurados ATM.');

  evaluate(`genericQuoteSources=[inicializarIdentidadFuente({id:'generica-1',compania:'Compañía no identificada',opciones:[]},'Compañía no identificada')];quoteSources.push(genericQuoteSources[0])`);
  evaluate("confirmarCompaniaFuente('generica-1','AgroSalta','agrosalta')");
  check(evaluate("genericQuoteSources[0].compania_confirmada") === 'Agrosalta', 'La confirmada no reemplazó a la detectada.');
  check(evaluate("genericQuoteSources[0].company_key") === 'agrosalta', 'La confirmación no eligió logo/key.');
  evaluate("confirmarCompaniaFuente('generica-1','Rivadavia','rivadavia')");
  check(evaluate("genericQuoteSources[0].company_key") === 'rivadavia', 'El cambio posterior dejó el logo/key anterior.');

  context.fetch = async (_url, options) => {
    const body = JSON.parse(options.body);
    const final = Number(body.precio_base) * (1 - Number(body.descuento) / 100);
    return {ok: true, status: 200, redirected: false, text: async () => JSON.stringify({ok: true, precio_final: String(final)})};
  };
  evaluate(`mercantilFuente={id:'mercantil',compania:'Mercantil Andina',bonificacion:40,opciones:[
    {precio_base:'100000',descuento:35},{precio_base:'200000',descuento:35},{precio_base:'300000',descuento:30}
  ]}`);
  await evaluate('recalcularMercantilTodas()');
  check(evaluate('mercantilFuente.opciones.every(x=>x.descuento===40)') === true, '40% no se aplicó globalmente.');
  check(evaluate("mercantilFuente.opciones.map(x=>x.precio_final).join(',')") === '60000,120000,180000', 'No se recalcularon todas las alternativas.');

  check(evaluate("normalizarPorcentajeCotizacion('2%%')") === '2%', 'Se generó un porcentaje duplicado.');
  const mercantilPlus = evaluate(`datosCoberturaPropuesta({
    compania:'Mercantil Andina',codigo:'MP',familia:'C_PLUS',nombre:'Terceros Completo M Plus',
    nombreComercial:'Terceros Completo M Plus',servicioGrua:true,
    descripcion:'Responsabilidad civil, incendio total y parcial, robo total y parcial, destrucción total por accidente. Cubre ruedas, vidrios, granizo y cerraduras.',
    precio:'$100.000'
  })`);
  check(mercantilPlus.contenidos.some(x => /Incluye grúa/i.test(x.texto)), 'M Plus perdió la grúa confirmada en la salida comercial.');
  const tr75 = evaluate(`datosCoberturaPropuesta({
    compania:'San Cristóbal',familia:'TODO_RIESGO',nombre:'Todo Riesgo',nombreComercial:'Todo Riesgo',
    descripcion:'Responsabilidad civil. Daños parciales por accidente.',franquiciaPct:'7,5',precio:'$200.000'
  })`);
  check(!tr75.contenidos.some(x => x.tipo==='nota' && /franquicia/i.test(x.texto)), 'La nota de franquicia no debe viajar duplicada dentro de contenidos.');
  const wa75 = evaluate(`bloqueCoberturaWhatsAppDatos(${JSON.stringify(tr75)})`);
  check((wa75.match(/franquicia equivalente al 7,5% de la suma asegurada/gi)||[]).length===1, 'WhatsApp debe explicar la franquicia exactamente una vez.');
  const atmTr = evaluate(`datosCoberturaPropuesta({
    compania:'ATM',familia:'TODO_RIESGO',nombre:'Todo Riesgo',nombreComercial:'Todo Riesgo',
    descripcion:'Responsabilidad civil, incendio total y parcial, robo total y parcial, destrucción total y daños parciales por accidente. En caso de daño parcial, queda a cargo del asegurado una franquicia equivalente al 3% de la suma asegurada. Todo gasto que supere ese importe queda a cargo de la compañía.',
    franquiciaPct:'3',mostrarFranquiciaWhatsApp:false
  })`);
  const atmWa = evaluate(`bloqueCoberturaWhatsAppDatos(${JSON.stringify(atmTr)})`);
  check((atmWa.match(/franquicia equivalente al 3% de la suma asegurada/gi)||[]).length===1, 'ATM perdió o duplicó la explicación de franquicia en WhatsApp.');
  check(!/\*Franquicia:\*/i.test(atmWa), 'ATM cambió el formato histórico y agregó una línea de franquicia duplicable.');
  const plusTextos=mercantilPlus.contenidos.filter(x=>x.tipo!=='nota').map(x=>x.texto);
  for(const esperado of ['Responsabilidad Civil','Incendio Total y Parcial','Robo/Hurto Total y Parcial','Destrucción Total por Accidente']){
    check(plusTextos.includes(esperado), `C_PLUS perdió la prestación canónica: ${esperado}.`);
  }
  check(!plusTextos.some(x=>/, incendio/i.test(x)&&/, robo/i.test(x)), 'C_PLUS volvió a una frase legacy en lugar de una prestación por bullet.');

  // ATM: 3% y 6% son alternativas independientes; seleccionar una nunca
  // puede apagar la otra y no existe un selector genérico TR visible.
  evaluate(`atmCoberturasDetectadas=[
    {codigo:'TR',tipo_vehiculo:'auto',franquicia_pct:'3',ofrecer:false,orden:120},
    {codigo:'TR',tipo_vehiculo:'auto',franquicia_pct:'6',ofrecer:false,orden:120}
  ]`);
  evaluate("togglearFranquiciaATM('3')");
  evaluate("togglearFranquiciaATM('6')");
  check(evaluate("atmCoberturasDetectadas.filter(x=>x.codigo==='TR'&&x.ofrecer).length")===2, 'ATM sigue haciendo mutuamente excluyentes las franquicias 3% y 6%.');
  check(evaluate("ATM_CODIGOS_ORDEN.filter(codigo=>codigo!=='TR').includes('TR')")===false, 'El selector genérico TR volvió a la matriz visible.');

  console.log('OK - modelo JS de Cotizaciones, prestaciones canónicas, TR independiente y bonificación global');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
