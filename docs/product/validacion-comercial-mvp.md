# Validacion comercial y costos externos del MVP

Fecha de preparacion: 22 de agosto de 2026
Issue relacionada: #4 Modelo de planes fijos por emisores

## Objetivo

Validar que CFDI-AES puede venderse como un servicio autoservicio tipo streaming: el cliente elige un plan, paga en linea, recibe activacion automatica y administra su suscripcion sin depender de una llamada o de un operador. Tambien se deben confirmar los costos variables que afectan el margen: Finkok, WhatsApp, almacenamiento y soporte.

Las entrevistas son opcionales y sirven para ajustar precio, limites y mensaje comercial. No son un requisito tecnico para activar el producto.

## Investigacion opcional: 5 entrevistas

- 2 negocios que emiten sus propios CFDI.
- 2 contadores o despachos que administran varios RFCs.
- 1 negocio con alto volumen o proceso de cuentas por pagar.

Registrar para cada entrevista: giro, numero de RFCs/emisores, facturas mensuales, usuarios, herramienta actual, precio actual, tiempo perdido, problema principal y decision de compra.

No usar solo conocidos que ya apoyen el proyecto. Incluir al menos dos personas que actualmente paguen otro sistema.

## Guion opcional de entrevista de 20 minutos

### Contexto actual

1. Cuantos RFCs o emisores administran hoy?
2. Cuantas facturas emiten en un mes normal y en un mes alto?
3. Cuantas personas necesitan acceso y con que roles?
4. Que sistema usan hoy y cuanto pagan incluyendo IVA?
5. Que tareas siguen haciendo manualmente?

### Problema y valor

6. Cual es el problema mas costoso o urgente del proceso actual?
7. Cuanto tiempo cuesta corregir rechazos, buscar XML/PDF o cambiar de emisor?
8. Que tan importante es para ustedes el soporte especializado?
9. Necesitan emitir, cancelar, enviar XML/PDF, WhatsApp, reportes o recepcion CFDI?
10. Que motivo los haria cambiar de sistema este mes?

### Validacion de oferta

Presentar la oferta solo despues de escuchar el proceso actual:

- Emprendedor@: 1 emisor, hasta 10 facturas/mes, $399 MXN/mes como precio piloto, 1 usuario administrador, CFDI 4.0 estandar y soporte por WhatsApp.
- Basico: 1 emisor, hasta 50 facturas/mes, $799 MXN/mes como precio piloto, soporte por WhatsApp.
- Contador: 5 emisores, hasta 100 facturas/mes, 20 facturas por emisor al mes, $1,490 MXN/mes como precio piloto, soporte por WhatsApp.
- Despacho: 10 emisores, hasta 500 facturas/mes, 50 facturas por emisor al mes, $2,990 MXN/mes como precio piloto.
- Modalidad anual: Emprendedor@ $3,990, Basico $7,990, Contador $14,900 y Despacho $29,900 MXN/anual; 10 meses pagados por adelantado, con dos meses sin costo y mismos limites.
- Beneficios por plan: Basico con 1 usuario admin y soporte email 48h; Contador con 3-5 usuarios, selector RFC, exportaciones y soporte 24h; Despacho con roles, onboarding asistido, SLA, reportes consolidados, plantillas y catalogos avanzados.
- Activacion autoservicio y prueba de 15 a 30 dias.
- WhatsApp sujeto a cuota o cargo adicional; no prometer ilimitado.

Preguntar:

11. Cual plan describe mejor su operacion?
12. El limite de emisores es claro y suficiente?
13. El precio les parece barato, razonable o caro? Por que?
14. Preferirian pagar por negocio, por RFC/emisor o por folios?
15. En caso de fallo del pago automatico, aceptarian recibir soporte para completar la activacion?
16. Preferirian pagar mensual o anual con dos meses sin costo?
17. Que beneficio anual valorarian mas: descuento, precio bloqueado, onboarding o soporte prioritario?
18. Que tendria que incluir para pagar el primer mes o contratar el anual?
19. En que fecha real podrian comenzar?

No preguntar solamente "comprarias esto?". Solicitar una accion verificable: prueba con datos reales, compartir una factura de ejemplo sin secretos, agendar onboarding o aceptar una cotizacion.

## Matriz de registro

| Campo | Entrevista 1 | Entrevista 2 | Entrevista 3 | Entrevista 4 | Entrevista 5 |
|---|---|---|---|---|---|
| Segmento | | | | | |
| RFCs/emisores | | | | | |
| Facturas/mes | | | | | |
| Usuarios | | | | | |
| Sistema actual | | | | | |
| Precio actual MXN/mes | | | | | |
| Plan CFDI-AES sugerido | | | | | |
| Precio aceptable | | | | | |
| Prefiere negocio/RFC/folios | | | | | |
| Usa WhatsApp para entregar | | | | | |
| Accion comprometida | | | | | |

## Prueba obligatoria del flujo autoservicio

Antes de abrir ventas, ejecutar con cuentas de prueba:

