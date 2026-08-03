"""
Tests unitarios para la máquina de estados de conversación.
Cubre todos los estados y transiciones incluyendo casos de error.
"""

from models.schemas import EstadoConversacion
from services.state_machine import (
    ConversationStateMachine,
    DatosCapturados,
    SessionContext,
)

sm = ConversationStateMachine()


def _ctx(estado: EstadoConversacion, **datos_kwargs) -> SessionContext:
    """Helper para crear contextos de prueba."""
    return SessionContext(
        wa_id="521XXXXXXXXXX",
        estado=estado,
        datos=DatosCapturados(**datos_kwargs),
    )


class TestInicio:
    def test_keyword_factura_arranca(self):
        ctx = _ctx(EstadoConversacion.INICIO)
        r = sm.process(ctx, "FACTURA")
        assert r.nuevo_estado == EstadoConversacion.ESPERANDO_OPTIN
        assert "Política de Privacidad" in r.respuesta

    def test_keyword_hola_arranca(self):
        ctx = _ctx(EstadoConversacion.INICIO)
        r = sm.process(ctx, "hola")
        assert r.nuevo_estado == EstadoConversacion.ESPERANDO_OPTIN

    def test_mensaje_random_no_arranca(self):
        ctx = _ctx(EstadoConversacion.INICIO)
        r = sm.process(ctx, "qué tal el clima?")
        assert r.nuevo_estado == EstadoConversacion.INICIO
        assert "FACTURA" in r.respuesta


class TestOptIn:
    def test_si_acepta(self):
        ctx = _ctx(EstadoConversacion.ESPERANDO_OPTIN)
        r = sm.process(ctx, "SÍ")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_RFC

    def test_si_minusculas(self):
        ctx = _ctx(EstadoConversacion.ESPERANDO_OPTIN)
        r = sm.process(ctx, "si")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_RFC

    def test_rechazo_cierra(self):
        ctx = _ctx(EstadoConversacion.ESPERANDO_OPTIN)
        r = sm.process(ctx, "no")
        assert r.nuevo_estado == EstadoConversacion.CERRADA


class TestCapturaRFC:
    def test_rfc_valido_avanza(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_RFC)
        r = sm.process(ctx, "DNS010101AAA")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_RAZON_SOCIAL
        assert r.datos_actualizados.rfc == "DNS010101AAA"

    def test_rfc_invalido_permanece(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_RFC)
        r = sm.process(ctx, "INVALIDORFC")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_RFC
        assert "❌" in r.respuesta

    def test_max_intentos_error(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_RFC)
        ctx.intentos_rfc = 2  # ya lleva 2 intentos fallidos
        r = sm.process(ctx, "INVALIDO")
        assert r.nuevo_estado == EstadoConversacion.ERROR

    def test_rfc_generico_acepta(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_RFC)
        r = sm.process(ctx, "XAXX010101000")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_RAZON_SOCIAL


class TestCapturaRazonSocial:
    def test_razon_social_valida(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_RAZON_SOCIAL, rfc="DNS010101AAA")
        r = sm.process(ctx, "Distribuidora Nacional SA de CV")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_CP
        assert r.datos_actualizados.razon_social == "Distribuidora Nacional SA de CV"

    def test_razon_social_muy_corta(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_RAZON_SOCIAL)
        r = sm.process(ctx, "A")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_RAZON_SOCIAL

    def test_razon_social_trunca_300(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_RAZON_SOCIAL)
        r = sm.process(ctx, "X" * 400)
        assert len(r.datos_actualizados.razon_social) == 300


class TestCapturaCP:
    def test_cp_valido(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_CP)
        r = sm.process(ctx, "06600")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_REGIMEN

    def test_cp_invalido(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_CP)
        r = sm.process(ctx, "ABCDE")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_CP


class TestCapturaRegimen:
    def test_regimen_601(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_REGIMEN)
        r = sm.process(ctx, "601")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_USO_CFDI
        assert r.datos_actualizados.regimen_fiscal == "601"

    def test_regimen_invalido(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_REGIMEN)
        r = sm.process(ctx, "999")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_REGIMEN


class TestCapturaUsoCFDI:
    def test_uso_g03_valido(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_USO_CFDI, regimen_fiscal="601")
        r = sm.process(ctx, "G03")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_EMAIL

    def test_uso_incompatible_falla(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_USO_CFDI, regimen_fiscal="601")
        r = sm.process(ctx, "D01")  # D01 no aplica a morales (601)
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_USO_CFDI


class TestCapturaEmail:
    def test_email_valido(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_EMAIL)
        r = sm.process(ctx, "cliente@empresa.mx")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_TICKET
        assert r.datos_actualizados.email == "cliente@empresa.mx"

    def test_email_invalido(self):
        ctx = _ctx(EstadoConversacion.CAPTURA_EMAIL)
        r = sm.process(ctx, "noesuncorreo")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_EMAIL


class TestCapturaTicket:
    def test_ticket_valido_muestra_confirmacion(self):
        ctx = _ctx(
            EstadoConversacion.CAPTURA_TICKET,
            rfc="DNS010101AAA",
            razon_social="Mi Empresa SA de CV",
            codigo_postal="06600",
            regimen_fiscal="601",
            uso_cfdi="G03",
            email="test@test.mx",
        )
        r = sm.process(ctx, "TKT-12345")
        assert r.nuevo_estado == EstadoConversacion.CONFIRMACION
        assert "Resumen de tu factura" in r.respuesta
        assert "DNS010101AAA" in r.respuesta


class TestConfirmacion:
    def _ctx_confirmacion(self) -> SessionContext:
        return _ctx(
            EstadoConversacion.CONFIRMACION,
            rfc="DNS010101AAA",
            razon_social="Mi Empresa",
            codigo_postal="06600",
            regimen_fiscal="601",
            uso_cfdi="G03",
            email="x@x.mx",
            ticket_id="TKT-001",
        )

    def test_si_dispara_timbrado(self):
        ctx = self._ctx_confirmacion()
        r = sm.process(ctx, "SÍ")
        assert r.nuevo_estado == EstadoConversacion.TIMBRADO
        assert r.listo_para_timbrar is True

    def test_no_reinicia_captura(self):
        ctx = self._ctx_confirmacion()
        r = sm.process(ctx, "NO")
        assert r.nuevo_estado == EstadoConversacion.CAPTURA_RFC

    def test_respuesta_invalida_repregunta(self):
        ctx = self._ctx_confirmacion()
        r = sm.process(ctx, "quizás")
        assert r.nuevo_estado == EstadoConversacion.CONFIRMACION


class TestEstadosTerminales:
    def test_cerrada_keyword_reinicia(self):
        ctx = _ctx(EstadoConversacion.CERRADA)
        r = sm.process(ctx, "FACTURA")
        assert r.nuevo_estado == EstadoConversacion.INICIO

    def test_entrega_otro_mensaje(self):
        ctx = _ctx(EstadoConversacion.ENTREGA)
        r = sm.process(ctx, "gracias")
        assert r.nuevo_estado == EstadoConversacion.ENTREGA
        assert "FACTURA" in r.respuesta
