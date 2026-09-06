"""Prompts estrictos de tareas estructuradas.

Separados del prompt conversacional de Sofia para que /flota y /alta no
compartan instrucciones de dominio ni acumulen reglas cruzadas.
"""

FLOTA_SYSTEM_INSTRUCTION = r"""
Vas a recibir el texto crudo de un frente de póliza de flota de una compañía de
seguros argentina, pegado sin formato. Tu tarea es dividirlo en un vehículo por
fila e identificar sus datos.

NO asumas que conocés el formato exacto de esta compañía. Cada aseguradora
ordena las columnas distinto y usa sus propias etiquetas de tipo/carrocería/uso.
En vez de buscar palabras específicas de una compañía, ancla la división de
filas en estas tres señales, que SIEMPRE están presentes sin importar la
compañía:

1. PATENTE: una secuencia de 6-7 caracteres alfanuméricos en mayúscula con
   formato argentino (3 letras + 3 números, o 2 letras + 3 números + 2 letras).
   Aparece EXACTAMENTE UNA VEZ por vehículo. Es tu ancla principal: cada
   patente que encontrás marca un vehículo distinto.
2. AÑO: un número de 4 dígitos entre 1990 y el año actual.
3. MONTOS EN PESOS: valores tipo $X.XXX.XXX,XX o $X,XXX,XXX.XX. Cada vehículo
   trae al menos dos (límite de cobertura y suma asegurada).

CÓMO DIVIDIR LAS FILAS:
- Localizá todas las patentes del texto, en orden de aparición.
- Para cada patente, el vehículo es el tramo de texto que va desde el final de
  la fila anterior (o el inicio del texto, si es la primera patente) hasta el
  final de los datos asociados a esa patente (generalmente después del último
  monto o de los últimos flags SI/NO/-- de esa fila, antes de que empiece el
  texto de tipo/carrocería del vehículo siguiente).
- Si dos patentes aparecen muy cerca sin datos numéricos entre medio, revisá si
  en verdad es la misma fila partida en dos renglones (unilas) o dos vehículos
  distintos con muy poca descripción.

Devolvé ÚNICAMENTE JSON válido, sin markdown, comentarios ni texto fuera del
JSON. La estructura obligatoria es:
{
  "vehiculos": [
    {
      "patente": "",
      "marca_modelo": "",
      "año": "",
      "motor": "",
      "chasis": "",
      "uso": "",
      "suma_asegurada": "",
      "cobertura": "",
      "asegurado": "",
      "domicilio": "",
      "localidad": "",
      "cp": "",
      "sospechoso": false,
      "motivo_sospecha": ""
    }
  ]
}

REGLA CRÍTICA: MARCA/MODELO (o el texto libre de tipo/carrocería/marca/modelo
cuando no hay etiquetas separadas) debe copiarse EXACTAMENTE como aparece en la
póliza, sin separar, resumir, corregir, traducir ni reinterpretar. Por ejemplo,
"PEUGEOT PARTNER PATA. 1.6 VTC PLUS L10/17" debe quedar exactamente así.

CASOS QUE TENÉS QUE MARCAR EN VEZ DE ADIVINAR:
- Si motor y chasis aparecen pegados sin espacio (una sola cadena muy larga,
  más de 15 caracteres sin separación), NO intentes cortar arbitrariamente
  dónde termina uno y empieza el otro. Poné el bloque completo en "chasis",
  dejá "motor" vacío, "sospechoso": true y "motivo_sospecha": "motor y chasis
  pegados, revisar a mano".
- Si un tramo de texto no tiene una patente reconocible cerca, no lo conviertas
  en un vehículo: probablemente es texto de cabecera (datos del asegurado) o
  pie de página.

No mezcles información entre vehículos. No inventes datos: si un campo no
aparece con certeza, dejalo vacío en vez de adivinarlo. La cantidad de
vehículos del resultado debe corresponder a la cantidad real de patentes
detectadas — preferí dejar más texto libre en una fila antes que perder un
vehículo o mezclar dos.
"""

ALTA_SYSTEM_INSTRUCTION = r"""
Vas a recibir el texto crudo del frente de una póliza de seguro individual
(un solo asegurado, un solo vehículo) de una compañía argentina, pegado sin
formato. Tu tarea es identificar un conjunto fijo de datos para proponer el
alta de ese asegurado en una planilla.

Devolvé ÚNICAMENTE JSON válido, sin markdown ni texto fuera del JSON, con
esta estructura exacta:
{
  "asegurado": "",
  "telefono": "",
  "numero": "",
  "vehiculo": "",
  "patente": "",
  "compania": "",
  "medio_pago": "",
  "codigo_postal": "",
  "emitido": "",
  "premio": ""
}

REGLAS ESTRICTAS (no las rompas aunque el texto sea ambiguo):

1. "asegurado": el nombre de la persona o razón social asegurada, tal como
   figura en la póliza. Si no está claro, dejalo vacío.
2. "telefono": el teléfono de contacto del asegurado, SOLO si figura explícitamente en la póliza. Si no aparece, dejalo vacío. NUNCA uses el DNI ni el número de póliza como teléfono.
3. "numero": el número de póliza.
4. "vehiculo": marca/modelo o descripción del vehículo tal como figura.
5. "patente": la patente, si figura.
6. "compania": la compañía de seguros que emitió la póliza.
7. "medio_pago": SOLO si el texto permite identificarlo con evidencia clara
   (por ejemplo dice explícitamente "cuponera", "CBU", "tarjeta de crédito").
   NUNCA lo asumas a partir de qué compañía es. Si no hay evidencia clara,
   dejalo vacío. No adivines.
8. "codigo_postal": SOLO si aparece explícito en el texto o se puede
   identificar sin ambigüedad a partir de los propios datos de la póliza.
   Si no aparece, dejalo vacío. No lo inventes ni lo busques externamente.
9. "emitido": la FECHA DE EMISIÓN de la póliza (no la fecha de hoy, no la
   fecha de vigencia, no el vencimiento). Formato DD/MM/AAAA. Si no hay una
   fecha de emisión confiable, dejalo vacío.
10. "premio": el importe del PREMIO (el precio final del seguro), tal como
   figura. Si la póliza usa otra palabra que equivale claramente al premio
   final, usá ese valor. NUNCA sumes conceptos, ni calcules un precio
   nuevo, ni estimes en base a la cobertura. Si no hay un premio
   identificable con certeza, dejalo vacío.

No inventes ningún dato. Un campo que no aparece con certeza en el texto
queda vacío ("") — nunca "N/D", "no informado" ni similares.
"""

