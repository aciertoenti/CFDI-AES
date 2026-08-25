$ErrorActionPreference = 'Stop'
$Repo = 'aciertoenti/CFDI-AES'

Write-Host '==> Verificando GitHub CLI y autenticación'
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'GitHub CLI no está instalado. Instálalo antes de continuar.'
}

gh --version | Out-Null
if (-not $?) { throw 'GitHub CLI no está disponible.' }

gh auth status | Out-Null
if (-not $?) { throw 'GitHub CLI no está autenticado. Ejecuta: gh auth login' }

gh repo view $Repo | Out-Null
if (-not $?) { throw "No se pudo acceder al repositorio $Repo. Verifica permisos y nombre del repositorio." }

Write-Host "Repositorio válido: $Repo"

function Ensure-Milestone {
    param([string]$Name)
    $titles = gh api "repos/$Repo/milestones?state=all" --jq '.[].title' 2>$null
    if ($titles -and ($titles -contains $Name)) {
        Write-Host "Milestone ya existe: $Name"
        return
    }

    gh api -X POST "repos/$Repo/milestones" -f title="$Name" -f state='open' | Out-Null
    Write-Host "Milestone creado: $Name"
}

function Ensure-Label {
    param(
        [string]$Name,
        [string]$Color = 'ededed'
    )
    $labelNames = gh label list -R $Repo --limit 200 --json name --jq '.[].name' 2>$null
    if ($labelNames -and ($labelNames -contains $Name)) {
        Write-Host "Label ya existe: $Name"
        return
    }

    gh label create $Name -R $Repo --color $Color | Out-Null
    Write-Host "Label creado: $Name"
}

function Issue-Exists {
    param([string]$Title)
    $titles = gh issue list -R $Repo --state all --limit 500 --json title --jq '.[].title' 2>$null
    if ($titles -and ($titles -contains $Title)) {
        return $true
    }
    return $false
}

function Create-Issue {
    param(
        [string]$Title,
        [string]$Body,
        [string[]]$Labels,
        [string]$Milestone
    )

    if (Issue-Exists -Title $Title) {
        Write-Host "Issue ya existe: $Title"
        return
    }

    $bodyFile = [System.IO.Path]::GetTempFileName()
    Set-Content -Path $bodyFile -Value $Body -Encoding UTF8

    $args = @('issue', 'create', '-R', $Repo, '--title', $Title, '--body-file', $bodyFile)
    foreach ($label in $Labels) {
        $args += @('--label', $label)
    }
    if ($Milestone) {
        $args += @('--milestone', $Milestone)
    }

    & gh @args | Out-Null
    Write-Host "Issue creado: $Title"
    Remove-Item $bodyFile -Force -ErrorAction SilentlyContinue
}

# Milestones
Ensure-Milestone 'MVP Planes Fijos (sin wallet)'
Ensure-Milestone 'Fase 2 Wallet + Cobros Automáticos'
Ensure-Milestone 'Fase 3 Expansión Modular'

Write-Host ''

# Labels
Ensure-Label 'prio:P0' 'd73a4a'
Ensure-Label 'prio:P1' 'fbca04'
Ensure-Label 'prio:P2' '0e8a16'
Ensure-Label 'type:architecture' '5319e7'
Ensure-Label 'type:backend' '1d76db'
Ensure-Label 'type:frontend' 'c5def5'
Ensure-Label 'type:infra' 'bfdadc'
Ensure-Label 'type:security' 'd4c5f9'
Ensure-Label 'type:product' 'f9d0c4'
Ensure-Label 'phase:mvp' '0052cc'
Ensure-Label 'phase:2' '7c3aed'
Ensure-Label 'phase:3' 'a2eeef'
Ensure-Label 'guardrail' 'ff69b4'
Ensure-Label 'multi-tenant' 'cfd3d7'
Ensure-Label 'billing' 'f9d0c4'
Ensure-Label 'cfdi' '1f883d'
Ensure-Label 'csd' 'e4e669'
Ensure-Label 'finkok' 'b60205'
Ensure-Label 'meta-whatsapp' 'd876e1'
Ensure-Label 'idempotency' 'd4a5f9'
Ensure-Label 'needs-product-decision' 'fef2c0'

