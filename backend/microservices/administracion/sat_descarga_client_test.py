# ─── services/administracion/sat_descarga_client_test.py ─────────────────────
# Pruebas de Fase 1 del cliente de descarga masiva (zg55DWY): SIN una sola
# llamada real al SAT. Se monkeypatchean los 4 puntos de contacto con
# cfdiclient (_obtener_token + las 3 clases Solicita/Verifica/Descarga) y la
# subida a MinIO (subir_zip), inyectando las respuestas sinteticas basadas en
# los dicts de retorno ya confirmados en la investigacion.
#
# Corre contra la BD real de administracion (cfdi_admin) - crea una e.firma de
# prueba (RFC XAXX010101000, negocio_id 999999), ejercita los 5 casos y borra
# TODO lo de prueba al final.
#
# Uso (dentro del contenedor administracion):
#   python sat_descarga_client_test.py
# ─────────────────────────────────────────────────────────────────────────────
import asyncio
import base64
import sys
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import sat_descarga_client as mod
from database import AsyncSessionLocal, Efirma, PaqueteDescarga, SolicitudDescarga
from sat_codigos import es_sin_resultados
from sat_descarga_client import (
    BloqueoPrevioError,
    descargar_paquetes,
    solicitar_descarga,
    tick_verificar_solicitudes,
)
from sqlalchemy import delete, select

RFC = "XAXX010101000"
NEGOCIO_ID = 999999

FAKE_ZIP = b"PK\x03\x04-contenido-zip-falso-para-la-prueba"
FAKE_ZIP_B64 = base64.b64encode(FAKE_ZIP).decode()

_fallos = []


def check(label, got, exp):
    ok = got == exp
    print(("PASS " if ok else "FAIL "), label, "->", repr(got), "" if ok else f"(esperado {exp!r})")
    if not ok:
        _fallos.append(label)
    return ok


# ─── Fakes de cfdiclient ─────────────────────────────────────────────────────
class _FakeSolicita:
    mock = MagicMock()

    def __init__(self, fiel):
        pass

    def solicitar_descarga(self, **kw):
        return _FakeSolicita.mock(**kw)


class _FakeVerifica:
    mock = MagicMock()

    def __init__(self, fiel):
        pass

    def verificar_descarga(self, *a):
        return _FakeVerifica.mock(*a)


class _FakeDescarga:
    mock = MagicMock()

    def __init__(self, fiel):
        pass

    def descargar_paquete(self, *a):
        return _FakeDescarga.mock(*a)


def _reset_mocks():
    for m in (_FakeSolicita.mock, _FakeVerifica.mock, _FakeDescarga.mock):
        m.reset_mock(return_value=True, side_effect=True)
    mod._obtener_token.reset_mock(return_value=True, side_effect=True)
    mod._obtener_token.return_value = "FAKE_TOKEN"
    mod.subir_zip.reset_mock(return_value=True, side_effect=True)
    mod.subir_zip.side_effect = lambda key, data: key


# ─── Setup / teardown de datos de prueba ─────────────────────────────────────
async def _limpiar(db):
    sub = select(SolicitudDescarga.id).where(SolicitudDescarga.negocio_id == NEGOCIO_ID)
    await db.execute(delete(PaqueteDescarga).where(PaqueteDescarga.solicitud_id.in_(sub)))
    await db.execute(delete(SolicitudDescarga).where(SolicitudDescarga.negocio_id == NEGOCIO_ID))
    await db.execute(delete(Efirma).where(Efirma.rfc_titular == RFC, Efirma.negocio_id == NEGOCIO_ID))
    await db.commit()


