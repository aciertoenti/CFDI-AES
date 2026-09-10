# ─── services/administracion/sat_descarga_client.py ──────────────────────────
# Cliente del ciclo de Descarga Masiva de CFDI del SAT (zg55DWY), sobre
# cfdiclient 1.6.3:
#
#   SolicitaDescarga(Emitidos|Recibidos) -> id_solicitud
#   VerificaSolicitudDescarga            -> estado (1..6) + lista de paquetes
#   DescargaMasiva                       -> el .zip en base64
#
# ARQUITECTURA (acordada, sin infra de jobs en el proyecto):
#   - Un endpoint "tick" (POST /admin/solicitudes-descarga/tick) que un
#     disparador EXTERNO invoca periodicamente. Cada tick re-autentica desde
#     cero: el token del SAT vive 5 min y el ciclo completo tarda de minutos
#     a horas, asi que NUNCA se persiste el token; se pide uno nuevo por cada
#     paso.
#   - El material sensible de la e.firma (key + password) se descifra SOLO en
#     memoria para construir el Fiel y se descarta al terminar el paso. Nunca
#     se loguea, nunca sale en una respuesta.
#
# Las 3 llamadas de cfdiclient usan `requests` (bloqueante); aqui se envuelven
# en asyncio.to_thread para no bloquear el event loop de FastAPI.
#
# Fase 1 (este archivo): logica + maquina de estados + persistencia + subida a
# MinIO, validada con respuestas sinteticas (sat_descarga_client_test.py). NO
# se ha hecho todavia ninguna llamada real al SAT.
# ─────────────────────────────────────────────────────────────────────────────
import asyncio
import base64
import io
import logging
import os
import uuid
from datetime import date, datetime, time
from functools import lru_cache
from typing import List, Optional

from cfdiclient import (
    Autenticacion,
    DescargaMasiva,
    Fiel,
    SolicitaDescargaEmitidos,
    SolicitaDescargaRecibidos,
    VerificaSolicitudDescarga,
)
from minio import Minio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Efirma, PaqueteDescarga, SolicitudDescarga, _fernet_efirma
from sat_codigos import (
    clasificar_cod_estatus,
    es_sin_resultados,
    verificar_bloqueo_previo,
)

logger = logging.getLogger("administracion.sat_descarga")

