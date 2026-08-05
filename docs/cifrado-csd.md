# Cifrado del CSD en reposo (`administracion`)

Desde el 05 ago 2026 (#34), el CSD (certificado, llave privada y contraseña)
que guarda `administracion` en Postgres (tabla `emisores`, columnas
`csd_cert_base64`, `csd_key_base64`, `csd_password`) se cifra en reposo con
[Fernet](https://cryptography.io/en/latest/fernet/) (de la librería
`cryptography`). El cifrado/descifrado es transparente a nivel de modelo de
SQLAlchemy (`EmisorCSDCifrado` en `database.py`) — el resto del código
(endpoints de `main.py`) sigue leyendo/escribiendo estas columnas como
strings normales, sin saber que están cifradas.

**Alcance deliberadamente acotado:** esta tarea solo protege el dato en
reposo. Hoy ese CSD guardado en `administracion` no se usa para ningún
timbrado real — `facturacion` firma con archivos estáticos separados
(`CSD_CERT_PATH`/`CSD_KEY_PATH`/`CSD_PASSWORD`, ver `.env` y
`certs_test/`). Conectar el CSD cifrado de `administracion` al flujo real
de timbrado es trabajo aparte (tarjeta de seguimiento en el Project).

## La llave maestra: `CSD_MASTER_KEY`

- Vive únicamente en la variable de entorno `CSD_MASTER_KEY`, leída por
  `administracion` desde su `.env` (nunca hardcodeada, nunca commiteada —
  `.env` ya está en `.gitignore`).
- Es una llave Fernet: 32 bytes aleatorios codificados en base64 URL-safe.
- **Si `CSD_MASTER_KEY` se pierde, todo el CSD cifrado en la base de datos
  queda irrecuperable.** No hay backdoor ni recuperación — es cifrado
  simétrico real. Guardar una copia de la llave en un lugar seguro fuera
  del repo (gestor de secretos, vault) antes de manejar CSDs reales de
  clientes en producción.

### Generar una llave nueva

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Pegar el resultado como `CSD_MASTER_KEY=...` en el `.env` real (nunca en
`.env.example`, que debe seguir con un placeholder).

### Rotar la llave

Fernet no soporta "recifrar en el sitio" — rotar significa descifrar todo
con la llave vieja y volver a cifrar con la llave nueva:

1. Genera la llave nueva (ver arriba), pero **no la actives todavía** —
   guárdala aparte.
2. Con la llave vieja aún activa en `CSD_MASTER_KEY`, corre un script que:
   - Lea cada fila de `emisores`.
   - Descifre `csd_cert_base64`/`csd_key_base64`/`csd_password` con la
     llave vieja.
   - Vuelva a cifrar cada valor con la llave nueva.
   - Actualice la fila.
   (Mismo patrón que la migración de datos inicial — ver más abajo.)
3. Reemplaza `CSD_MASTER_KEY` en el `.env` por la llave nueva.
4. Reinicia `administracion` (`docker compose up -d administracion`).
5. Verifica que `GET /admin/emisores/<rfc>` siga respondiendo 200 para
   algún emisor conocido (si la llave nueva no coincide con lo recién
   cifrado, el descifrado transparente falla con una excepción al leer).

No hay rotación automática ni calendarizada todavía — es un procedimiento
manual, deliberadamente, hasta que el proyecto tenga un vault real (ver
#19-21).

## Migración de datos existentes (05 ago 2026)

Cuando se adoptó el cifrado, el emisor de prueba `EKU9003173C9` ya tenía su
CSD guardado en texto plano desde antes (#4). Ese dato **no se puede migrar
con Alembic** — Alembic versiona esquema (columnas, tablas, índices), no
transforma los valores que ya viven en las filas. Se migró con un script
aparte, ejecutado una sola vez, antes de desplegar el modelo con cifrado
transparente (para no intentar descifrar con Fernet un valor que todavía
era texto plano). El script leyó el valor plano, lo cifró con
`CSD_MASTER_KEY`, y hizo `UPDATE` directo sobre la fila — evidencia
(consulta cruda antes/después) documentada en la tarjeta #34 del Project.
