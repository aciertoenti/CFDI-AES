# ─── services/administracion/sat_codigos.py ──────────────────────────────────
# Clasificacion de los codigos de estatus (CodEstatus) del servicio de
# Descarga Masiva de Terceros del SAT, para el ciclo Solicita/Verifica/
# Descarga (zg55DWY).
#
# FUENTE (investigacion 09 sep 2026):
#   - Especificacion publica del SAT ("Servicio Web de Descarga Masiva de
#     Terceros" / "Consulta y recuperacion de comprobantes").
#   - Codigo de cfdiclient 1.6.3 (no trae ningun mapeo de codigos: solo
#     expone CodEstatus/Mensaje como strings crudos del XML).
#   - Contraste con librerias de terceros equivalentes en otros lenguajes.
#
# ESTE MODULO ES SOLO PARA LOGICA (decidir: reintentar o no, bloquear el
# periodo o no). NO es para redaccion de cara al usuario: el texto exacto
# que devuelve el SAT varia entre versiones del WS y no se puede confirmar
# de forma confiable sin una llamada real, asi que para MOSTRARLE algo al
# usuario se prefiere SIEMPRE el 'mensaje_sat' verbatim que quedo guardado
# en solicitudes_descarga. Las descripciones de aqui son notas internas.
#
# fail-safe: un CodEstatus que el SAT devuelva y que NO este en el
# diccionario se trata como NO reintentable (ver clasificar_cod_estatus).
# Nunca asumir que es seguro reintentar algo desconocido - primero se
# investiga y se agrega aqui.
# ─────────────────────────────────────────────────────────────────────────────
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import SolicitudDescarga


# tipo:
#   exito              -> el SAT acepto (o completo) la operacion
#   exito_vacio        -> completo sin resultados (rango sin CFDI); no es error
#   no_autorizado      -> este RFC no esta autorizado por el titular a descargar
#   bloqueo_permanente -> "se han agotado las solicitudes de por vida" para ese
#                         (RFC, periodo, tipo); no reintentar nunca ese periodo
#   rango_excede_tope  -> el rango tiene demasiados CFDI (>1,000,000); hay que
#                         partirlo en sub-periodos y volver a solicitar
#   duplicada          -> ya hay una solicitud vigente con los mismos criterios;
#                         reusar / esperar la previa en vez de crear otra
#   error_interno      -> fallo transitorio del lado SAT; backoff y reintentar
#   auth_error         -> problema de sello/token/usuario en la peticion; se
#                         puede reintentar tras re-firmar / re-autenticar
#   efirma_invalida    -> certificado revocado, caduco o invalido; requiere
#                         renovar la e.firma (PUT /admin/efirmas/{rfc_titular})
#
# reintentable:
#   None            -> no aplica (es un caso de exito)
#   True            -> reintentar el mismo paso (con backoff)
#   False           -> NO reintentar; requiere accion humana o cambio de input
#   "reusar_previa" -> no crear una solicitud nueva; enganchar con la existente
CODIGOS_SAT = {
    "5000": {"tipo": "exito", "reintentable": None,
             "desc": "Solicitud recibida con exito."},
    "5001": {"tipo": "no_autorizado", "reintentable": False,
             "desc": "Tercero no autorizado por el contribuyente titular a descargar."},
    "5002": {"tipo": "bloqueo_permanente", "reintentable": False,
             "desc": "Se han agotado las solicitudes de por vida para ese RFC / periodo / tipo."},
    "5003": {"tipo": "rango_excede_tope", "reintentable": False,
             "desc": "El rango de fechas excede el tope maximo de elementos por solicitud."},
    "5004": {"tipo": "exito_vacio", "reintentable": None,
             "desc": "No se encontro la informacion: el rango no tiene CFDI. Exito sin resultados."},
    "5005": {"tipo": "duplicada", "reintentable": "reusar_previa",
             "desc": "Ya existe una solicitud registrada con los mismos parametros."},
    "5006": {"tipo": "error_interno", "reintentable": True,
             "desc": "Error interno en el proceso del SAT. Transitorio."},
    "300": {"tipo": "auth_error", "reintentable": True,
            "desc": "Usuario no valido / peticion mal formada."},
    "302": {"tipo": "auth_error", "reintentable": True,
            "desc": "Sello mal formado o invalido."},
    "303": {"tipo": "auth_error", "reintentable": True,
            "desc": "El sello no corresponde con el RFC solicitante."},
    "304": {"tipo": "efirma_invalida", "reintentable": False,
            "desc": "Certificado revocado o caduco. Renovar la e.firma."},
    "305": {"tipo": "efirma_invalida", "reintentable": False,
            "desc": "Certificado invalido. Renovar la e.firma."},
}

# Codigos ante los que NO tiene sentido reintentar el mismo paso: requieren
# accion humana o un cambio de input. Lo usa es_bloqueo_permanente().
NO_REINTENTAR = {"5001", "5002", "5003", "304", "305"}

# Subconjunto de NO_REINTENTAR que ademas deja inservible un PERIODO
# concreto (RFC, tipo, rango de fechas). Es lo unico que puede comparar la
# guarda de pre-vuelo, que hace match por fecha_desde/fecha_hasta exactos.
#   5001 tercero no autorizado, 5002 agotado "de por vida", 5003 tope de
#   elementos -> todos atados a ese periodo/criterios.
# 304/305 (e.firma revocada/caduca/invalida) quedan FUERA a proposito: no
# son un bloqueo de ese periodo, sino de la e.firma para CUALQUIER
# solicitud - se detectan por el estado/vigencia de la propia e.firma, no
# comparando contra solicitudes pasadas.
BLOQUEO_POR_PERIODO = {"5001", "5002", "5003"}

