import unittest

from auth_utils import normalizar_email_opcional, obtener_email_seguro


class TestAuthUtils(unittest.TestCase):
    def test_email_vacio_se_reemplaza_por_placeholder(self):
        self.assertEqual(normalizar_email_opcional(""), "sin-email@local.dev")
        self.assertEqual(normalizar_email_opcional("   "), "sin-email@local.dev")

    def test_email_valido_se_conserva(self):
        self.assertEqual(normalizar_email_opcional("usuario@empresa.mx"), "usuario@empresa.mx")

    def test_obtener_email_seguro_usa_placeholder_en_desarrollo(self):
        self.assertEqual(obtener_email_seguro(""), "sin-email@local.dev")
        self.assertEqual(obtener_email_seguro("usuario@empresa.mx"), "usuario@empresa.mx")


if __name__ == "__main__":
    unittest.main()
