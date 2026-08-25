#!/usr/bin/env bash
set -euo pipefail

REPO="aciertoenti/CFDI-AES"

echo "==> Verificando GitHub CLI y autenticación"
if ! command -v gh >/dev/null 2>&1; then
  echo "Error: GitHub CLI no está instalado. Instálalo antes de continuar."
  exit 1
fi

gh --version >/dev/null
if ! gh auth status >/dev/null 2>&1; then
  echo "Error: GitHub CLI no está autenticado. Ejecuta: gh auth login"
  exit 1
fi

if ! gh repo view "$REPO" >/dev/null 2>&1; then
  echo "Error: no se pudo acceder al repositorio $REPO. Verifica permisos y nombre del repo."
  exit 1
fi

echo "==> Repositorio válido: $REPO"

ensure_milestone() {
  local name="$1"
  if gh api "repos/$REPO/milestones?state=all" --jq ".[] | select(.title == \"$name\") | .title" 2>/dev/null | grep -Fxq "$name"; then
    echo "Milestone ya existe: $name"
  else
    gh api -X POST "repos/$REPO/milestones" -f title="$name" -f state="open" >/dev/null
    echo "Milestone creado: $name"
  fi
}

ensure_label() {
  local name="$1"
  local color="${2:-ededed}"
  if gh label list -R "$REPO" --limit 200 --json name --jq '.[].name' 2>/dev/null | grep -Fxq "$name"; then
    echo "Label ya existe: $name"
  else
    gh label create "$name" -R "$REPO" --color "$color" >/dev/null
    echo "Label creado: $name"
  fi
}

issue_exists() {
  local title="$1"
  gh issue list -R "$REPO" --state all --limit 500 --json title --jq '.[].title' 2>/dev/null | grep -Fxq "$title"
}

create_issue() {
  local title="$1"
  local body="$2"
  local labels="$3"
  local milestone="$4"

  if issue_exists "$title"; then
    echo "Issue ya existe: $title"
    return 0
  fi

  local cmd=(gh issue create -R "$REPO" --title "$title" --body "$body")
  if [[ -n "$labels" ]]; then
    cmd+=(--label "$labels")
  fi
  if [[ -n "$milestone" ]]; then
    cmd+=(--milestone "$milestone")
  fi

  "${cmd[@]}" >/dev/null
  echo "Issue creado: $title"
}

# ---------- Milestones ----------
ensure_milestone "MVP Planes Fijos (sin wallet)"
ensure_milestone "Fase 2 Wallet + Cobros Automáticos"
ensure_milestone "Fase 3 Expansión Modular"

echo
# ---------- Labels ----------
ensure_label "prio:P0" "d73a4a"
ensure_label "prio:P1" "fbca04"
ensure_label "prio:P2" "0e8a16"

ensure_label "type:architecture" "5319e7"
ensure_label "type:backend" "1d76db"
ensure_label "type:frontend" "c5def5"
ensure_label "type:infra" "bfdadc"
ensure_label "type:security" "d4c5f9"
ensure_label "type:product" "f9d0c4"

ensure_label "phase:mvp" "0052cc"
ensure_label "phase:2" "7c3aed"
ensure_label "phase:3" "a2eeef"

ensure_label "guardrail" "ff69b4"
ensure_label "multi-tenant" "cfd3d7"
ensure_label "billing" "f9d0c4"
ensure_label "cfdi" "1f883d"
ensure_label "csd" "e4e669"
ensure_label "finkok" "b60205"
ensure_label "meta-whatsapp" "d876e1"
ensure_label "idempotency" "d4a5f9"
ensure_label "needs-product-decision" "fef2c0"

echo
# ---------- Issues ----------
create_issue \
  "Architecture Guardrails: preservar componentes reutilizables (shared) en CFDI-AES" \
  $'Definir y documentar límites entre capa reusable y capa dominio CFDI para evitar regresiones del refactor.\n\n- Checklist:\n  - [ ] Definir frontera shared vs domain/cfdi\n  - [ ] Prohibir lógica fiscal en componentes shared\n  - [ ] Definir patrón adapters/wrappers por dominio\n  - [ ] Publicar guía de contribución arquitectónica\n\n- Criterios de aceptación:\n  - Documento en `/docs/architecture/guardrails.md`\n  - PRs nuevos validan que cambios de dominio no alteran contratos shared' \
  "prio:P0,type:architecture,phase:mvp,guardrail" \
  "MVP Planes Fijos (sin wallet)"

create_issue \
  "ADR-001: límites de acoplamiento entre librería reusable y módulos CFDI" \
  "Documentar la arquitectura y los límites de acoplamiento entre la capa reusable y los módulos CFDI, con decisiones sobre qué debe quedar en shared y qué en domain/cfdi." \
  "prio:P0,type:architecture,phase:mvp" \
  "MVP Planes Fijos (sin wallet)"

create_issue \
  "Contract Tests para componentes reutilizables" \
  "Definir y ejecutar contract tests para los componentes reutilizables para evitar regresiones de compatibilidad y acoplamiento entre shared y dominio CFDI." \
  "prio:P0,type:backend,type:frontend,phase:mvp,guardrail" \
  "MVP Planes Fijos (sin wallet)"

