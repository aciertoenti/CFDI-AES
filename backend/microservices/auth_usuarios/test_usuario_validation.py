import unittest

from usuario_validation import es_usuario_valido


class TestValidacionUsuario(unittest.TestCase):
    def test_valido_en_limite_corto_6_caracteres_se_acepta(self):
        self.assertTrue(es_usuario_valido("ABC123"))

    def test_valido_en_limite_largo_10_caracteres_se_acepta(self):
        self.assertTrue(es_usuario_valido("ABCDEFGH12"))

    def test_invalido_por_empezar_con_numero_se_rechaza(self):
        self.assertFalse(es_usuario_valido("1ABCDE"))

    def test_invalido_por_caracter_no_permitido_espacio_se_rechaza(self):
        self.assertFalse(es_usuario_valido("AB CDE"))

    def test_invalido_por_caracter_no_permitido_arroba_se_rechaza(self):
        self.assertFalse(es_usuario_valido("AB@CDE"))

    def test_invalido_por_longitud_menor_a_6_se_rechaza(self):
        self.assertFalse(es_usuario_valido("ABC12"))

    def test_invalido_por_longitud_mayor_a_10_se_rechaza(self):
        self.assertFalse(es_usuario_valido("ABCDEFGHIJ1"))

    def test_guion_bajo_permitido_en_el_resto_se_acepta(self):
        self.assertTrue(es_usuario_valido("AB_12_CD"))

    def test_minusculas_se_normalizan_a_mayusculas_antes_de_validar(self):
        self.assertTrue(es_usuario_valido("abc123"))


if __name__ == "__main__":
    unittest.main()
