# Architecture Guardrails: preservar componentes reutilizables (shared) en CFDI-AES

## Objetivo

Proteger la estructura ya refactorizada de [frontend/src/App.jsx](../../frontend/src/App.jsx) y evitar que el código de negocio fiscal se mezcle con los componentes y hooks reutilizables. El principio central es:

- `shared/` debe ser reutilizable y agnóstico a negocio.
- `domains/<dominio>/` debe contener la lógica específica de cada flujo de negocio.
- La capa de presentación no debe conocer detalles de CFDI, validaciones fiscales ni reglas de negocio internas.

## Principio de frontera

La arquitectura del frontend se organiza así:

- `frontend/src/shared/components/`: componentes puros, sin lógica de negocio.
- `frontend/src/shared/hooks/`: hooks reutilizables, genéricos, con manejo de sesión o infraestructura.
- `frontend/src/shared/layout/`: shell visual y providers globales (ej. Toast, AppShell).
- `frontend/src/shared/utils/`: helpers, formateo y utilidades sin estado.
- `frontend/src/domains/<dominio>/`: flujo de negocio y vistas únicas por dominio.

El criterio de decisión es simple:

- Si un módulo puede usarse sin cambiar de negocio ni de contexto, vive en `shared`.
- Si un módulo depende de reglas fiscales, emisores, clientes, facturación, IA o de un contexto específico del producto, vive en `domains/*`.

## Qué sí va en shared

`shared` solo debe contener elementos derivados de infraestructura, UI base o utilidades transversales.

Ejemplos válidos:

- `Btn`, `Card`, `KPI`, `SectionTitle`, `TwoCol`
- `ToastProvider` y wrappers de notificaciones globales
- `useBreakpoint` o hooks de ventana / viewport
- `fetchAuth` para autenticación y transporte HTTP genérico
- `format` helpers para moneda, porcentaje, fechas y texto de UI
- `AppShell`, navegación global y shell de layout

Estas piezas deben ser:

- reutilizables en varios dominios
- sin modelo financiero ni regla fiscal embebida
- independientes del contenido del negocio

## Qué no va en shared

Se prohíbe mover lógica específica de CFDI, permisos, planes, emisores o facturación a `shared` si ese código no puede reutilizarse en otro dominio del mismo tipo.

Prohibido:

- lógica de validación fiscal dentro de componentes `shared`
- uso directo de reglas del negocio CFDI en `shared/components/*`
- hooks compartidos que conocen `emisorActivoRfc`, clientes, planes, addendas o estados de factura
- helpers que mezclen formato fiscal con comportamiento del dominio
- providers globales que estén acoplados a un único caso de uso de negocio

## Patrón recomendado por dominio

Cada dominio debe encapsular su contexto propio.

### `auth`

Mantener:

- login
- registro
- reset password
- recuperación de contraseña
- estado de sesión / autenticación

No debe depender de detalles de facturación ni de la estructura de CFDI.

### `administracion`

Mantener:

- emisores
- clientes
- usuarios
- series
- configuración administrativa

La capa de administración puede consumir `shared` para layout y botones, pero debería encapsular la lógica de negocio y la API del dominio.

### `facturacion`

Mantener:

- facturas
- reporte mensual
- dashboard de costos
- contador virtual
- flujo de alta de CFDI

Si algo depende del emisor activo, del negocio actual, del plan o de reglas fiscales, debe vivir aquí.

### `ia`

Mantener:

- lector de documentos
- chat fiscal
- anomalías
- integración con IA

La capa de IA puede reusar `shared`, pero no debe introducir lógica fiscal ni reglas de negocio en componentes compartidos.

## Adaptadores y wrappers

Cuando un dominio necesite interactuar con una pieza reusable, se recomienda un wrapper o adaptador del dominio, no una extensión del shared.

Ejemplo:

- `shared/hooks/useEmisores` puede existir como proveedor genérico y de contexto
- pero el acceso al contexto y la selección del emisor activo debe ser consumido por `domains/facturacion/*` o `domains/administracion/*` con adaptadores locales
- la lógica del negocio (qué hace un emisor activo en un flujo específico) no debe vivir en `shared`

## Reglas de contribución

Antes de abrir un PR que toque arquitectura:

- [ ] Confirmar si el cambio afecta la frontera `shared` vs `domains`.
- [ ] Si afecta `shared`, verificar que la pieza sigue siendo verdaderamente reutilizable.
- [ ] Si afecta un dominio, mantener la lógica del negocio dentro del dominio.
- [ ] No mover un helper a `shared` solo porque parece útil una vez; debe ser útil en 2+ contextos sin acoplarse a negocio.
- [ ] Documentar el cambio si modifica la intención de la arquitectura.

## Criterios de aceptación

Este documento se considera cumplido cuando:

- existe una guía clara en `/docs/architecture/guardrails.md`
- los nuevos PRs validan que cambios en dominio no alteran contratos de `shared`
- los componentes reutilizables no contienen lógica fiscal ni de negocio específica
- cada dominio conserva su propio modelo y sus adaptadores

## Siguiente control de calidad

La regla práctica para todo refactor futuro es:

> Si un componente o hook no puede reutilizarse en un segundo dominio sin cambiar de contexto, no pertenece a `shared`.

Esto es la barrera principal para preservar la base reusable montada en el refactor de App.jsx y evitar regresiones en el MVP de CFDI-AES.
