# Modelo de planes fijos del MVP

## Objetivo

Definir una oferta simple y autoservicio para vender CFDI-AES a negocios, contadores y despachos. El cliente debe poder elegir un plan, pagar en linea y activar su cuenta sin depender de una entrevista o de intervencion manual. El limite principal del MVP es el numero de emisores que un negocio puede administrar.

## Planes propuestos

| Plan | Cliente objetivo | Emisores incluidos | Facturas incluidas/mes | Precio mensual piloto | Precio anual piloto |
|---|---|---:|---:|---:|---:|
| Emprendedor@ | Persona que empieza a facturar | 1 | 10 | $399 MXN/mes | $3,990 MXN/anual |
| Basico | Persona fisica / micro negocio | 1 | 50 | $799 MXN/mes | $7,990 MXN/anual |
| Contador | Contador independiente con cartera pequena | 5 | 100 | $1,490 MXN/mes | $14,900 MXN/anual |
| Despacho | Despacho contable PyME | 10 | 500 | $2,990 MXN/mes | $29,900 MXN/anual |

Los precios son la propuesta de piloto preferida, no una tarifa definitiva. El precio anual equivale a pagar 10 meses y obtener 2 meses sin costo frente al pago mensual. Deben validarse antes de publicarse como precio permanente.

### Plan Emprendedor@

- 1 emisor.
- Hasta 10 facturas al mes.
- 1 usuario administrador.
- CFDI 4.0 estandar.
- Soporte por WhatsApp.

Este plan funciona como puerta de entrada, pero no debe incluir WhatsApp ilimitado. El costo de timbrado y del canal debe medirse para confirmar si el soporte por WhatsApp es solo atencion al cliente o tambien entrega de documentos.

### Beneficios del pago anual

- Dos meses sin costo frente a doce pagos mensuales.
- Precio bloqueado durante la vigencia anual.
- Onboarding prioritario y configuracion inicial de emisores/CSD.
- Soporte prioritario durante la activacion inicial.
- Renovacion automatica opcional, informada antes del cobro.
- Mismos limites de emisores del plan; el pago anual no regala emisores adicionales.
- Basico: 1 usuario admin, hasta 50 facturas al mes, CFDI 4.0 estandar y soporte por WhatsApp.
- Contador: 3 a 5 usuarios, hasta 100 facturas al mes, 20 facturas por emisor al mes, selector rapido de RFC, exportaciones basicas y soporte por WhatsApp.
- Despacho: hasta 500 facturas al mes, 50 facturas por emisor al mes, multiusuario con roles, onboarding asistido, SLA de soporte, reportes consolidados por emisor, plantillas y catalogos avanzados.
- Los timbres mensuales incluidos deben definirse como cuota de uso razonable antes de publicar los planes; no se ofrece timbrado ilimitado.
- Cuota inicial de facturas incluidas por mes: 10, 50, 100 y 500 para Emprendedor@, Basico, Contador y Despacho. La cuota debe contar operaciones efectivamente timbradas y su alcance debe confirmarse con Finkok.

Los beneficios deben centrarse en precio, estabilidad y onboarding. No se deben prometer timbres o WhatsApp ilimitados porque Finkok y Meta generan costos variables.

## Costos variables que deben entrar al modelo

### Finkok

La propuesta economica recibida de Finkok indica un costo de **$0.30 MXN por peticion al WebService**, sin IVA, con esquema sobre demanda y un consumo minimo mensual de **$150 MXN + IVA**. La cotizacion tambien indica que los timbres se emiten a traves de CVDSA, PAC #69901.

El modelo financiero debe distinguir entre peticiones enviadas, CFDI aceptados, reintentos, consultas y cancelaciones. Hay que confirmar por escrito con Finkok cuales operaciones son facturables y si el minimo de $150 aplica a la cuenta consolidada de CFDI-AES o a cada cliente.

Formula inicial: `costo_finkok = max(peticiones_facturables * 0.30, 150.00)` MXN antes de IVA.

### WhatsApp Business API

WhatsApp debe modelarse como costo variable, no como funcionalidad gratuita. Desde el 1 de julio de 2025, Meta cobra por mensaje de plantilla entregado; el importe depende del pais del destinatario, categoria de plantilla, volumen y reglas vigentes. Los mensajes no plantilla dentro de la ventana de atencion al cliente pueden ser gratuitos. Tambien pueden existir costos de numero, proveedor intermediario, infraestructura y soporte.

Por negocio se deben registrar mensajes enviados y entregados, plantillas y categoria, codigo de pais del destinatario, indicador `billable`, costo informado por Meta/proveedor y costo de infraestructura. La fuente operativa debe ser Meta Business Suite/Billing y el detalle tecnico debe contrastarse con `pricing_analytics` y los webhooks de estado de mensajes. Mientras no exista una tarifa productiva confirmada, `costo_whatsapp = 0` solo puede ser un supuesto temporal y el margen debe marcarse como provisional.