create_issue \
  "Modelo de planes fijos por emisores (Básico/Contador/Despacho)" \
  "Diseñar el modelo de negocio del MVP con planes fijos por límite de emisores, diferenciando los perfiles Básico, Contador y Despacho y la política de activación." \
  "prio:P0,type:backend,type:product,phase:mvp,billing" \
  "MVP Planes Fijos (sin wallet)"

create_issue \
  "Validación de límite de emisores al alta (regla central MVP)" \
  "Implementar la validación central del límite de emisores al alta del negocio para asegurar que cada plan respete sus restricciones." \
  "prio:P0,type:backend,phase:mvp,multi-tenant" \
  "MVP Planes Fijos (sin wallet)"

create_issue \
  "Migraciones multi-tenant: negocios, usuarios, emisores y roles" \
  "Definir y ejecutar la migración del esquema para soportar la estructura multi-tenant con negocios, usuarios, emisores y roles apropiados para el MVP." \
  "prio:P0,type:backend,phase:mvp,multi-tenant" \
  "MVP Planes Fijos (sin wallet)"

create_issue \
  "Módulo CSD por emisor: carga segura .cer/.key + contraseña cifrada" \
  "Implementar el módulo para almacenamiento seguro por emisor del CSD (.cer/.key) con cifrado de la contraseña y políticas de acceso restrictivas." \
  "prio:P0,type:security,type:backend,phase:mvp,csd" \
  "MVP Planes Fijos (sin wallet)"

create_issue \
  "Integración base Finkok para timbrado CFDI (MVP)" \
  "Conectar la capa de timbrado CFDI con Finkok para la operación base del MVP, manteniendo el flujo documentado y validado para los emisores activos." \
  "prio:P0,type:backend,phase:mvp,cfdi,finkok" \
  "MVP Planes Fijos (sin wallet)"

create_issue \
  "Panel operativo interno: asignación manual de plan y estado" \
  "Construir el panel interno para que el equipo operativo asigne manualmente planes y estados a negocios/emisores durante la fase inicial del MVP." \
  "prio:P1,type:product,type:backend,phase:mvp" \
  "MVP Planes Fijos (sin wallet)"

create_issue \
  "Wallet transaccional con constraints anti-negativos y ledger" \
  "Diseñar y construir la wallet transaccional para la siguiente fase, con constraints anti-negativos, ledger y trazabilidad contable." \
  "prio:P1,type:backend,phase:2,billing" \
  "Fase 2 Wallet + Cobros Automáticos"

create_issue \
  "Débito atómico + compensación automática ante rechazo PAC/SAT" \
  "Definir el patrón de débito atómico para timbrado/servicios con compensación automática ante rechazo del PAC/SAT y consistencia idempotente." \
  "prio:P1,type:backend,phase:2,cfdi,idempotency" \
  "Fase 2 Wallet + Cobros Automáticos"

create_issue \
  "Webhooks idempotentes Stripe/Mercado Pago para autoaprovisionamiento" \
  "Implementar webhooks idempotentes de cobros para autoaprovisionamiento, integración con Stripe/Mercado Pago y manejo seguro de reintentos." \
  "prio:P1,type:backend,phase:2,type:frontend,phase:2" \
  "Fase 2 Wallet + Cobros Automáticos"

create_issue \
  "Add-ons automáticos y facturación de recargas" \
  "Definir el modelo de add-ons y recargas automáticas, con reglas de facturación y consumo por plan." \
  "prio:P2,type:backend,type:product,phase:2" \
  "Fase 2 Wallet + Cobros Automáticos"

create_issue \
  "Meta WhatsApp: envío + conciliación de consumo" \
  "Integrar Meta WhatsApp para entrega y conciliación de consumo de servicios, con validación de eventos y trazabilidad." \
  "prio:P2,type:backend,phase:2,meta-whatsapp" \
  "Fase 2 Wallet + Cobros Automáticos"

create_issue \
  "Recepción de documentos CFDI (portal proveedor/cliente)" \
  "Definir y construir la recepción de documentos CFDI en un portal para proveedores/clientes como expansión modular de la plataforma." \
  "prio:P2,type:backend,type:frontend,phase:3" \
  "Fase 3 Expansión Modular"

create_issue \
  "Contabilidad electrónica (integración incremental)" \
  "Planear la integración incremental con contabilidad electrónica y definir el sistema de sincronización y validación documental." \
  "prio:P2,type:backend,phase:3" \
  "Fase 3 Expansión Modular"

create_issue \
  "Observabilidad avanzada y SLA por plan" \
  "Definir métricas operativas, observabilidad avanzada y SLA por plan para la etapa de expansión modular y operación en producción." \
  "prio:P2,type:infra,phase:3" \
  "Fase 3 Expansión Modular"

echo
printf '\n==> Resumen final\n'
printf 'Milestones verificados: MVP Planes Fijos (sin wallet), Fase 2 Wallet + Cobros Automáticos, Fase 3 Expansión Modular\n'
printf 'Labels verificados: prioridad, tipo, fase, contexto\n'
printf 'Issues creados o ya existentes en %s\n' "$REPO"
printf '\nPróximos pasos:\n'
printf '1. Revisar la lista de issues en GitHub\n'
printf '2. Crear el primer PR del MVP con el guardrail arquitectónico\n'
printf '3. Definir backlog del equipo y priorizar P0\n'
