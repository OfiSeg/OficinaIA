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
    {key:'rivadavia',nombre:'Rivadavia',logo_url:'/static/img/companias/rivadavia.png',aliases:['Seguros Rivadavia']}
  ]`);
  check(evaluate("resolverCompaniaCotizacion('AGRO SALTA')?.key") === 'agrosalta', 'Falló alias AgroSalta.');
  check(evaluate("resolverCompaniaCotizacion('Seguros Rivadavia')?.logo_url").endsWith('rivadavia.png'), 'Falló logo Rivadavia.');

  evaluate(`quoteSources=[inicializarIdentidadFuente({id:'atm',compania:'ATM',compania_detectada:'ATM',opciones:[
    {codigo:'A',tipo_vehiculo:'auto',nombre_cliente:'Responsabilidad Civil',grua:true},
    {codigo:'A1',tipo_vehiculo:'auto',nombre_cliente:'Responsabilidad Civil',grua:false}
  ]},'ATM')]`);
  check(evaluate("modeloComercialOpcion(quoteSources[0],quoteSources[0].opciones[0]).titulo_comercial") === 'Responsabilidad Civil · CON GRÚA', 'Falta CON GRÚA.');
  check(evaluate("modeloComercialOpcion(quoteSources[0],quoteSources[0].opciones[1]).titulo_comercial") === 'Responsabilidad Civil · SIN GRÚA', 'Falta SIN GRÚA.');
  check(evaluate("modeloComercialOpcion(quoteSources[0],{codigo:'TR',tipo_vehiculo:'auto',nombre_cliente:'Todo Riesgo',franquicia_pct:'3%%'}).titulo_comercial") === 'Todo Riesgo · FRANQUICIA 3%', 'Falló franquicia TR.');

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
  console.log('OK - modelo JS de Cotizaciones y bonificación global');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
