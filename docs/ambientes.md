# Ambientes del proyecto (#19)

Documentación de diseño únicamente — nada de esto crea infraestructura nueva.
Describe los 3 ambientes que el proyecto necesita, cuál existe hoy, y qué
falta para pasar de uno al siguiente.

## Cómo se usa cada archivo .env (#20, 13 ago 2026)

`docker-compose.yml` ya no tiene ninguna credencial de Postgres hardcodeada
— todas se leen de variables de entorno, con default = los valores de
siempre de Dev local (ver `.env.example`). Esto permite tener un archivo de
variables por ambiente, sin tocar `docker-compose.yml` para cambiar de uno a
otro:

```bash
# Dev local (de siempre) - .env sin sufijo, Docker Compose lo lee
# automaticamente, sin necesidad de --env-file:
docker compose up -d

# Staging - variables de .env.staging (copiado desde .env.staging.example):
docker compose --env-file .env.staging up -d

# Produccion - variables de .env.production (copiado desde
# .env.production.example):
docker compose --env-file .env.production up -d
```

Los 3 archivos reales (`.env`, `.env.staging`, `.env.production`) están
gitignorados — nunca se commitean con secretos reales. Solo sus plantillas
(`.env.example`, `.env.staging.example`, `.env.production.example`) están
en el repo, siempre con placeholders.