async def _crear_efirma(db) -> Efirma:
    # construir_fiel esta parcheado -> estos valores nunca se usan como cripto.
    e = Efirma(
        rfc_titular=RFC,
        negocio_id=NEGOCIO_ID,
        cert_base64="ZmFrZQ==",
        key_base64_cifrado="ZmFrZQ==",
        password_cifrado="ZmFrZQ==",
        vigencia_desde=date(2024, 1, 1),
        vigencia_hasta=date(2099, 1, 1),
        estado="Activo",
        consentimiento_at=None,
        consentimiento_por_rfc=None,
        creado_por_rfc="TESTRFC",
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return e


# ─── Casos ──────────────────────────────────────────────────────────────────
async def caso_1(db, efirma):
    print("\n=== CASO 1: 5000 -> Aceptada -> tick -> Terminada 0 paquetes (5004) ===")
    _reset_mocks()
    _FakeSolicita.mock.return_value = {
        "id_solicitud": "11111111-1111-1111-1111-111111111111",
        "cod_estatus": "5000",
        "mensaje": "Solicitud Aceptada",
    }
    fila = await solicitar_descarga(
        fiel=object(), negocio_id=NEGOCIO_ID, efirma_id=efirma.id, rfc_titular=RFC,
        tipo="emitidas", fecha_desde=date(2025, 1, 1), fecha_hasta=date(2025, 1, 31),
        solicitado_por_rfc="TESTRFC", db=db,
    )
    check("solicitud.estado_solicitud (Aceptada)", fila.estado_solicitud, 1)
    check("solicitud.cod_estatus", fila.cod_estatus, "5000")
    check("solicitud.id_solicitud_sat", fila.id_solicitud_sat, "11111111-1111-1111-1111-111111111111")
    check("solicitud.mensaje_sat verbatim", fila.mensaje_sat, "Solicitud Aceptada")

    _FakeVerifica.mock.return_value = {
        "cod_estatus": "5000", "estado_solicitud": "3", "codigo_estado_solicitud": "5004",
        "numero_cfdis": "0", "mensaje": "Solicitud Aceptada", "paquetes": [],
    }
    terminadas = await tick_verificar_solicitudes(db)
    ids = [t.id for t in terminadas]
    check("tick devuelve la solicitud como terminada", fila.id in ids, True)
    await db.refresh(fila)
    check("solicitud.estado_solicitud (Terminada)", fila.estado_solicitud, 3)
    check("solicitud.numero_cfdis", fila.numero_cfdis, 0)
    n_paq = await db.scalar(
        select(mod.PaqueteDescarga.id).where(mod.PaqueteDescarga.solicitud_id == fila.id)
    )
    check("no se crearon paquetes (rango vacio)", n_paq, None)

    await descargar_paquetes(object(), fila, db)
    check("descargar_paquetes no subio nada (0 paquetes)", mod.subir_zip.call_count, 0)


async def caso_2(db, efirma):
    print("\n=== CASO 2: 5000 -> tick -> Terminada CON 1 paquete -> descarga -> MinIO ===")
    _reset_mocks()
    _FakeSolicita.mock.return_value = {
        "id_solicitud": "22222222-2222-2222-2222-222222222222",
        "cod_estatus": "5000", "mensaje": "Solicitud Aceptada",
    }
    fila = await solicitar_descarga(
        fiel=object(), negocio_id=NEGOCIO_ID, efirma_id=efirma.id, rfc_titular=RFC,
        tipo="emitidas", fecha_desde=date(2025, 2, 1), fecha_hasta=date(2025, 2, 28),
        solicitado_por_rfc="TESTRFC", db=db,
    )
    id_paquete = "22222222-2222-2222-2222-222222222222_01"
    _FakeVerifica.mock.return_value = {
        "cod_estatus": "5000", "estado_solicitud": "3", "codigo_estado_solicitud": "5000",
        "numero_cfdis": "5", "mensaje": "Solicitud Aceptada", "paquetes": [id_paquete],
    }
    terminadas = await tick_verificar_solicitudes(db)
    check("tick devuelve terminada", fila.id in [t.id for t in terminadas], True)
    await db.refresh(fila)
    check("solicitud.numero_cfdis", fila.numero_cfdis, 5)
    paquetes = list(await db.scalars(
        select(PaqueteDescarga).where(PaqueteDescarga.solicitud_id == fila.id)
    ))
    check("1 paquete creado", len(paquetes), 1)
    check("paquete.descargado inicial", paquetes[0].descargado, False)

    _FakeDescarga.mock.return_value = {
        "cod_estatus": "5000", "mensaje": "", "paquete_b64": FAKE_ZIP_B64,
    }
    await descargar_paquetes(object(), fila, db)
    check("subir_zip llamado 1 vez", mod.subir_zip.call_count, 1)
    args = mod.subir_zip.call_args[0]
    key_ok = args[0].endswith(f"{id_paquete}.zip") and fila.id_solicitud_sat in args[0]
    check("object_key contiene id_solicitud_sat + id_paquete", key_ok, True)
    check("subir_zip recibio los bytes del zip decodificado", args[1], FAKE_ZIP)
    p = (await db.scalars(
        select(PaqueteDescarga).where(PaqueteDescarga.solicitud_id == fila.id)
    )).one()
    check("paquete.descargado", p.descargado, True)
    check("paquete.ruta_almacenamiento", p.ruta_almacenamiento, args[0])


async def caso_3(db, efirma):
    print("\n=== CASO 3: 5002 (bloqueo permanente) -> persiste, NO se reintenta ===")
    _reset_mocks()
    _FakeSolicita.mock.return_value = {
        "id_solicitud": None, "cod_estatus": "5002",
        "mensaje": "Se han agotado las solicitudes de por vida",
    }
    fila = await solicitar_descarga(
        fiel=object(), negocio_id=NEGOCIO_ID, efirma_id=efirma.id, rfc_titular=RFC,
        tipo="emitidas", fecha_desde=date(2025, 3, 1), fecha_hasta=date(2025, 3, 31),
        solicitado_por_rfc="TESTRFC", db=db,
    )
    check("solicitud.estado_solicitud (Error)", fila.estado_solicitud, 4)
    check("solicitud.cod_estatus", fila.cod_estatus, "5002")
    check("solicitud.id_solicitud_sat sigue None", fila.id_solicitud_sat, None)
    check("solicitud.mensaje_sat verbatim", fila.mensaje_sat,
          "Se han agotado las solicitudes de por vida")
    check("SolicitaDescarga llamado 1 sola vez (one-shot, sin retry)",
          _FakeSolicita.mock.call_count, 1)
    return fila


async def caso_4(db, efirma):
    print("\n=== CASO 4: guarda de pre-vuelo -> 2da solicitud MISMOS params -> rechazo LOCAL ===")
    _reset_mocks()
    _FakeSolicita.mock.return_value = {"id_solicitud": "x", "cod_estatus": "5000", "mensaje": "x"}
    lanzo = False
    try:
        await solicitar_descarga(
            fiel=object(), negocio_id=NEGOCIO_ID, efirma_id=efirma.id, rfc_titular=RFC,
            tipo="emitidas", fecha_desde=date(2025, 3, 1), fecha_hasta=date(2025, 3, 31),
            solicitado_por_rfc="TESTRFC", db=db,
        )
    except BloqueoPrevioError as e:
        lanzo = True
        check("BloqueoPrevioError.solicitud_previa.cod_estatus", e.solicitud_previa.cod_estatus, "5002")
    check("se lanzo BloqueoPrevioError", lanzo, True)
    check("SolicitaDescarga NUNCA fue llamado (rechazo local, sin tocar el SAT)",
          _FakeSolicita.mock.call_count, 0)


async def caso_5(db, efirma):
    print("\n=== CASO 5: token invalido (estado 0) a mitad del tick -> retry token nuevo, NO falla ===")
    _reset_mocks()
    _FakeSolicita.mock.return_value = {
        "id_solicitud": "55555555-5555-5555-5555-555555555555",
        "cod_estatus": "5000", "mensaje": "Solicitud Aceptada",
    }
    fila = await solicitar_descarga(
        fiel=object(), negocio_id=NEGOCIO_ID, efirma_id=efirma.id, rfc_titular=RFC,
        tipo="emitidas", fecha_desde=date(2025, 5, 1), fecha_hasta=date(2025, 5, 31),
        solicitado_por_rfc="TESTRFC", db=db,
    )
    # el conteo de tokens que nos importa es el del TICK: reset tras la solicitud.
    mod._obtener_token.reset_mock(return_value=True, side_effect=True)
    mod._obtener_token.return_value = "FAKE_TOKEN"
    _FakeVerifica.mock.side_effect = [
        {"cod_estatus": "5000", "estado_solicitud": "0", "codigo_estado_solicitud": "5000",
         "numero_cfdis": None, "mensaje": "Token invalido o expirado", "paquetes": []},
        {"cod_estatus": "5000", "estado_solicitud": "2", "codigo_estado_solicitud": "5000",
         "numero_cfdis": None, "mensaje": "Solicitud en proceso", "paquetes": []},
    ]
    terminadas = await tick_verificar_solicitudes(db)
    check("Verifica llamado 2 veces (retry tras estado 0)", _FakeVerifica.mock.call_count, 2)
    check("_obtener_token llamado 2 veces (token nuevo en el retry)", mod._obtener_token.call_count, 2)
    await db.refresh(fila)
    check("solicitud NO marcada terminal (estado 2, sigue en vuelo)", fila.estado_solicitud, 2)
    check("solicitud NO en la lista de terminadas", fila.id in [t.id for t in terminadas], False)


async def caso_6(db, efirma):
    print("\n=== CASO 6: tick -> EstadoSolicitud=5 + CodigoEstadoSolicitud=5004 = SIN RESULTADOS (real Fase 2) ===")
    _reset_mocks()
    _FakeSolicita.mock.return_value = {
        "id_solicitud": "66666666-6666-6666-6666-666666666666",
        "cod_estatus": "5000", "mensaje": "Solicitud Aceptada",
    }
    fila = await solicitar_descarga(
        fiel=object(), negocio_id=NEGOCIO_ID, efirma_id=efirma.id, rfc_titular=RFC,
        tipo="emitidas", fecha_desde=date(2025, 6, 1), fecha_hasta=date(2025, 6, 1),
        solicitado_por_rfc="TESTRFC", db=db,
    )
    # Respuesta EXACTA que devolvio el SAT real el 09 sep 2026 para la
    # solicitud 94e68a70-...: estado 5, codigo 5004, 0 CFDIs, mensaje generico.
    _FakeVerifica.mock.return_value = {
        "cod_estatus": "5000", "estado_solicitud": "5", "codigo_estado_solicitud": "5004",
        "numero_cfdis": "0", "mensaje": "Solicitud Aceptada", "paquetes": [],
    }
    terminadas = await tick_verificar_solicitudes(db)
    await db.refresh(fila)
    check("estado_solicitud CRUDO del SAT preservado (5)", fila.estado_solicitud, 5)
    check("codigo_estado_solicitud persistido", fila.codigo_estado_solicitud, "5004")
    check("numero_cfdis explicito a 0 (no NULL)", fila.numero_cfdis, 0)
    check("es_sin_resultados(5, '5004') == True", es_sin_resultados(5, "5004"), True)
    check("NO cuenta como terminada (no hay nada que descargar)",
          fila.id in [t.id for t in terminadas], False)
    n_paq = await db.scalar(
        select(mod.PaqueteDescarga.id).where(mod.PaqueteDescarga.solicitud_id == fila.id)
    )
    check("sin paquetes", n_paq, None)

    print("  -- sub-caso: estado 5 SIN 5004 = rechazo genuino, numero_cfdis NO se toca --")
    _reset_mocks()
    _FakeSolicita.mock.return_value = {
        "id_solicitud": "66666666-6666-6666-6666-66666666aaaa",
        "cod_estatus": "5000", "mensaje": "Solicitud Aceptada",
    }
    fila2 = await solicitar_descarga(
        fiel=object(), negocio_id=NEGOCIO_ID, efirma_id=efirma.id, rfc_titular=RFC,
        tipo="emitidas", fecha_desde=date(2025, 6, 2), fecha_hasta=date(2025, 6, 2),
        solicitado_por_rfc="TESTRFC", db=db,
    )
    _FakeVerifica.mock.return_value = {
        "cod_estatus": "5000", "estado_solicitud": "5", "codigo_estado_solicitud": "5999",
        "numero_cfdis": None, "mensaje": "Solicitud Rechazada", "paquetes": [],
    }
    await tick_verificar_solicitudes(db)
    await db.refresh(fila2)
    check("rechazo genuino: estado 5", fila2.estado_solicitud, 5)
    check("rechazo genuino: codigo_estado_solicitud persistido (5999)", fila2.codigo_estado_solicitud, "5999")
    check("rechazo genuino: numero_cfdis sigue NULL (no es 'sin resultados')", fila2.numero_cfdis, None)
    check("es_sin_resultados(5, '5999') == False", es_sin_resultados(5, "5999"), False)


# ─── Runner ─────────────────────────────────────────────────────────────────
async def main():
    # patch
    orig = {
        "_obtener_token": mod._obtener_token,
        "subir_zip": mod.subir_zip,
        "construir_fiel": mod.construir_fiel,
        "SolicitaDescargaEmitidos": mod.SolicitaDescargaEmitidos,
        "SolicitaDescargaRecibidos": mod.SolicitaDescargaRecibidos,
        "VerificaSolicitudDescarga": mod.VerificaSolicitudDescarga,
        "DescargaMasiva": mod.DescargaMasiva,
    }
    mod._obtener_token = AsyncMock(return_value="FAKE_TOKEN")
    mod.subir_zip = MagicMock(side_effect=lambda key, data: key)
    mod.construir_fiel = MagicMock(side_effect=lambda efirma: object())
    mod.SolicitaDescargaEmitidos = _FakeSolicita
    mod.SolicitaDescargaRecibidos = _FakeSolicita
    mod.VerificaSolicitudDescarga = _FakeVerifica
    mod.DescargaMasiva = _FakeDescarga

    async with AsyncSessionLocal() as db:
        try:
            await _limpiar(db)
            efirma = await _crear_efirma(db)
            await caso_1(db, efirma)
            await caso_2(db, efirma)
            await caso_3(db, efirma)
            await caso_4(db, efirma)
            await caso_5(db, efirma)
            await caso_6(db, efirma)
        finally:
            await _limpiar(db)
            n_e = await db.scalar(select(Efirma.id).where(Efirma.rfc_titular == RFC, Efirma.negocio_id == NEGOCIO_ID))
            n_s = await db.scalar(select(SolicitudDescarga.id).where(SolicitudDescarga.negocio_id == NEGOCIO_ID))
            print("\n=== LIMPIEZA ===")
            check("0 e.firmas de prueba tras limpiar", n_e, None)
            check("0 solicitudes de prueba tras limpiar", n_s, None)
            for k, v in orig.items():
                setattr(mod, k, v)

    print("\n" + ("=" * 60))
    if _fallos:
        print(f"RESULTADO: {len(_fallos)} FALLO(S) -> {_fallos}")
        sys.exit(1)
    print("RESULTADO: TODOS LOS CASOS PASAN")


if __name__ == "__main__":
    asyncio.run(main())
