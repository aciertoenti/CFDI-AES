"""
Tests de _construir_fernet() (database.py) - soporte de rotacion sin
perdida de datos para las 3 llaves maestras (CSD/EFIRMA/DECLARACIONES),
reporte 186 (EFIRMA_MASTER_KEY se expuso en una salida de herramienta
durante el reporte 185, motivo real de este trabajo).

Llaves SINTETICAS generadas aqui mismo con Fernet.generate_key() - nunca
las llaves reales del .env, ni siquiera indirectamente: estos tests
llaman _construir_fernet() directamente con os.environ parcheado
(monkeypatch), nunca dependen de los objetos _fernet/_fernet_efirma/
_fernet_declaraciones ya construidos a nivel de modulo con las llaves
reales del entorno de test.
"""
import pytest
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from database import _construir_fernet

NOMBRE_VAR = "TEST_ROTACION_MASTER_KEY"


def test_sin_anterior_comportamiento_identico_a_fernet_simple(monkeypatch):
    """Sin la variable _ANTERIOR: _construir_fernet debe devolver el
    mismo comportamiento que Fernet(actual) a secas - ninguna diferencia
    cuando no hay una rotacion en curso (caso normal, la inmensa mayoria
    del tiempo)."""
    actual = Fernet.generate_key()
    monkeypatch.setenv(NOMBRE_VAR, actual.decode())
    monkeypatch.delenv(f"{NOMBRE_VAR}_ANTERIOR", raising=False)

    f = _construir_fernet(NOMBRE_VAR)
    assert isinstance(f, Fernet)
    assert not isinstance(f, MultiFernet)

    token = f.encrypt(b"contenido de prueba")
    assert f.decrypt(token) == b"contenido de prueba"


def test_con_anterior_lee_valores_cifrados_con_la_llave_anterior(monkeypatch):
    """Con _ANTERIOR presente: un valor cifrado ANTES de la rotacion
    (con la llave vieja) debe poder seguir leyendose sin perdida de
    datos - esta es la propiedad central que hace posible re-cifrar
    todas las filas sin downtime ni perder acceso a las que aun no se
    han procesado."""
    llave_vieja = Fernet.generate_key()
    llave_nueva = Fernet.generate_key()
    monkeypatch.setenv(NOMBRE_VAR, llave_nueva.decode())
    monkeypatch.setenv(f"{NOMBRE_VAR}_ANTERIOR", llave_vieja.decode())

    token_viejo = Fernet(llave_vieja).encrypt(b"dato cifrado antes de rotar")

    f = _construir_fernet(NOMBRE_VAR)
    assert isinstance(f, MultiFernet)
    assert f.decrypt(token_viejo) == b"dato cifrado antes de rotar"


def test_con_anterior_escribe_siempre_con_la_llave_actual(monkeypatch):
    """Con _ANTERIOR presente: CUALQUIER valor nuevo cifrado debe quedar
    legible con la llave NUEVA sola (sin necesitar la vieja) - confirma
    que MultiFernet.encrypt() usa la PRIMERA llave de la lista (la
    actual), nunca la anterior. Si esto fallara, la rotacion nunca
    terminaria: cada escritura nueva seguiria dependiendo de la llave
    vieja."""
    llave_vieja = Fernet.generate_key()
    llave_nueva = Fernet.generate_key()
    monkeypatch.setenv(NOMBRE_VAR, llave_nueva.decode())
    monkeypatch.setenv(f"{NOMBRE_VAR}_ANTERIOR", llave_vieja.decode())

    f = _construir_fernet(NOMBRE_VAR)
    token = f.encrypt(b"dato escrito durante la rotacion")

    # Debe descifrar con la llave nueva SOLA (sin la vieja en la lista).
    assert Fernet(llave_nueva).decrypt(token) == b"dato escrito durante la rotacion"
    # Y NO debe poder descifrarse con la llave vieja sola - confirma que
    # el cifrado nuevo no quedo atado a la llave anterior.
    with pytest.raises(InvalidToken):
        Fernet(llave_vieja).decrypt(token)


def test_llave_ajena_no_descifra(monkeypatch):
    """Aislamiento: una llave completamente ajena (ni actual ni anterior
    de esta rotacion) nunca debe poder descifrar un valor cifrado con
    _construir_fernet - mismo patron ya usado en
    test_declaraciones_anuales.py para confirmar separacion real de
    llaves entre CSD/EFIRMA/DECLARACIONES, aplicado aqui a la rotacion."""
    actual = Fernet.generate_key()
    llave_ajena = Fernet.generate_key()
    monkeypatch.setenv(NOMBRE_VAR, actual.decode())
    monkeypatch.delenv(f"{NOMBRE_VAR}_ANTERIOR", raising=False)

    f = _construir_fernet(NOMBRE_VAR)
    token = f.encrypt(b"dato protegido")

    with pytest.raises(InvalidToken):
        Fernet(llave_ajena).decrypt(token)


def test_anterior_vacio_se_trata_como_no_configurado(monkeypatch):
    """Un _ANTERIOR presente pero con string vacio (caso real: docker
    compose interpola "${VAR:-}" a "" cuando no esta en .env, ver
    docker-compose.yml) debe comportarse EXACTAMENTE igual que si la
    variable no existiera - nunca debe intentar construir un Fernet con
    una cadena vacia (eso lanzaria ValueError, no es el fail-closed
    esperado)."""
    actual = Fernet.generate_key()
    monkeypatch.setenv(NOMBRE_VAR, actual.decode())
    monkeypatch.setenv(f"{NOMBRE_VAR}_ANTERIOR", "")

    f = _construir_fernet(NOMBRE_VAR)
    assert isinstance(f, Fernet)
    assert not isinstance(f, MultiFernet)