# ─── Almacenamiento del .zip (MinIO) ─────────────────────────────────────────
# Mismo patron que facturacion/storage_client.py, pero mas simple: aqui solo
# hace falta el cliente INTERNO (red de Docker) para subir. Los .zip son
# datos fiscales y NO se exponen con URL publica: se sirven despues por un
# endpoint autenticado. region= fijo para que el cliente no haga el
# round-trip de GetBucketLocation (ver el incidente documentado en
# facturacion/storage_client.py).
MINIO_URL = os.environ.get("MINIO_URL", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minio_admin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minio_secret")
MINIO_REGION = os.environ.get("MINIO_REGION", "us-east-1")
BUCKET_DESCARGAS = os.environ.get("MINIO_BUCKET_DESCARGAS", "cfdi-descargas-sat")


@lru_cache
def _minio_client() -> Minio:
    endpoint = MINIO_URL.replace("http://", "").replace("https://", "")
    secure = MINIO_URL.startswith("https://")
    client = Minio(
        endpoint,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=secure,
        region=MINIO_REGION,
    )
    if not client.bucket_exists(BUCKET_DESCARGAS):
        client.make_bucket(BUCKET_DESCARGAS)
    return client


def subir_zip(object_key: str, data: bytes) -> str:
    """Sube el .zip a MinIO (bucket BUCKET_DESCARGAS) y devuelve el object key
    guardado en paquetes_descarga.ruta_almacenamiento. Llamada bloqueante -
    los call sites la envuelven en asyncio.to_thread."""
    client = _minio_client()
    client.put_object(
        BUCKET_DESCARGAS,
        object_key,
        data=io.BytesIO(data),
        length=len(data),
        content_type="application/zip",
    )
    return object_key


# ─── Construccion del Fiel a partir de la e.firma custodiada ──────────────────
def construir_fiel(efirma: Efirma) -> Fiel:
    """Descifra key+password de la e.firma SOLO en memoria y arma el Fiel de
    cfdiclient. El objeto Fiel y el material descifrado no deben loguearse ni
    devolverse en ninguna respuesta."""
    cer_der = base64.b64decode(efirma.cert_base64)
    key_b64 = _fernet_efirma.decrypt(efirma.key_base64_cifrado.encode()).decode()
    key_der = base64.b64decode(key_b64)
    password = _fernet_efirma.decrypt(efirma.password_cifrado.encode()).decode()
    return Fiel(cer_der, key_der, password)


# ─── Excepcion de la guarda de pre-vuelo ─────────────────────────────────────
class BloqueoPrevioError(Exception):
    """Ya existe una solicitud NO reintentable (5001/5002/5003) para el mismo
    (efirma_id, tipo, fecha_desde, fecha_hasta). El caller debe rechazar con
    409 mostrando solicitud_previa.mensaje_sat + solicitud_previa.created_at,
    sin haber tocado el SAT."""

    def __init__(self, solicitud_previa: SolicitudDescarga) -> None:
        self.solicitud_previa = solicitud_previa
        super().__init__(
            f"Periodo bloqueado por el SAT (cod_estatus={solicitud_previa.cod_estatus})"
        )


# ─── Helpers internos ────────────────────────────────────────────────────────
async def _obtener_token(fiel: Fiel) -> str:
    """Token nuevo del SAT (TTL 5 min). Se pide en cada paso; nunca se
    persiste. Bloqueante -> to_thread."""
    return await asyncio.to_thread(
        Autenticacion(fiel).obtener_token, id=uuid.uuid4()
    )


def _rango_a_datetime(fecha_desde: date, fecha_hasta: date) -> tuple:
    """fecha_hasta se lleva al final del dia (23:59:59) para no perder los
    CFDI del ultimo dia; cfdiclient formatea con '%Y-%m-%dT%H:%M:%S'."""
    return (
        datetime.combine(fecha_desde, time.min),
        datetime.combine(fecha_hasta, time(23, 59, 59)),
    )


# ─── Paso 1: SolicitaDescarga ────────────────────────────────────────────────
async def solicitar_descarga(
    fiel: Fiel,
    negocio_id: int,
    efirma_id: int,
    rfc_titular: str,
    tipo: str,
    fecha_desde: date,
    fecha_hasta: date,
    solicitado_por_rfc: str,
    db: AsyncSession,
) -> SolicitudDescarga:
    """Dispara una solicitud de descarga masiva y persiste la fila.

    NOTA de firma: se agrego `solicitado_por_rfc` respecto al boceto del plan
    porque solicitudes_descarga.solicitado_por_rfc es NOT NULL (auditoria:
    quien la inicio). Lo pasa el endpoint desde X-Usuario-Rfc.

    Orden:
      1. verificar_bloqueo_previo() -> si hay una 5001/5002/5003 con los
         mismos parametros, lanza BloqueoPrevioError SIN tocar el SAT.
      2. token nuevo (Fiel -> Autenticacion).
      3. SolicitaDescargaEmitidos/Recibidos segun `tipo`.
      4. clasifica cod_estatus (sat_codigos) y persiste:
           cod_estatus == "5000" -> estado_solicitud=1 (Aceptada) + id_solicitud_sat
           cualquier otro        -> estado_solicitud=4 (Error); cod_estatus +
                                    mensaje_sat verbatim guardan el detalle real
    """
    tipo = tipo.lower().strip()
    if tipo not in ("emitidas", "recibidas"):
        # 'ambas' implicaria dos solicitudes (Emitidos + Recibidos) y por
        # tanto dos filas; queda fuera de Fase 1 a proposito.
        raise ValueError(
            f"tipo '{tipo}' no soportado todavia; usa 'emitidas' o 'recibidas'."
        )

    rfc_titular = rfc_titular.upper().strip()

    # 1. Guarda de pre-vuelo.
    bloqueo = await verificar_bloqueo_previo(
        db, negocio_id, efirma_id, tipo, fecha_desde, fecha_hasta
    )
    if bloqueo is not None:
        logger.info(
            "sat_descarga.bloqueo_previo efirma_id=%s tipo=%s rango=%s..%s cod_estatus=%s",
            efirma_id, tipo, fecha_desde, fecha_hasta, bloqueo.cod_estatus,
        )
        raise BloqueoPrevioError(bloqueo)

    # 2. Token nuevo.
    token = await _obtener_token(fiel)

    # 3. SolicitaDescarga.
    fecha_inicial, fecha_final = _rango_a_datetime(fecha_desde, fecha_hasta)
    if tipo == "emitidas":
        cliente = SolicitaDescargaEmitidos(fiel)
        kwargs = {"rfc_emisor": rfc_titular}
    else:
        cliente = SolicitaDescargaRecibidos(fiel)
        kwargs = {"rfc_receptor": rfc_titular}

    resultado = await asyncio.to_thread(
        cliente.solicitar_descarga,
        token=token,
        rfc_solicitante=rfc_titular,
        fecha_inicial=fecha_inicial,
        fecha_final=fecha_final,
        tipo_solicitud="CFDI",
        **kwargs,
    )

    cod_estatus = resultado.get("cod_estatus")
    mensaje = resultado.get("mensaje")
    clasif = clasificar_cod_estatus(cod_estatus)
    logger.info(
        "sat_descarga.solicitud efirma_id=%s tipo=%s cod_estatus=%s clasif=%s",
        efirma_id, tipo, cod_estatus, clasif["tipo"],
    )

    if cod_estatus == "5000":
        estado_solicitud = 1  # Aceptada
        id_solicitud_sat = resultado.get("id_solicitud")
    else:
        estado_solicitud = 4  # Error local; el detalle real va en cod_estatus/mensaje_sat
        id_solicitud_sat = None

    fila = SolicitudDescarga(
        negocio_id=negocio_id,
        efirma_id=efirma_id,
        tipo=tipo,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        id_solicitud_sat=id_solicitud_sat,
        estado_solicitud=estado_solicitud,
        cod_estatus=cod_estatus,
        mensaje_sat=mensaje,
        solicitado_por_rfc=solicitado_por_rfc,
    )
    db.add(fila)
    await db.commit()
    await db.refresh(fila)
    return fila


# ─── Paso 2: VerificaSolicitudDescarga (el "tick") ───────────────────────────
_MAX_REINTENTOS_TOKEN = 1  # estado 0 = token invalido; no deberia pasar (se
                           # re-autentica cada tick), pero si pasa: 1 reintento
                           # con token nuevo, NO estado terminal.


async def _verificar_una(fiel: Fiel, rfc_titular: str, id_solicitud_sat: str) -> dict:
    """VerificaSolicitudDescarga con reintento acotado si el SAT responde
    estado_solicitud=0 (token invalido). Devuelve el dict del SAT."""
    intentos = 0
    while True:
        token = await _obtener_token(fiel)
        resultado = await asyncio.to_thread(
            VerificaSolicitudDescarga(fiel).verificar_descarga,
            token,
            rfc_titular,
            id_solicitud_sat,
        )
        estado = int(resultado.get("estado_solicitud") or 0)
        if estado != 0 or intentos >= _MAX_REINTENTOS_TOKEN:
            return resultado
        intentos += 1
        logger.warning(
            "sat_descarga.token_invalido id_solicitud=%s reintento=%s",
            id_solicitud_sat, intentos,
        )


async def tick_verificar_solicitudes(db: AsyncSession) -> List[SolicitudDescarga]:
    """Un tick: verifica en el SAT todas las solicitudes en vuelo (1=Aceptada,
    2=EnProceso) y avanza su maquina de estados. Devuelve las que quedaron
    3=Terminada EN ESTE tick, para que el caller les baje los paquetes.

    Cada fila se procesa aislada (commit por fila): un error en una no tira
    las demas.
    """
    filas = list(
        await db.scalars(
            select(SolicitudDescarga).where(
                SolicitudDescarga.estado_solicitud.in_((1, 2))
            )
        )
    )
    terminadas: List[SolicitudDescarga] = []

    for fila in filas:
        try:
            efirma = await db.get(Efirma, fila.efirma_id)
            if efirma is None:
                logger.error(
                    "sat_descarga.tick efirma_id=%s inexistente (solicitud=%s)",
                    fila.efirma_id, fila.id,
                )
                continue
            fiel = construir_fiel(efirma)
            resultado = await _verificar_una(
                fiel, efirma.rfc_titular, fila.id_solicitud_sat
            )
            estado = int(resultado.get("estado_solicitud") or 0)
            cod_estatus = resultado.get("cod_estatus")
            codigo_estado_solicitud = resultado.get("codigo_estado_solicitud")
            mensaje = resultado.get("mensaje")

            if estado == 0:
                # Sigue invalido tras el reintento: NO es terminal. Se deja la
                # fila como estaba y se reintenta en el proximo tick.
                logger.warning(
                    "sat_descarga.tick token_invalido_persistente solicitud=%s", fila.id
                )
                continue

            # codigo_estado_solicitud se persiste SIEMPRE (no solo en el 5004):
            # es el resultado real del procesamiento y hoy la unica pista
            # confiable para distinguir un rechazo de un "sin resultados".
            fila.codigo_estado_solicitud = codigo_estado_solicitud

            if estado in (1, 2):
                fila.estado_solicitud = estado
                fila.cod_estatus = cod_estatus
                fila.mensaje_sat = mensaje
                await db.commit()
                continue

            if estado == 3:  # Terminada
                fila.estado_solicitud = 3
                fila.cod_estatus = cod_estatus
                fila.mensaje_sat = mensaje
                fila.numero_cfdis = int(resultado.get("numero_cfdis") or 0)
                for id_paquete in (resultado.get("paquetes") or []):
                    db.add(
                        PaqueteDescarga(
                            solicitud_id=fila.id,
                            id_paquete_sat=id_paquete,
                            descargado=False,
                        )
                    )
                await db.commit()
                await db.refresh(fila)
                terminadas.append(fila)
                continue

            # 4 Error · 5 Rechazada · 6 Vencida -> terminal. Se guarda el
            # estado_solicitud CRUDO del SAT (no se reescribe: sigue siendo un
            # espejo fiel del enum 1-6). La reinterpretacion de casos como
            # "5 + CodigoEstadoSolicitud=5004 = consulta vacia, no rechazo"
            # vive en sat_codigos.es_sin_resultados (capa de presentacion),
            # mismo criterio que 5002 con es_bloqueo_permanente.
            fila.estado_solicitud = estado
            fila.cod_estatus = cod_estatus
            fila.mensaje_sat = mensaje
            if es_sin_resultados(estado, codigo_estado_solicitud):
                # Exito sin resultados: numero_cfdis explicito a 0 (no NULL),
                # para que "consultado, 0 CFDI" no se confunda con "sin verificar".
                fila.numero_cfdis = 0
            await db.commit()

        except Exception:  # noqa: BLE001 - una fila mala no debe tumbar el tick
            await db.rollback()
            logger.exception("sat_descarga.tick error en solicitud=%s", fila.id)

    return terminadas


# ─── Paso 3: DescargaMasiva ──────────────────────────────────────────────────
async def descargar_paquetes(
    fiel: Fiel, solicitud: SolicitudDescarga, db: AsyncSession
) -> None:
    """Baja cada paquete pendiente (descargado=False) de una solicitud
    Terminada, lo sube a MinIO y marca la fila. Commit por paquete."""
    efirma = await db.get(Efirma, solicitud.efirma_id)
    if efirma is None:
        logger.error(
            "sat_descarga.descarga efirma_id=%s inexistente (solicitud=%s)",
            solicitud.efirma_id, solicitud.id,
        )
        return
    rfc_titular = efirma.rfc_titular

    paquetes = list(
        await db.scalars(
            select(PaqueteDescarga).where(
                PaqueteDescarga.solicitud_id == solicitud.id,
                PaqueteDescarga.descargado.is_(False),
            )
        )
    )

    for paquete in paquetes:
        try:
            token = await _obtener_token(fiel)
            resultado = await asyncio.to_thread(
                DescargaMasiva(fiel).descargar_paquete,
                token,
                rfc_titular,
                paquete.id_paquete_sat,
            )
            zip_bytes = base64.b64decode(resultado.get("paquete_b64") or "")
            object_key = (
                f"descargas/{solicitud.negocio_id}/{solicitud.id_solicitud_sat}/"
                f"{paquete.id_paquete_sat}.zip"
            )
            await asyncio.to_thread(subir_zip, object_key, zip_bytes)
            paquete.ruta_almacenamiento = object_key
            paquete.descargado = True
            await db.commit()
            logger.info(
                "sat_descarga.paquete_descargado solicitud=%s paquete=%s bytes=%s",
                solicitud.id, paquete.id_paquete_sat, len(zip_bytes),
            )
        except Exception:  # noqa: BLE001
            await db.rollback()
            logger.exception(
                "sat_descarga.descarga error paquete=%s (solicitud=%s)",
                paquete.id_paquete_sat, solicitud.id,
            )
