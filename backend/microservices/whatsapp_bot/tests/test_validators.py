"""
Tests unitarios para el módulo de validación fiscal.
Cubre: RFC, CP, Régimen Fiscal, Uso CFDI, compatibilidad régimen-uso.
"""

from services.fiscal_validator import (
    validate_codigo_postal,
    validate_rfc,
    validate_regimen_fiscal,
    validate_uso_cfdi,
    validate_datos_fiscales,
)


class TestValidarRFC:
    def test_rfc_moral_valido(self):
        r = validate_rfc("DNS010101AAA")
        assert r.valid is True
        assert r.normalized == "DNS010101AAA"

    def test_rfc_fisica_valido(self):
        r = validate_rfc("GOHJ800101AA1")
        assert r.valid is True

    def test_rfc_generico_publico(self):
        r = validate_rfc("XAXX010101000")
        assert r.valid is True

    def test_rfc_generico_extranjero(self):
        r = validate_rfc("XEXX010101000")
        assert r.valid is True

    def test_rfc_normaliza_minusculas(self):
        r = validate_rfc("dns010101aaa")
        assert r.valid is True
        assert r.normalized == "DNS010101AAA"

    def test_rfc_normaliza_espacios(self):
        r = validate_rfc("  DNS010101AAA  ")
        assert r.valid is True

    def test_rfc_muy_corto(self):
        r = validate_rfc("DNS0101")
        assert r.valid is False
        assert "12 caracteres" in r.error

    def test_rfc_mes_invalido(self):
        r = validate_rfc("DNS991301AAA")  # mes 13 no existe
        assert r.valid is False

    def test_rfc_dia_invalido(self):
        r = validate_rfc("DNS990132AAA")  # día 32 no existe
        assert r.valid is False

    def test_rfc_caracteres_invalidos(self):
        r = validate_rfc("123010101AAA")  # empieza con números
        assert r.valid is False


class TestValidarCP:
    def test_cp_valido(self):
        r = validate_codigo_postal("06600")
        assert r.valid is True
        assert r.normalized == "06600"

    def test_cp_cuatro_digitos_normaliza(self):
        # CP con cero inicial omitido
        r = validate_codigo_postal("6600")
        assert r.valid is True
        assert r.normalized == "06600"

    def test_cp_letras(self):
        r = validate_codigo_postal("A6600")
        assert r.valid is False

    def test_cp_demasiado_bajo(self):
        r = validate_codigo_postal("00500")  # < 1000 fuera de rango
        assert r.valid is False

    def test_cp_seis_digitos(self):
        r = validate_codigo_postal("066001")
        assert r.valid is False


class TestValidarRegimenFiscal:
    def test_regimen_601_valido(self):
        r = validate_regimen_fiscal("601")
        assert r.valid is True
        assert r.normalized == "601"

    def test_regimen_626_valido(self):
        r = validate_regimen_fiscal("626")
        assert r.valid is True

    def test_regimen_invalido(self):
        r = validate_regimen_fiscal("999")
        assert r.valid is False
        assert "no reconocido" in r.error

    def test_regimen_con_espacios(self):
        r = validate_regimen_fiscal("  601  ")
        assert r.valid is True


class TestValidarUsoCFDI:
    def test_uso_g03_valido(self):
        r = validate_uso_cfdi("G03")
        assert r.valid is True
        assert r.normalized == "G03"

    def test_uso_minusculas_normaliza(self):
        r = validate_uso_cfdi("g03")
        assert r.valid is True
        assert r.normalized == "G03"

    def test_uso_invalido(self):
        r = validate_uso_cfdi("ZZZ")
        assert r.valid is False

    def test_uso_d01_fisica_compatible(self):
        # D01 solo aplica a personas físicas
        r = validate_uso_cfdi("D01", regimen_fiscal="612")
        assert r.valid is True

    def test_uso_d01_moral_incompatible(self):
        # D01 no aplica a personas morales
        r = validate_uso_cfdi("D01", regimen_fiscal="601")
        assert r.valid is False
        assert "personas morales" in r.error

    def test_uso_g03_moral_compatible(self):
        r = validate_uso_cfdi("G03", regimen_fiscal="601")
        assert r.valid is True

    def test_uso_sin_regimen(self):
        # Sin régimen no verifica compatibilidad
        r = validate_uso_cfdi("D01")
        assert r.valid is True

    def test_uso_g03_regimen_616_invalido(self):
        # Caso real que causó CFDI40161 (folio previo a A-0041, ver zg41BYk):
        # G03 no aplica al régimen 616 (Sin obligaciones fiscales).
        r = validate_uso_cfdi("G03", regimen_fiscal="616")
        assert r.valid is False
        assert "616" in r.error

    def test_uso_g03_regimen_625_valido(self):
        # G03 + 625 SÍ es válido - timbró en producción (folio W-0007).
        r = validate_uso_cfdi("G03", regimen_fiscal="625")
        assert r.valid is True

    def test_uso_s01_regimen_616_valido(self):
        # S01 acepta 616 - fue el reintento exitoso (folio A-0041).
        r = validate_uso_cfdi("S01", regimen_fiscal="616")
        assert r.valid is True


class TestValidacionCompuesta:
    def test_todos_validos(self):
        resultado = validate_datos_fiscales(
            rfc="DNS010101AAA",
            codigo_postal="06600",
            regimen_fiscal="601",
            uso_cfdi="G03",
        )
        assert all(v.valid for v in resultado.values())

    def test_rfc_invalido_en_compuesto(self):
        resultado = validate_datos_fiscales(
            rfc="INVALIDO",
            codigo_postal="06600",
            regimen_fiscal="601",
            uso_cfdi="G03",
        )
        assert resultado["rfc"].valid is False
        assert resultado["codigo_postal"].valid is True
