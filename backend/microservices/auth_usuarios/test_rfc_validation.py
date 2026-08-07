import unittest

from rfc_validation import es_rfc_persona_fisica_valido

# RFC real encontrado por fuerza bruta contra el algoritmo de satcfdi
# (satcfdi.models.rfc.RFC(...).is_valid()) - digito verificador confirmado
# correcto, no inventado a mano.
RFC_VALIDO = "PEGJ800101003"


class TestValidacionRFC(unittest.TestCase):
    def test_rfc_con_digito_verificador_correcto_se_acepta(self):
        self.assertTrue(es_rfc_persona_fisica_valido(RFC_VALIDO))

    def test_mismo_rfc_con_ultimo_caracter_alterado_se_rechaza(self):
        alterado = RFC_VALIDO[:-1] + ("4" if RFC_VALIDO[-1] != "4" else "5")
        self.assertFalse(es_rfc_persona_fisica_valido(alterado))

    def test_rfc_con_longitud_incorrecta_se_rechaza(self):
        self.assertFalse(es_rfc_persona_fisica_valido(RFC_VALIDO[:-1]))


if __name__ == "__main__":
    unittest.main()
