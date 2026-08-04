# Migraciones de base de datos (Alembic)

Desde el 04 ago 2026 (#38), los 4 microservicios con base de datos real usan
[Alembic](https://alembic.sqlalchemy.org/) para versionar el esquema.
**Ya no se debe usar `ALTER TABLE` manual** — eso fue lo que causó dos
incidentes el 03 ago 2026 (ampliar `Factura.estado`, agregar
`Factura.detalle_pac`) donde el modelo de SQLAlchemy y la base de datos real
quedaron desincronizados hasta que alguien corrigió ambos a mano.

## Servicios con Alembic

| Servicio | Carpeta | Base de datos |
|---|---|---|
| `facturacion` | `backend/microservices/facturacion/` | `cfdi_facturas` (postgres_facturas) |
| `administracion` | `backend/microservices/administracion/` | `cfdi_admin` (postgres_admin) |
| `auth_usuarios` | `backend/microservices/auth_usuarios/` | `cfdi_auth` (postgres_auth) |
| `whatsapp_bot` | `backend/microservices/whatsapp_bot/` | `cfdi_bot` (postgres_bot) |

`addenda_aes` y `reportes` **no tienen modelos de SQLAlchemy ni base de datos
propia todavía** (son stubs) — no aplica Alembic ahí hasta que la tengan.

Cada servicio tiene su propio `alembic.ini` + carpeta `alembic/` — no hay
una configuración compartida entre servicios, porque cada uno tiene su
propia base de datos y su propio `Base.metadata`. `alembic/env.py` reutiliza
la configuración de conexión que el servicio ya usa en runtime
(`database.py` en `facturacion`/`administracion`/`auth_usuarios`,
`core/config.py` + `models/database.py` en `whatsapp_bot`) — las
credenciales nunca se duplican en `alembic.ini`.

## Cómo generar y aplicar una migración nueva

1. Modifica el modelo de SQLAlchemy como siempre (agregar/quitar columna,
   tabla, índice, etc.) en el `database.py` (o `models/schemas.py` en
   `whatsapp_bot`) del servicio correspondiente.
2. Dentro del contenedor del servicio (`docker exec -it <contenedor> sh`,
   luego `cd /app`), genera la migración automáticamente comparando el
   modelo contra la base de datos real:
   ```bash
   python -m alembic revision --autogenerate -m "descripcion corta del cambio"
   ```
   Alembic va a detectar la diferencia y escribir el `upgrade()`/`downgrade()`
   correspondiente en `alembic/versions/`. **Siempre revisa el archivo
   generado antes de aplicarlo** — autogenerate no detecta todo
   perfectamente (ej. renombrar una columna se ve como "borrar una y crear
   otra" si no se le indica lo contrario).
3. Copia el archivo de migración generado de vuelta al repo en el host
   (el contenedor no tiene bind mount del código fuente):
   ```bash
   docker cp <contenedor>:/app/alembic/versions/<archivo>.py backend/microservices/<servicio>/alembic/versions/
   ```
4. Aplica la migración de verdad:
   ```bash
   python -m alembic upgrade head
   ```
5. Confirma que quedó en el head esperado:
   ```bash
   python -m alembic current
   ```

## Cómo revertir una migración

```bash
python -m alembic downgrade -1   # revierte solo la ultima
python -m alembic downgrade <revision_id>  # revierte hasta una revision especifica
```

## Verificar que no hay drift entre el modelo y la base de datos real

```bash
python -m alembic revision --autogenerate -m "check"
```
Si el `upgrade()`/`downgrade()` generado queda vacío (`pass`), no hay
diferencia — bórralo sin aplicarlo. Si genera cambios reales, significa que
el modelo y la base de datos real se desincronizaron (por ejemplo, alguien
volvió a usar `ALTER TABLE` manual) y hay que investigar por qué antes de
aplicar nada.

## Nota sobre el `create_all()` que ya existía

`facturacion`, `administracion`, `auth_usuarios` y `whatsapp_bot` (este
último solo cuando `ENVIRONMENT=development`) siguen llamando a
`create_tables()` (que usa `Base.metadata.create_all`) al arrancar — esto
**no se quitó** porque sirve para levantar un ambiente nuevo desde cero
(una base de datos vacía) sin tener que correr migraciones a mano la
primera vez. `create_all` nunca modifica una tabla que ya existe, así que
convive bien con Alembic. Pero cualquier cambio a una tabla **que ya
existe** debe ir por una migración de Alembic — `create_all` no lo va a
detectar ni aplicar.

## Bootstrap automático para un ambiente nuevo (`stamp_head_si_es_ambiente_nuevo`)

Los 4 servicios llaman, en su `lifespan` de arranque, a
`stamp_head_si_es_ambiente_nuevo()` justo después de `create_tables()`:

```python
await create_tables()
await stamp_head_si_es_ambiente_nuevo()
```

Esto resuelve un hueco real que existía al adoptar Alembic sobre un
proyecto que ya usaba `create_all`: si alguien clona el repo hoy y levanta
los servicios contra una base de datos completamente vacía,
`create_tables()` construye el esquema completo (correcto, con el modelo
actual), pero **la tabla `alembic_version` nunca se crea sola** — nada en
Alembic sabe que esa base de datos "ya está al día". Si en el futuro se
agrega una segunda migración real (no vacía, ej. `add_column`) y alguien
corre `alembic upgrade head` en un ambiente así por primera vez, Alembic
intenta aplicar **todas** las migraciones desde cero, incluida la que
agrega una columna que `create_tables()` ya puso ahí — y truena con
`DuplicateColumnError`. Esto se probó de verdad, en un ambiente
desechable, antes de implementar el fix.

`stamp_head_si_es_ambiente_nuevo()` resuelve esto de forma segura:

- Si la tabla `alembic_version` **no existe todavía** (ambiente
  genuinamente nuevo): hace `alembic stamp head` automáticamente — marca
  la base de datos como sincronizada con la última revisión, **sin
  ejecutar ningún `upgrade()` real** (las tablas ya las construyó
  `create_tables()` con el modelo actual, que ya incluye todo lo que
  cualquier migración pasada habría hecho).
- Si `alembic_version` **ya existe** (ambiente con historia real, como
  los 4 servicios de este proyecto hoy): no hace absolutamente nada. Sigue
  siendo **responsabilidad manual** correr `alembic upgrade head` cuando
  haya una migración pendiente real.

**Por qué el paso de aplicar migraciones sigue siendo manual a propósito:**
si `alembic upgrade head` corriera automáticamente en cada arranque,
cualquier migración nueva se aplicaría sin que nadie la revisara primero
— exactamente el tipo de cambio de esquema sin supervisión que Alembic
existe para evitar. El auto-stamp solo cubre el caso especial y seguro de
"esta base de datos nunca tuvo ninguna migración" (donde no hay nada que
revisar, porque no se ejecuta DDL real) — todo lo demás sigue pasando por
una persona corriendo `alembic upgrade head` deliberadamente, como se
describe arriba.