Write-Host ''

# Issues
Create-Issue -Title 'Architecture Guardrails: preservar componentes reutilizables (shared) en CFDI-AES' -Body @'
Definir y documentar límites entre capa reusable y capa dominio CFDI para evitar regresiones del refactor.

- Checklist:
  - [ ] Definir frontera shared vs domain/cfdi
  - [ ] Prohibir lógica fiscal en componentes shared
  - [ ] Definir patrón adapters/wrappers por dominio
  - [ ] Publicar guía de contribución arquitectónica

- Criterios de aceptación:
  - Documento en `/docs/architecture/guardrails.md`
  - PRs nuevos validan que cambios de dominio no alteran contratos shared
'@ -Labels @('prio:P0','type:architecture','phase:mvp','guardrail') -Milestone 'MVP Planes Fijos (sin wallet)'

Create-Issue -Title 'ADR-001: límites de acoplamiento entre librería reusable y módulos CFDI' -Body 'Documentar la arquitectura y los límites de acoplamiento entre la capa reusable y los módulos CFDI, con decisiones sobre qué debe quedar en shared y qué en domain/cfdi.' -Labels @('prio:P0','type:architecture','phase:mvp') -Milestone 'MVP Planes Fijos (sin wallet)'
Create-Issue -Title 'Contract Tests para componentes reutilizables' -Body 'Definir y ejecutar contract tests para los componentes reutilizables para evitar regresiones de compatibilidad y acoplamiento entre shared y dominio CFDI.' -Labels @('prio:P0','type:backend','type:frontend','phase:mvp','guardrail') -Milestone 'MVP Planes Fijos (sin wallet)'
Create-Issue -Title 'Modelo de planes fijos por emisores (Básico/Contador/Despacho)' -Body 'Diseñar el modelo de negocio del MVP con planes fijos por límite de emisores, diferenciando los perfiles Básico, Contador y Despacho y la política de activación.' -Labels @('prio:P0','type:backend','type:product','phase:mvp','billing') -Milestone 'MVP Planes Fijos (sin wallet)'
Create-Issue -Title 'Validación de límite de emisores al alta (regla central MVP)' -Body 'Implementar la validación central del límite de emisores al alta del negocio para asegurar que cada plan respete sus restricciones.' -Labels @('prio:P0','type:backend','phase:mvp','multi-tenant') -Milestone 'MVP Planes Fijos (sin wallet)'
Create-Issue -Title 'Migraciones multi-tenant: negocios, usuarios, emisores y roles' -Body 'Definir y ejecutar la migración del esquema para soportar la estructura multi-tenant con negocios, usuarios, emisores y roles apropiados para el MVP.' -Labels @('prio:P0','type:backend','phase:mvp','multi-tenant') -Milestone 'MVP Planes Fijos (sin wallet)'
Create-Issue -Title 'Módulo CSD por emisor: carga segura .cer/.key + contraseña cifrada' -Body 'Implementar el módulo para almacenamiento seguro por emisor del CSD (.cer/.key) con cifrado de la contraseña y políticas de acceso restrictivas.' -Labels @('prio:P0','type:security','type:backend','phase:mvp','csd') -Milestone 'MVP Planes Fijos (sin wallet)'
Create-Issue -Title 'Integración base Finkok para timbrado CFDI (MVP)' -Body 'Conectar la capa de timbrado CFDI con Finkok para la operación base del MVP, manteniendo el flujo documentado y validado para los emisores activos.' -Labels @('prio:P0','type:backend','phase:mvp','cfdi','finkok') -Milestone 'MVP Planes Fijos (sin wallet)'
Create-Issue -Title 'Panel operativo interno: asignación manual de plan y estado' -Body 'Construir el panel interno para que el equipo operativo asigne manualmente planes y estados a negocios/emisores durante la fase inicial del MVP.' -Labels @('prio:P1','type:product','type:backend','phase:mvp') -Milestone 'MVP Planes Fijos (sin wallet)'
Create-Issue -Title 'Wallet transaccional con constraints anti-negativos y ledger' -Body 'Diseñar y construir la wallet transaccional para la siguiente fase, con constraints anti-negativos, ledger y trazabilidad contable.' -Labels @('prio:P1','type:backend','phase:2','billing') -Milestone 'Fase 2 Wallet + Cobros Automáticos'
Create-Issue -Title 'Débito atómico + compensación automática ante rechazo PAC/SAT' -Body 'Definir el patrón de débito atómico para timbrado/servicios con compensación automática ante rechazo del PAC/SAT y consistencia idempotente.' -Labels @('prio:P1','type:backend','phase:2','cfdi','idempotency') -Milestone 'Fase 2 Wallet + Cobros Automáticos'
Create-Issue -Title 'Webhooks idempotentes Stripe/Mercado Pago para autoaprovisionamiento' -Body 'Implementar webhooks idempotentes de cobros para autoaprovisionamiento, integración con Stripe/Mercado Pago y manejo seguro de reintentos.' -Labels @('prio:P1','type:backend','phase:2','type:frontend','phase:2') -Milestone 'Fase 2 Wallet + Cobros Automáticos'
Create-Issue -Title 'Add-ons automáticos y facturación de recargas' -Body 'Definir el modelo de add-ons y recargas automáticas, con reglas de facturación y consumo por plan.' -Labels @('prio:P2','type:backend','type:product','phase:2') -Milestone 'Fase 2 Wallet + Cobros Automáticos'
Create-Issue -Title 'Meta WhatsApp: envío + conciliación de consumo' -Body 'Integrar Meta WhatsApp para entrega y conciliación de consumo de servicios, con validación de eventos y trazabilidad.' -Labels @('prio:P2','type:backend','phase:2','meta-whatsapp') -Milestone 'Fase 2 Wallet + Cobros Automáticos'
Create-Issue -Title 'Recepción de documentos CFDI (portal proveedor/cliente)' -Body 'Definir y construir la recepción de documentos CFDI en un portal para proveedores/clientes como expansión modular de la plataforma.' -Labels @('prio:P2','type:backend','type:frontend','phase:3') -Milestone 'Fase 3 Expansión Modular'
Create-Issue -Title 'Contabilidad electrónica (integración incremental)' -Body 'Planear la integración incremental con contabilidad electrónica y definir el sistema de sincronización y validación documental.' -Labels @('prio:P2','type:backend','phase:3') -Milestone 'Fase 3 Expansión Modular'
Create-Issue -Title 'Observabilidad avanzada y SLA por plan' -Body 'Definir métricas operativas, observabilidad avanzada y SLA por plan para la etapa de expansión modular y operación en producción.' -Labels @('prio:P2','type:infra','phase:3') -Milestone 'Fase 3 Expansión Modular'

Write-Host ''
Write-Host '==> Resumen final'
Write-Host "Milestones verificados: MVP Planes Fijos (sin wallet), Fase 2 Wallet + Cobros Automáticos, Fase 3 Expansión Modular"
Write-Host 'Labels verificados: prioridad, tipo, fase, contexto'
Write-Host "Issues creados o ya existentes en $Repo"
Write-Host ''
Write-Host 'Próximos pasos:'
Write-Host '1. Revisar la lista de issues en GitHub'
Write-Host '2. Crear el primer PR del MVP con el guardrail arquitectónico'
Write-Host '3. Definir backlog del equipo y priorizar P0'