- Registro de usuario y negocio.
- Seleccion de plan y precio visible en MXN con IVA aclarado.
- Checkout exitoso con Stripe o Mercado Pago sandbox.
- Webhook firmado que active exactamente una suscripcion y un negocio.
- Acceso al panel y registro de emisores hasta el limite del plan.
- Pago duplicado o webhook repetido sin duplicar la cuenta.
- Pago fallido, periodo de gracia, suspension y recuperacion tras renovacion.
- Cambio de plan con nuevo limite y politica de prorrateo definida.
- Cancelacion con acceso hasta el fin del periodo pagado.
- Pantalla de cuenta con plan, vigencia, estado y opcion de gestionar suscripcion.

## Criterios de decision comercial

Mantener la hipotesis de precio si se cumplen al menos estas condiciones:

- 3 de 5 entrevistados identifican un problema urgente.
- 3 de 5 aceptan probar con datos reales.
- 2 de 5 aceptan el precio piloto o proponen un precio superior justificable.
- La mayoria de contadores/despachos considera suficiente el limite de 5 o 20 emisores.
- Ningun plan tiene margen negativo en el escenario de uso observado.
- El flujo autoservicio activa correctamente la cuenta sin intervencion manual.
- Los webhooks repetidos no crean cuentas, suscripciones o facturas duplicadas.

Cambiar la hipotesis si:

- La mayoria prefiere pagar por RFC o folios.
- El precio queda por encima de alternativas comparables sin una diferencia valorada.
- El consumo real de timbrado hace inviable el plan Basico.
- WhatsApp representa un costo material y los clientes exigen incluirlo ilimitado.

## Confirmacion con Finkok

Enviar a ventas@finkok.com y solicitar confirmacion por escrito de:

- Si el costo de $0.30 MXN aplica por peticion WebService.
- Si se cobran igual timbrados aceptados, rechazos fiscales, reintentos, consultas y cancelaciones.
- Como se calcula exactamente el minimo de $150 MXN + IVA.
- Si el minimo aplica a la cuenta consolidada de CFDI-AES o a cada cliente/razon social.
- Si existe precio por volumen o contrato de integrador.
- Credenciales, URLs y condiciones para produccion.
- SLA, soporte, tiempos de respuesta y procedimiento ante indisponibilidad.
- Confirmacion de la relacion Finkok/CVDSA PAC #69901 indicada en la cotizacion.

Mensaje sugerido:

> Buen dia. Estamos evaluando integrar Finkok como PAC para una plataforma SaaS multi-negocio. Recibimos una propuesta con costo de $0.30 MXN por peticion WebService, bajo demanda, y minimo mensual de $150 MXN + IVA. Para cerrar nuestro modelo de precios necesitamos confirmar por escrito que operaciones son facturables, como aplica el minimo cuando atendemos varias razones sociales y cuales son las condiciones productivas, SLA y precios por volumen. Tambien agradecemos confirmar la participacion de CVDSA PAC #69901 mencionada en la propuesta. Saludos.

## Confirmacion con Meta/WhatsApp

Antes de asignar un saldo o cuota definitiva, confirmar en la cuenta productiva:

- Categoria de cada mensaje o plantilla utilizada.
- Precio vigente por categoria y mercado del destinatario.
- Diferencia entre conversaciones iniciadas por usuario y por empresa.
- Ventana de servicio y mensajes de servicio incluidos o cobrables.
- Costos de plantillas, numero, proveedor intermediario e infraestructura.
- Reporte disponible para conciliar consumo por negocio.
- Requisitos de verificacion, plantillas y opt-in.

Mensaje sugerido para soporte/proveedor:

> Estamos construyendo una plataforma multi-negocio que enviara XML/PDF y notificaciones de CFDI por WhatsApp Business Platform. Necesitamos confirmar tarifas productivas vigentes para Mexico, categorias de conversaciones, reglas de la ventana de servicio, costos de plantillas, requisitos de opt-in y como obtener un reporte de consumo atribuible por cliente. No queremos ofrecer WhatsApp ilimitado sin conocer el costo real.

## Modelo financiero minimo

Para cada negocio:

- `costo_finkok = max(peticiones_facturables * 0.30, minimo_aplicable)`
- `costo_whatsapp = mensajes_de_plantilla_entregados_cobrables * tarifa_categoria`
- `costo_variable = costo_finkok + costo_whatsapp + almacenamiento + soporte_variable`
- `margen_bruto = precio_plan - costo_variable`
- `margen_bruto_pct = margen_bruto / precio_plan`

Separar siempre IVA trasladado de costo neto y precio comercial. El IVA no debe confundirse con margen.

## Evidencia y cierre

La tarea #4 no debe cerrarse solo por tener una tabla de precios. Se cierra cuando exista:

- Prueba automatizada o evidencia reproducible del flujo autoservicio completo.
- Registro de entrevistas opcionales, si se realizaron, o una justificacion de por que se posponen.
- Decisiones documentadas sobre precio, unidad de cobro y limites.
- Confirmacion escrita de Finkok o una hipotesis marcada como no confirmada.
- Tarifa productiva de WhatsApp o una decision explicita de excluirlo del plan base.
- Calculo de margen para bajo, medio y alto consumo.
- Decision de continuar, ajustar o descartar los planes propuestos.

Mientras no exista esa evidencia, los precios de CFDI-AES deben presentarse como precio piloto y no como tarifa definitiva.