**Ojo:** esto separa las *credenciales* por ambiente (#20) — no crea el
Postgres físico separado, el dominio/TLS de Staging (#36), ni el pipeline de
CI/CD (#21). Son piezas distintas del mismo checklist de abajo.

## 1. Local/Dev — existe hoy

Lo que ya está corriendo en esta máquina vía `docker compose up`:

- **Facturación:** sandbox de Finkok (`demo-facturacion.finkok.com`), nunca
  producción de Finkok.
- **CSD:** el de prueba `EKU9003173C9` (`certs_test/`), cifrado en reposo
  desde #34. `facturacion` firma con los archivos estáticos directamente
  (`CSD_CERT_PATH`/`CSD_KEY_PATH`/`CSD_PASSWORD`) — el CSD cifrado que
  `administracion` persiste todavía no alimenta el timbrado real (#42, en
  progreso).
- **Red:** sin dominio público. `minio:9000` y los demás microservicios
  solo resuelven dentro de la red de Docker Compose o vía `localhost` con
  los puertos publicados al host (convención de desarrollo, no de
  producción).
- **WhatsApp:** un solo número configurado (`WHATSAPP_PHONE_NUMBER_ID`) —
  hoy no existe una separación explícita entre un número de prueba y uno
  real de producción.
- **Base de datos:** una Postgres por servicio, sin separación por
  ambiente — la misma que usa cualquiera que levante el proyecto
  localmente.
- **Alembic:** los 4 servicios con modelos reales corren
  `stamp_head_si_es_ambiente_nuevo()` al arrancar (ver
  `docs/migraciones.md`) — se autoconfiguran solos la primera vez que se
  levantan contra una base de datos vacía.

## 2. Staging/Pruebas — no existe todavía

**Propósito:** probar con condiciones más parecidas a producción (dominio
real, TLS, despliegue automático) sin arriesgar datos ni credenciales
reales de clientes.

**Reglas no negociables (del título original de #19):**
- Debe seguir usando el **sandbox de Finkok** — nunca producción de Finkok
  con datos de prueba.
- Debe usar un **número de WhatsApp Business separado del número real**.

**Qué lo diferenciaría de Dev:**
- Dominio real (aunque sea un subdominio, ej. `staging.tudominio.mx`) para
  que MinIO (#36) sea alcanzable desde fuera de Docker — hoy ni siquiera
  Dev resuelve esto, así que Staging es el primer ambiente donde este
  problema debe estar resuelto de verdad.
- Base de datos propia, separada de Dev (#20) — no reusar la misma
  Postgres.
- Despliegue automático en cada push (#21), para detectar regresiones
  antes de que lleguen a Producción.
- Puede seguir usando el mismo CSD de prueba que Dev (`EKU9003173C9`), pero
  servido desde el dominio real de Staging en vez de `minio:9000`.

**Qué debe resolverse antes de crear este ambiente:**
- #20 — `.env.staging` separado, con su propia base de datos.
- #21 — pipeline de CI/CD que despliegue automáticamente a Staging.
- #36 — dominio real + proxy reverso con TLS para MinIO.

## 3. Producción — no existe todavía

Requisitos antes de considerar esto listo para clientes reales pagando:

- **Dominio real de producción** (no solo el de Staging).
- **Finkok en modo producción**, no sandbox — implica cuenta/contrato real
  con el PAC, distinto del acceso de pruebas usado hoy.
- **Verificación de negocio de Meta completa.** Ligado directamente a lo
  vivido hoy con #32: el token de WhatsApp sigue bloqueado por una
  verificación de correo que Meta no resuelve por panel (solo foro). Antes
  de producción, esto debe estar resuelto de raíz — idealmente migrando al
  flujo de **System User** identificado en #32 (token de producción no
  ligado a un perfil personal), en vez de arrastrar el mismo mecanismo
  frágil de hoy.
- **CSD reales de clientes con custodia seria.** El cifrado en reposo ya
  existe (#34), pero tiene una limitación conocida: el endpoint que
  descifra el CSD (#42) hoy es alcanzable por TCP desde fuera de Docker
  porque `administracion` publica su puerto al host para otras vistas —
  solo está protegido por un secreto compartido (`X-Internal-Key`), no por
  aislamiento de red real. Antes de manejar CSDs reales de clientes, este
  puerto necesita un firewall real o un rediseño del aislamiento (ver nota
  en #42).
- **Migraciones de Alembic controladas**, no automáticas. El bootstrap
  automático (`stamp_head_si_es_ambiente_nuevo()`) existe únicamente para
  el caso de "esta base de datos nunca tuvo Alembic" — en Producción,
  cualquier migración posterior a la primera debe aplicarse a mano
  (`alembic upgrade head`), revisada por una persona, nunca en automático
  al arrancar el contenedor.
- **El swap real de #42 completado y probado a fondo** — `facturacion`
  debe firmar con el CSD real de cada cliente obtenido de `administracion`,
  no con archivos estáticos de prueba. Hoy esto está deliberadamente
  diferido por el riesgo de romper el timbrado real que ya funciona; no
  puede quedar pendiente al llegar a Producción, porque en producción no
  existe un solo CSD estático de prueba — existen tantos CSD como clientes.

## Checklist: Dev → Staging

- [ ] #20 — `.env.staging` con base de datos propia, separada de Dev
- [ ] #21 — CI/CD despliega automáticamente a Staging en cada push
- [ ] #36 — dominio real + proxy reverso con TLS para MinIO
- [ ] Número de WhatsApp Business de prueba, distinto del número real
- [ ] Confirmar que Staging apunta al sandbox de Finkok, nunca a producción de Finkok

## Checklist: Staging → Producción

- [ ] Dominio real de producción configurado (distinto del de Staging)
- [ ] Cuenta de Finkok en modo producción (no sandbox)
- [ ] Verificación de negocio de Meta completa, token vía System User (ver #32)
- [ ] Endpoint de CSD descifrado (#42) aislado de verdad a nivel de red, no solo por secreto compartido
- [ ] #42 completado: `facturacion` firma con el CSD real de cada cliente, no con archivos estáticos
- [ ] Migraciones de Alembic aplicadas manualmente y revisadas — auto-stamp solo se usó la primera vez, nunca como sustituto de revisión real
- [ ] Plantillas de WhatsApp aprobadas por Meta, si se activan mensajes proactivos (#47)
- [ ] Modelo de tenants (#15) y planes de precio (#16) implementados en código, no solo diseñados
- [ ] Pipeline de CI/CD exige aprobación manual para desplegar a Producción (#21)
- [ ] Frontend conectado a través del Gateway con JWT real (hoy llama directo a `administracion`/`facturacion`, bypaseando la autenticación de #10) — ver tarjeta aparte para esto, no depende de hosting real.