### Donde validar la tarifa productiva

1. Entrar a [Meta Business Suite](https://business.facebook.com/) con el Business Portfolio propietario de la cuenta de WhatsApp.
2. Abrir **Facturacion y pagos / Billing & payments** y seleccionar la cuenta de WhatsApp Business (WABA) y su entidad de cobro.
3. Revisar el rate card vigente para **MXN**, las facturas, cargos por mensaje y periodo de facturacion.
4. Confirmar en WhatsApp Manager que el numero productivo y las plantillas pertenecen a la misma WABA.
5. Descargar una factura o exportar el detalle de consumo para conservar evidencia con fecha, moneda, categoria y cantidad.
6. Contrastar el consumo con los webhooks de estado: `pricing.billable`, `pricing.category` y `pricing.type`, y con el campo `pricing_analytics` de Meta.

La tarifa publica se consulta en la [documentacion oficial de precios de WhatsApp](https://developers.facebook.com/docs/whatsapp/pricing), pero la cifra que debe entrar al margen es la que corresponda a la WABA productiva y aparezca en Billing o en las facturas de Meta. No usar la tarifa de un proveedor intermediario como si fuera la tarifa de Meta: si existe BSP, sumar ambas capas.

Para el MVP se recomienda incluir WhatsApp dentro de una cuota limitada o venderlo como add-on/cargo variable. No se debe prometer WhatsApp ilimitado antes de conocer el costo real.

### Margen por negocio

`costo_variable = costo_finkok + costo_whatsapp + costo_almacenamiento + costo_soporte_variable`

`margen_bruto = precio_plan - costo_variable`

`margen_bruto_porcentaje = margen_bruto / precio_plan`

Con el minimo PAC de $150 MXN, el plan Basico de $799 MXN deja preliminarmente $649 MXN antes de WhatsApp, almacenamiento, soporte, impuestos y gastos fijos. Esto no representa el margen final.

### Escenarios iniciales

| Escenario | Peticiones mensuales | Finkok antes de IVA | WhatsApp | Lectura |
|---|---:|---:|---:|---|
| Bajo | 0-500 | $150 minimo | Por confirmar | El minimo PAC domina |
| Medio | 1,000 | $300 | Por confirmar | El costo crece con uso |
| Alto | 5,000 | $1,500 | Por confirmar | Requiere capacidad o add-on |

## Estimacion preliminar de margen

Esta es una simulacion para decidir si la propuesta de precios es viable. No sustituye la tarifa productiva de WhatsApp, la confirmacion contractual de Finkok ni la medicion real de soporte y almacenamiento.

### Supuestos de trabajo por negocio y mes

- Los precios publicados se consideran importes finales con IVA del 16% incluido. Para calcular margen, `ingreso_neto = precio_cobrado / 1.16`; el IVA trasladado no es ingreso de CFDI-AES.
- Finkok: se usa el supuesto conservador de aplicar el minimo completo de $150 MXN a cada negocio. Si Finkok cobra el minimo una sola vez sobre la cuenta consolidada de CFDI-AES, el margen real mejorara.
- Finkok: $0.30 MXN por peticion; se modelan 10, 50, 100 y 500 peticiones para Emprendedor@, Basico, Contador y Despacho. En todos esos niveles aplica el minimo de $150 MXN bajo el supuesto actual.
- WhatsApp: como la tarifa productiva aun no esta confirmada, se usa una provision interna provisional de $50, $50, $100 y $300 MXN para Emprendedor@, Basico, Contador y Despacho. No es una tarifa de Meta.
- Almacenamiento: provision provisional de $15, $30 y $60 MXN.
- Soporte variable: provision provisional de $40, $100 y $250 MXN, consistente con el nivel de soporte de cada plan.
- Pago: se calcula Stripe con 3.6% + $3 MXN por transaccion nacional y Mercado Pago con 3.49% + $4 MXN para disponibilidad inmediata, sin IVA sobre la comision. Las tarifas pueden cambiar y deben confirmarse para suscripciones.
- No se incluyen IVA, impuestos sobre la renta, gastos fijos, ventas, desarrollo, contracargos ni costo de adquisición de cliente.

### Resultado mensual estimado actualizado con IVA incluido

| Plan | Precio cobrado | IVA 16% | Ingreso neto | Finkok | WhatsApp | Storage | Soporte | Stripe | Costo total | Margen neto | Margen % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Emprendedor@ | $399.00 | $55.03 | $343.97 | $150.00 | $50.00 | $15.00 | $40.00 | $17.36 | $272.36 | $71.60 | 20.82% |
| Basico | $799.00 | $110.21 | $688.79 | $150.00 | $50.00 | $15.00 | $40.00 | $31.76 | $286.76 | $402.03 | 58.37% |
| Contador | $1,490.00 | $205.52 | $1,284.48 | $150.00 | $100.00 | $30.00 | $100.00 | $56.64 | $436.64 | $847.84 | 66.01% |
| Despacho | $2,990.00 | $412.41 | $2,577.59 | $150.00 | $300.00 | $60.00 | $250.00 | $110.64 | $870.64 | $1,706.95 | 66.22% |

### Lectura del resultado

- Emprendedor@ es viable con margen neto moderado de 20.82%, pero no alcanza el objetivo de 43%-44%; requiere controlar WhatsApp y soporte.
- Basico, Contador y Despacho presentan margenes netos de 58.37%, 66.01% y 66.22% porque sus cuotas incluidas quedan por debajo del minimo de Finkok; el exceso de consumo debe cobrarse o limitarse.
- Despacho queda con 10 emisores y 500 facturas mensuales. Su margen es amplio en la cuota base, pero debe recalcularse si el consumo supera 500 peticiones.
- El plan anual mejora flujo de caja y reduce la friccion de renovacion, pero el IVA debe separarse antes de medir margen y no elimina el costo variable mensual. No debe usarse para ocultar un margen mensual negativo.

### Sensibilidad actualizada del plan Despacho

Con precio de $2,990 MXN, provision de WhatsApp de $300, almacenamiento de $60, soporte de $250 y comision Stripe aproximada de $110.64 sobre el mensual:

| Peticiones mensuales | Finkok | Margen estimado |
|---:|---:|---:|
| 100 | $150 minimo | $2,119.36 (70.9%) |
| 500 | $150 minimo | $2,119.36 (70.9%) |
| 1,000 | $300 | $1,969.36 (65.9%) |
| 2,000 | $600 | $1,669.36 (55.8%) |

La cuota de timbres incluida debe fijarse con base en esta sensibilidad, no solo por el numero de emisores. Una alternativa segura para el MVP es incluir una cuota baja y cobrar el excedente como add-on, manteniendo el plan por emisores como la unidad principal.

### Punto de equilibrio aproximado

Con los supuestos anteriores y sin considerar IVA ni gastos fijos:

- Emprendedor@: soporta aproximadamente 922 peticiones mensuales antes de llegar a margen cero, si WhatsApp, almacenamiento y soporte permanecen en sus provisiones.
- Basico: soporta aproximadamente 2,207 peticiones mensuales antes de llegar a margen cero.
- Contador: soporta aproximadamente 4,011 peticiones mensuales antes de llegar a margen cero.
- Despacho: soporta aproximadamente 7,565 peticiones mensuales antes de llegar a margen cero, con el costo provisional de WhatsApp, almacenamiento, soporte y la comision de pago incluidos.

Estos puntos de equilibrio son aproximados porque el minimo de Finkok crea un tramo no lineal y el costo real de WhatsApp puede cambiar por categoria.

## Modelo autoservicio tipo streaming

El flujo comercial principal debe funcionar como una suscripcion digital:

1. El visitante compara planes y elige Basico, Contador o Despacho.
2. Crea su cuenta con RFC personal, correo y datos del negocio.
3. Paga con tarjeta o transferencia procesada por Stripe/Mercado Pago.
4. El proveedor de pagos confirma el evento mediante webhook firmado.
5. CFDI-AES crea o activa el `Negocio`, asigna el plan y habilita el limite de emisores.
6. El usuario entra al panel, registra sus emisores y carga el CSD de cada uno.
7. El sistema muestra plan, vigencia, consumo, limite de emisores y opcion de cambiar o cancelar.
8. Ante pago fallido o vencimiento, la cuenta pasa a `Pendiente de pago` o `Suspendido` segun la politica definida.

La activacion manual queda solo como fallback para soporte, ventas B2B o transferencias durante una migracion. No debe ser el camino normal del cliente.

### Reglas de suscripcion

- Cada `Negocio` tiene una suscripcion con plan, estado, periodo, proveedor externo y referencia de cliente.
- Cada `Negocio` tiene una modalidad de cobro activa: mensual o anual.
- El webhook de pago es la unica fuente automatica de activacion; nunca se activa una cuenta solo porque el frontend regreso de Checkout.
- Los webhooks deben verificar firma, ser idempotentes y tolerar reintentos.
- Un cambio de plan debe definir prorrateo, fecha efectiva y nuevo limite de emisores.
- Un cambio de periodicidad mensual/anual debe definir prorrateo y fecha efectiva; no debe reiniciar el ciclo ni duplicar cobros.
- La renovacion anual debe avisarse antes del cargo y permitir cancelacion para evitar la siguiente renovacion.
- Una cancelacion conserva acceso hasta el fin del periodo pagado, salvo fraude o incumplimiento.
- Un pago fallido no borra datos, CSD ni documentos; restringe nuevas operaciones conforme a la politica de gracia.
- Los precios visibles deben indicar MXN, IVA, periodicidad, limites y que ocurre al excederlos.

## Reglas del modelo

- Un `Negocio` es una cuenta de pago y puede tener uno o varios emisores.
- Cada negocio tiene exactamente un plan activo.
- El limite de emisores se aplica al registrar un nuevo emisor, no elimina emisores existentes cuando cambia el plan.
- El plan puede cambiarse por decision operativa; el cambio debe quedar auditado.
- Un negocio no puede crear emisores por encima del limite de su plan.
- El MVP no incluye wallet ni saldo prepago; si incluye suscripcion recurrente por plan.
- Las facturas excedentes no se cobran automaticamente en el MVP; se bloquean, se solicita cambio de plan o se ofrece un add-on definido.
- El consumo de Finkok y WhatsApp debe medirse por negocio aunque el proveedor se facture de forma consolidada.
- El MVP no incluye WhatsApp ilimitado; requiere cuota, add-on o cargo variable.

## Estados de la cuenta

Los estados minimos son:

- `Activo`: puede usar las funciones incluidas en su plan.
- `Pendiente de pago`: cuenta creada, pero sin activacion comercial confirmada.
- `Suspendido`: no puede crear ni timbrar facturas hasta que un operador la reactive.
- `Cancelado`: cuenta cerrada; conserva la trazabilidad y los documentos segun la politica de retencion.

El campo `Negocio.estado` ya existe en el servicio de administracion. La transicion del estado debe ocurrir junto con el registro de activacion y vigencia en la tarea #18.

## Activacion automatica del MVP

1. Se crea una cuenta pendiente y se presenta Checkout con el plan elegido.
2. El proveedor confirma el pago mediante webhook firmado.
3. El backend crea o activa el negocio, registra la suscripcion y calcula la vigencia.
4. El negocio puede registrar emisores hasta el limite del plan.
5. Los eventos de renovacion, pago fallido, cancelacion y cambio de plan actualizan la cuenta idempotentemente.

La activacion automatica requiere Checkout, webhooks, suscripcion y aprovisionamiento. La tarea #18 debe cubrir este flujo; la activacion manual queda como respaldo de soporte.

## Criterios de aceptacion de la tarea #4

- [x] Existen tres planes diferenciados: Basico, Contador y Despacho.
- [x] Cada plan tiene un limite inicial de emisores.
- [x] La hipotesis de precios esta explicitamente separada de la tarifa definitiva.
- [x] La activacion autoservicio esta definida para el MVP.
- [x] El modelo aclara que un negocio es la cuenta de pago.
- [x] La regla de limite queda lista para implementarse en la tarea #5.
- [x] La tarea #18 queda identificada como responsable de Checkout, suscripcion, pago y vigencia.

## Decisiones pendientes de validacion comercial

- Confirmar precios con 3 a 5 negocios reales.
- Confirmar si el plan Contador debe incluir 5 emisores o una cantidad distinta.
- Confirmar si el plan Despacho debe incluir 10 emisores o una cantidad distinta.
- Definir precio y tratamiento de emisores adicionales para una fase posterior.
- Definir politica de reembolso, renovacion y cancelacion antes del primer contrato.
- Definir proveedor primario de pagos: Stripe o Mercado Pago.
- Definir periodo de prueba, periodo de gracia y comportamiento ante pago fallido.
- Definir prorrateo al cambiar de plan.
- Confirmar si se mantendra el descuento de dos meses gratis o se usara otro descuento anual.
- Definir aviso y politica de renovacion automatica anual.
- Confirmar con Finkok el alcance del minimo de $150 MXN y que peticiones son facturables.
- Obtener la tarifa productiva de WhatsApp por categoria y escenario de uso.
- Definir cuota incluida y politica de excedentes de timbrado y WhatsApp.
- Medir almacenamiento y soporte por negocio para completar el margen.

## Estudio de modelos de la competencia

### Alegra Mexico

Fuente publica consultada: [planes de Alegra Mexico](https://www.alegra.com/mexico/precios/) y [pagina de facturacion electronica](https://www.alegra.com/mexico/facturacion-electronica/), consultadas el 22 de agosto de 2026.

Modelo observado:

- Suscripcion mensual o anual, con descuento por pago anual.
- Prueba gratuita de 15 dias sin tarjeta.
- Segmentacion por tipo de solucion: solo facturacion, contabilidad y POS.
- Escalamiento por usuarios y volumen mensual de facturas: los planes publicados de contabilidad muestran 1 a 5 usuarios y 100 a 1,000 facturas mensuales.
- Facturacion electronica incluida como parte del plan, con funciones adicionales como pagos/cobros, reportes, portal de cliente, WhatsApp, conciliacion e integraciones en planes superiores.
- Venta asistida mediante contacto con asesor, ademas del alta en linea.

Lectura para CFDI-AES:

- El contador es un segmento explicito y no solo una variante del negocio individual.
- El limite de emisores es una metrica mas natural para CFDI-AES que el numero de usuarios, porque el valor del despacho esta en administrar RFCs distintos.
- Conviene ofrecer activacion simple y soporte cercano antes de construir una suite contable completa.

### Facturama

Fuente publica consultada: [sitio de Facturama](https://facturama.mx/), consultada el 22 de agosto de 2026. La pagina publica el modelo y la oferta, pero no expone en el contenido recuperado una tabla confiable de precios actuales; por eso no se copian importes.

Modelo observado:

- Prueba de 30 dias con 15 facturas gratis.
- Paquetes de facturas/folios y planes contables adaptados al volumen de timbrado.
- Portal en la nube con almacenamiento de documentos.
- Monetizacion adicional por productos de mayor complejidad: API, facturacion masiva, nomina, complementos, addendas, cotizaciones y herramientas contables.
- Captacion por autoservicio, soporte personalizado y venta de soluciones a la medida.

Lectura para CFDI-AES:

- Una prueba limitada reduce la friccion de la primera conversion.
- La API y la automatizacion son una ruta de expansion, no un requisito para el primer plan.
- CFDI-AES puede diferenciarse con una experiencia orientada a despachos y multiples emisores, dejando el cobro por volumen o wallet para una fase posterior.

### Facture.app

Fuente consultada: [facture.app](https://facture.app), consultada el 22 de agosto de 2026. El sitio no expuso contenido legible durante la consulta automatizada; por tanto, no se registra ningun precio, limite o funcionalidad como hecho confirmado.

Tratamiento para el benchmark:

- Competidor pendiente de verificacion manual.
- Antes de usarlo para una comparativa comercial se deben capturar sus planes, prueba, unidad de cobro, numero de emisores/RFCs, folios, usuarios y funciones de soporte.
- La ausencia de datos publicos verificables tambien es una señal comercial: CFDI-AES debe mantener precios y limites visibles para reducir friccion de compra.

### e.Doc

Fuente publica consultada: [e.Doc Carta Porte](https://e-doc.mx/c), consultada el 22 de agosto de 2026.

Modelo observado:

- Oferta especializada de Carta Porte en la nube.
- Soporta multiempresa y multiples origenes/destinos.
- Monetiza mediante demo y venta consultiva, con capacidad de integracion a ERP.
- La propuesta se dirige a empresas que transportan bienes, operadores logisticos y organizaciones con necesidades de cumplimiento especificas.
- El sitio comunica experiencia de 30 anos y soluciones separadas, entre ellas CFDI, addendas, intercambio de documentos y Carta Porte.

Lectura para CFDI-AES:

- No es un sustituto directo del MVP general de facturacion; compite en un modulo fiscal/logistico especializado.
- Carta Porte y addendas deben tratarse como add-ons o fases posteriores, no como requisito del plan inicial.
- La integracion con ERP es una ruta B2B de mayor ticket, pero requiere ciclo comercial y soporte tecnico mas largo.

### Portal Facturacion Proveedores (PFP)

Fuente publica consultada: [Portal de Facturacion Proveedores](https://portalfacturacionproveedores.com.mx), consultada el 22 de agosto de 2026.

Modelo observado:

- Venta B2B consultiva mediante demo gratuita y contacto comercial; no se publica una tabla de precios en la pagina revisada.
- Producto orientado a empresas con operaciones complejas, no al contribuyente individual que solo necesita emitir.
- La unidad de valor es el proceso de cuentas por pagar y proveedores: validacion CFDI/UUID, ordenes de compra, aprobaciones, tesoreria, pagos, reportes e integracion ERP.
- Segmentos comunicados: automotriz, construccion, mensajeria, supermercados, manufactura, e-commerce, mayoristas, minoristas y distribucion.

Lectura para CFDI-AES:

- PFP valida que existe un mercado separado de control de proveedores y cuentas por pagar, pero no debe mezclarse con el primer plan de emision.
- La recepcion CFDI, portal de proveedores y tesoreria son oportunidades de expansion modular.
- Si CFDI-AES entra en este segmento, necesitara venta consultiva, integraciones ERP, roles/aprobaciones y un modelo de precio por volumen o empresa.

### Vynex

Fuente publica consultada: [Vynex](https://vynex.mx), consultada el 22 de agosto de 2026.

Modelo observado:

- Suscripcion mensual de entrada con 14 dias gratis y sin tarjeta.
- Precio publicado de arranque: $199 MXN/mes por 1 RFC y 1 usuario.
- Descarga ilimitada y gestion/exportacion de CFDIs incluidas en el plan inicial.
- Expansion modular: cada RFC, usuario y modulo se agrega de forma independiente; no hay permanencia minima.
- Producto orientado a multi-RFC, despachos y administracion fiscal/contable, con cuentas por cobrar/pagar y futuras capacidades bancarias, contables y de facturacion.

Lectura para CFDI-AES:

- Es el benchmark mas cercano para la hipotesis de cobro recurrente por cuenta/RFC.
- Su precio de entrada presiona a CFDI-AES a justificar cualquier precio mayor con soporte, timbrado, CSD, administracion de emisores y flujo de despacho claramente superiores.
- Vynex cobra por RFC, usuario y modulo; CFDI-AES propone cobrar por negocio y limite de emisores. Esa diferencia debe validarse con entrevistas.

### Profactura

Fuente publica consultada: [Profactura](https://www.profactura.com.mx), consultada el 22 de agosto de 2026. Se toma esta URL como referencia del nombre solicitado "profactura".

Modelo observado:

- Entrada gratuita de 10 folios.
- Catalogo de productos con precios publicados por solucion, no solo un plan unico: sistema CFDI online desde $490, timbrado desde $200, buzon de recepcion desde $200, XML contable desde $1,160, validador XML desde $1,160, addendas desde $3,480 y ERP contable desde $7,499.
- Venta de productos separados, complementos y servicios especializados.
- Incluye soporte con ticket de respuesta menor a 24 horas y resguardo anunciado por 3 meses.
- Atiende tanto emision online como timbrado para desarrolladores y necesidades contables/operativas.

Lectura para CFDI-AES:

- El modelo modular permite monetizar necesidades puntuales y servicios de mayor valor.
- La prueba por folios es una referencia para el onboarding del MVP, aunque CFDI-AES busca una relacion recurrente por negocio.
- La politica de resguardo de documentos debe ser explicita en CFDI-AES; el almacenamiento es parte de la confianza del producto, no un detalle tecnico.

### Factura.com

Fuentes publicas consultadas: [Factura.com](https://factura.com/) y [planes anuales](https://factura.com/precios/), consultadas el 22 de agosto de 2026.

Modelo observado:

- Prueba gratuita de 15 dias.
- Dos modelos de compra: planes anuales y planes por folios/volumen.
- Planes anuales publicados por capacidad: Emprendedor $490 MXN/anual, Pyme $990 MXN/anual y Empresa $1,890 MXN/anual. Los importes se muestran sin IVA y estan sujetos a cambios.
- Escalamiento combinado por folios, numero de empresas/RFCs, usuarios y API por RFC: los planes publicados muestran 250/1,000/2,000 folios, 2/5/15 empresas y 1/2/3 usuarios, respectivamente.
- Funciones incluidas o ampliables: envio por WhatsApp, app movil, cotizaciones, autofacturacion web/API, recordatorios de pago, personalizacion PDF/email y complementos.
- Carta Porte 3.1 comunicada como incluida en todos los planes; tambien ofrece addendas, nomina, API, partners y distribuidores.
- Tiene rutas de autoservicio, migracion, soporte y venta de planes a la medida.

Lectura para CFDI-AES:

- Es el competidor mas comparable junto con Vynex: ambos hacen visible el escalamiento por RFC/empresa y capacidad.
- Su precio anual de entrada es sensiblemente menor que la hipotesis mensual de CFDI-AES; por eso CFDI-AES necesita justificar el precio con soporte especializado, administracion de despachos, seguridad de CSD y aislamiento multi-negocio.
- El modelo por folios puede ser una alternativa futura para clientes que no quieran una suscripcion, pero introducirlo en el MVP agregaria complejidad de consumo, renovacion y excedentes.
- La inclusion de WhatsApp, API y Carta Porte en paquetes comerciales muestra que las integraciones y complementos pueden funcionar como diferenciadores o add-ons, pero no deben distraer del flujo base.

### Comparacion ampliada por posicionamiento

| Competidor | Segmento principal | Unidad/modelo observable | Precio publico verificable | Implicacion para CFDI-AES |
|---|---|---|---|---|
| Alegra | Pyme, contador y empresa | Suscripcion por usuarios/volumen y modulos | Desde $138/mes en facturacion; planes contables publicados | Competir con foco de despacho, no con suite completa |
| Facturama | Pyme, contabilidad y desarrolladores | Prueba/folios, paquetes y modulos/API | Precio no confirmado en la pagina consultada | Copiar baja friccion, no su amplitud de producto |
| Facture.app | Pendiente de verificar | No confirmado | No confirmado | Mantener transparencia de planes y limites |
| e.Doc | Logistica y cumplimiento Carta Porte | Demo/venta consultiva e integracion ERP | No publicado en la pagina consultada | Carta Porte como add-on posterior |
| PFP | Empresas grandes y cuentas por pagar | Demo/venta B2B, procesos y ERP | No publicado | Recepcion/proveedores como expansion, no MVP |
| Vynex | Multi-RFC, despachos y administracion fiscal | Suscripcion modular por RFC, usuario y modulo | $199/mes, 1 RFC y 1 usuario | Competidor mas cercano; validar valor diferencial |
| Profactura | Emision, timbrado y servicios fiscales | Folios gratis, productos y modulos separados | Desde $200, $490, $1,160 y superiores segun producto | Referencia para folios, add-ons y resguardo |
| Factura.com | Pyme, multiempresa y desarrolladores | Plan anual por folios, empresas/RFCs y usuarios; API y volumen | $490, $990 y $1,890 MXN/anual publicados | Benchmark directo; comparar contra precio por emisores |

Los importes anteriores son los visibles en las paginas consultadas y pueden cambiar. No deben presentarse como una auditoria exhaustiva ni como comparacion funcional equivalente.

## Comparacion especifica del cobro autoservicio

La idea de CFDI-AES de elegir un plan, pagar en linea y administrar la cuenta desde el panel **si tiene precedentes directos**, aunque cada competidor combina capacidades de forma distinta:

| Competidor | Similitud con CFDI-AES | Evidencia publica | Diferencia relevante |
|---|---|---|---|
| Vynex | Alta | 14 dias gratis, $199 MXN/mes de entrada, mensual/anual, cancelacion cuando quieras, activacion de RFCs/usuarios/modulos desde la cuenta | Cobra modularmente por RFC, usuario y modulo; CFDI-AES propone planes por negocio y limite de emisores |
| Alegra | Alta | Prueba de 15 dias sin tarjeta, pago mensual/anual y planes que escalan por usuarios y facturas | Es una suite mas amplia de contabilidad/POS; no se confirma aqui todo el detalle del aprovisionamiento por webhook |
| Factura.com | Media | Registro de prueba, compra en linea, planes anuales por folios, empresas/RFCs y usuarios, y opciones de volumen | Predomina la vigencia anual y el consumo por folios; no es el mismo modelo de suscripcion mensual por negocio |
| Facturama | Media | Prueba de 30 dias con 15 folios y paquetes adaptados al volumen | El contenido consultado no confirma una suscripcion recurrente autoservicio ni sus precios actuales |
| Profactura | Media-baja | 10 folios gratis y enlaces de compra para productos como CFDI online, timbrado y buzon | Modelo de productos/servicios separados; no se confirma suscripcion recurrente tipo streaming |
| e.Doc | Baja | Agenda de demo para Carta Porte, multiempresa e integracion ERP | Venta consultiva especializada en Carta Porte, no alta autoservicio de facturacion general |
| PFP | Baja | Demo gratuita y contacto comercial para portal de proveedores | Venta B2B consultiva para cuentas por pagar, tesoreria y ERP |
| Facture.app | No verificable | El sitio no expuso contenido legible en la consulta | Requiere verificacion manual antes de comparar su cobro |

### Conclusiones del benchmark de cobro

1. **Vynex es el competidor mas parecido** a la experiencia deseada: prueba sin tarjeta, precio visible, cobro recurrente, cancelacion libre y expansion desde la cuenta.
2. **Alegra valida el formato de prueba mas suscripcion**, pero compite con una suite mas amplia y una escala de usuarios/volumen.
3. **Factura.com valida la compra autoservicio y el escalamiento**, pero su eje es anualidad, folios, RFCs y usuarios, no necesariamente una suscripcion mensual por negocio.
4. Los demas competidores muestran que los folios, add-ons y venta consultiva son alternativas, no evidencia de que debamos abandonar el modelo autoservicio.

La diferenciacion de CFDI-AES no puede ser solamente "tambien tenemos planes". Debe ser:

- alta automatica para un negocio con varios emisores
- limite y consumo explicados en una sola pantalla
- CSD por emisor con flujo guiado y seguro
- timbrado y cancelacion confiables
- estado de suscripcion, renovacion y bloqueo visibles
- soporte especializado para contadores y despachos

Por tanto, el modelo elegido queda respaldado por el mercado: **suscripcion autoservicio por negocio, con planes segun numero de emisores, prueba controlada, cobro recurrente, upgrades y cancelacion desde la cuenta**. La cuota de WhatsApp y los costos de Finkok deben aparecer como reglas de uso o add-ons para proteger el margen.

## Implicaciones comerciales actualizadas

## Diferenciador de CFDI-AES

El diferenciador principal no es emitir facturas, porque esa capacidad ya existe en varias plataformas del mercado. La propuesta de CFDI-AES es especializarse en el trabajo de contadores y despachos que administran multiples negocios y emisores desde una sola cuenta.

### Promesa del MVP

> **La facturacion multiempresa para contadores y despachos, con cada RFC organizado, seguro y listo para operar.**

La promesa se concreta en:

- una cuenta para administrar varios negocios
- multiples emisores/RFCs con aislamiento real de la informacion
- CSD independiente y seguro por emisor
- cambio rapido entre emisores
- timbrado, cancelacion y entrega de XML/PDF en un mismo flujo
- planes claros segun numero de emisores
- costos de Finkok y WhatsApp controlados por cuotas o add-ons, sin consumo ilimitado no calculado

### Diferenciacion futura

WhatsApp e IA pueden convertirse en el diferenciador de la siguiente etapa al reducir captura manual y asistir la facturacion desde tickets, documentos o conversaciones. Esa promesa no debe presentarse como capacidad completa del MVP hasta validar Meta, costos productivos y el flujo E2E.

La administracion multi-negocio, el aislamiento de datos, el CSD por emisor y el timbrado son la base actual; la experiencia especifica para despachos debe demostrarse con el piloto de la tarea #22.

### Posicionamiento frente a competidores

Vynex ya demuestra que existe demanda por multi-RFC, suscripcion y expansion desde la cuenta. Por eso, administrar varios RFCs por si solo no es una ventaja suficiente. CFDI-AES debe diferenciarse combinando multi-negocio, CSD seguro, flujo de despacho, soporte especializado y automatizacion fiscal progresiva.

No se debe prometer superioridad general frente a Alegra, Factura.com, Facturama o Vynex. La hipotesis verificable es que un despacho valorara mas una experiencia centrada en emisores, seguridad del CSD y operacion diaria que una suite contable generalista.

El estudio ampliado sugiere que CFDI-AES tiene cuatro posibles posiciones, pero solo una debe ser central en el MVP:

1. **MVP elegido:** plataforma de emision CFDI para negocios, contadores y despachos, con planes por numero de emisores.
2. **Expansion natural:** multi-RFC, roles, soporte y automatizacion para despachos.
3. **Add-ons posteriores:** Carta Porte, addendas, recepcion CFDI, portal de proveedores y API.
4. **Segmento enterprise posterior:** cuentas por pagar, tesoreria e integraciones ERP.

La hipotesis de precio debe probarse frente a tres referencias distintas: el precio mensual modular de Vynex, el modelo modular por producto/folios de Profactura y el precio anual por folios, empresas/RFCs y usuarios de Factura.com. La pregunta comercial central para las entrevistas es si un despacho prefiere pagar por RFC, por emisor administrado o por una cuenta con un limite amplio de emisores a cambio de soporte especializado.

Factura.com tambien vuelve necesaria una decision explicita para la siguiente iteracion: CFDI-AES debe empezar con suscripcion mensual por negocio y limite de emisores, o adoptar desde el inicio una alternativa por folios. La recomendacion sigue siendo suscripcion por negocio para el MVP, porque facilita activacion, limite y soporte; el modelo por folios puede evaluarse despues con datos de consumo real.

### Patron competitivo sintetizado

La evidencia publica revisada muestra cuatro patrones repetidos:

1. Entrada con prueba gratuita o paquete inicial limitado.
2. Suscripcion recurrente, normalmente mensual con incentivo anual, o paquetes de folios.
3. Precio que escala por capacidad observable: usuarios, volumen de facturas, modulos o integraciones.
4. Expansion del ingreso mediante contabilidad, POS, API, automatizacion, soporte e integraciones.

No es recomendable competir en el MVP intentando igualar todo el alcance de estas plataformas. La propuesta inicial de CFDI-AES debe ser mas estrecha:

- planes claros por numero de emisores
- soporte especializado para contadores y despachos
- alta y activacion asistida
- timbrado, cancelacion y entrega confiable de XML/PDF
- administracion multi-negocio con aislamiento de datos

## Ajuste recomendado de la propuesta

Mantener los tres planes como hipotesis de piloto, pero presentarlos como capacidad administrada por negocio:

| Elemento | CFDI-AES MVP | Razon |
|---|---|---|
| Unidad de precio | Negocio/mes | Un despacho administra varios emisores bajo una cuenta |
| Limite principal | Emisores | Se alinea con el valor del cliente objetivo |
| Cobro inicial | Checkout automatizado | Activa la suscripcion sin intervencion del operador |
| Prueba | Piloto asistido de 15 a 30 dias | Reduce riesgo operativo y recoge evidencia |
| Excedentes | Regla manual o add-on | Protege margen ante exceso de timbrado/WhatsApp |
| Expansion | Cobro automatico, API, WhatsApp e integraciones | Se reserva para Fase 2/3 |

La propuesta de precios de la tabla inicial sigue siendo una hipotesis. La siguiente validacion debe medir disposicion de pago, numero real de emisores por cliente, frecuencia de facturacion, consumo de WhatsApp y si el cliente prefiere pagar por cuenta, por emisor o por volumen.

## Fuentes y limites del estudio

- Se revisaron paginas publicas de Alegra Mexico, Facturama y Factura.com, ademas de la propuesta economica de Finkok proporcionada para este proyecto, el 22 de agosto de 2026.
- Los precios y caracteristicas pueden cambiar; antes de publicar una comparativa comercial se deben volver a comprobar.
- No se infieren precios de competidores cuya pagina bloquea la consulta automatica o no publica una tabla legible.
- Esta seccion describe modelos observables, no afirma equivalencia funcional ni superioridad de CFDI-AES.
