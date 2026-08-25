# Confirmación: tarjeta addenda_aes/reportes marcada como Hecho

- item_id: `PVTI_lAHOBYC0Os4BfCxZzg2m00E`
- content_id: `DI_lAHOBYC0Os4BfCxZzgK7yls`
- Proyecto: CFDI-AES (`PVT_kwHOBYC0Os4BfCxZ`)
- Fecha de verificación: 2026-08-20

## Commit verificado

```
commit 500bb8dd8a4202e39c4a87c4985d50dadcb1ffea
Author: Acierto en TI <92320826+aciertoenti@users.noreply.github.com>
Date:   Thu Aug 20 21:22:53 2026 -0600

    security: proteger addenda_aes y reportes con X-Internal-Key
```

Confirmado con `git fetch origin WhatsApp-Bot && git log origin/WhatsApp-Bot -1` — coincide con el commit local, pusheado.

## Cambios aplicados a la tarjeta

1. **Body actualizado** vía `updateProjectV2DraftIssue`: se agregó la sección `## RESUELTO (20 ago 2026)` al final del body existente (que ya tenía las secciones de dimensionamiento agregadas previamente). Nada del contenido anterior se modificó ni eliminó.
2. **Status cambiado** de `Backlog` a `Hecho` vía `updateProjectV2ItemFieldValue` (fieldId `PVTSSF_lAHOBYC0Os4BfCxZzhZYk6I`, optionId `a44fe99d`).

## Verificación independiente (query separada, post-cambio)

Query GraphQL directa sobre `PVTI_lAHOBYC0Os4BfCxZzg2m00E` confirmó:

- **Status**: `Hecho`
- **Body**: contiene la sección `## RESUELTO (20 ago 2026)` con:
  - Commit `500bb8d` (pusheado y verificado)
  - X-Internal-Key aplicado a las 4 rutas reales (GET /addenda/schemas, GET /addenda/{cliente_key}/schema, POST /addenda/aplicar, GET /reportes/mensual)
  - X-Negocio-Id documentado con docstring (no aplica todavía)
  - Verificación 403/200/403 en las 4 rutas, directo y vía Gateway
  - Bono: fail-fast a INTERNAL_API_KEY en docker-compose.yml, con referencia a la tarjeta pendiente `PVTI_lAHOBYC0Os4BfCxZzg1vKlM`

Todas las secciones previas del body (Hallazgo, Contexto adicional, Riesgo, Alcance propuesto, Relacionado, Dimensionamiento con evidencia real, Aclaración 03uVA) se conservaron intactas.