# CodigoEstadoSolicitud que, dentro de un EstadoSolicitud=5, significa "la
# consulta termino bien pero NO hay CFDI en el rango" - NO es un rechazo.
# Descubierto en la corrida REAL de Fase 2 (09 sep 2026, RAHP7112093H0,
# solicitud 94e68a70-...): el SAT NO usa EstadoSolicitud=3+NumeroCFDIs=0
# para "vacio" (lo asumido en Fase 1), usa EstadoSolicitud=5 +
# CodigoEstadoSolicitud=5004. Mismo criterio de diseno que 5002: el dato
# crudo (estado_solicitud) se guarda tal cual vino del SAT; la
# interpretacion "esto no es un error" vive aqui, en la capa que clasifica.
SIN_RESULTADOS = {"5004"}

# Default fail-safe para un CodEstatus no mapeado: desconocido y NO
# reintentable, hasta que alguien lo investigue y lo agregue a CODIGOS_SAT.
_DEFAULT_DESCONOCIDO = {
    "tipo": "desconocido",
    "reintentable": False,
    "desc": "CodEstatus no mapeado. Se trata como NO reintentable por seguridad; investigar y agregar a CODIGOS_SAT.",
}


def clasificar_cod_estatus(cod_estatus: str) -> dict:
    """Devuelve la entrada de CODIGOS_SAT para 'cod_estatus'.

    Si el codigo no esta mapeado (o viene vacio/None), devuelve el default
    fail-safe: tipo='desconocido', reintentable=False. Nunca se asume que
    un codigo desconocido es seguro de reintentar.

    El dict devuelto es una copia, para que quien lo reciba no pueda mutar
    la tabla de referencia por accidente.
    """
    entrada = CODIGOS_SAT.get((cod_estatus or "").strip())
    return dict(entrada) if entrada is not None else dict(_DEFAULT_DESCONOCIDO)


def es_bloqueo_permanente(cod_estatus: str) -> bool:
    """True si el codigo deja el periodo (RFC, tipo, rango) inservible para
    reintentos - el caller debe tratarlo como terminal y NO volver a
    solicitar ese mismo periodo."""
    return (cod_estatus or "").strip() in NO_REINTENTAR


def es_sin_resultados(estado_solicitud, codigo_estado_solicitud) -> bool:
    """True si (estado_solicitud, codigo_estado_solicitud) del SAT
    representan "consulta exitosa pero SIN CFDI en el rango", no un rechazo.

    Es un EstadoSolicitud=5 con CodigoEstadoSolicitud en SIN_RESULTADOS
    ("5004"). La capa de presentacion debe mostrarlo como "no hay CFDI en
    ese periodo", NO como error/rechazo. El estado_solicitud crudo (5) se
    conserva tal cual lo devolvio el SAT; esta funcion es la que lo
    reinterpreta, igual que es_bloqueo_permanente() hace con el 5002."""
    return (
        str(estado_solicitud).strip() == "5"
        and (codigo_estado_solicitud or "").strip() in SIN_RESULTADOS
    )


async def verificar_bloqueo_previo(
    db: AsyncSession,
    negocio_id: int,
    efirma_id: int,
    tipo: str,
    fecha_desde,
    fecha_hasta,
) -> Optional[SolicitudDescarga]:
    """Guarda de pre-vuelo antes de disparar un SolicitaDescarga nuevo.

    Busca en solicitudes_descarga una fila con los MISMOS
    (efirma_id, tipo, fecha_desde, fecha_hasta) cuyo cod_estatus este en
    BLOQUEO_POR_PERIODO (5001 / 5002 / 5003). Si existe, la devuelve para
    que el caller rechace con 409 mostrando su mensaje_sat verbatim y la
    fecha del intento previo (created_at), sin gastar otra "solicitud de
    por vida" contra un periodo ya bloqueado.

    Deliberadamente NO mira 304/305 (e.firma revocada/caduca/invalida):
    eso invalida la e.firma para CUALQUIER solicitud, no solo este rango de
    fechas, y se verifica por el estado/vigencia de la propia e.firma, no
    comparando contra el historial de solicitudes por (fecha_desde,
    fecha_hasta). Mezclar ambos en esta guarda confundiria dos problemas
    distintos.

    negocio_id se incluye en el filtro como defensa en profundidad (la
    e.firma ya pertenece a un negocio, pero no se confia en un solo
    predicado). Devuelve la fila mas reciente si hubiera varias; None si no
    hay ninguna -> es seguro proceder.
    """
    stmt = (
        select(SolicitudDescarga)
        .where(
            SolicitudDescarga.negocio_id == negocio_id,
            SolicitudDescarga.efirma_id == efirma_id,
            SolicitudDescarga.tipo == tipo,
            SolicitudDescarga.fecha_desde == fecha_desde,
            SolicitudDescarga.fecha_hasta == fecha_hasta,
            SolicitudDescarga.cod_estatus.in_(tuple(BLOQUEO_POR_PERIODO)),
        )
        .order_by(SolicitudDescarga.created_at.desc())
        .limit(1)
    )
    return await db.scalar(stmt)
