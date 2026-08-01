"""
Configuración de pytest para el microservicio WhatsApp Bot.
Define variables de entorno de prueba para que Settings no falle.
"""
import os
import pytest

# ─── Variables de entorno para tests ─────────────────────────────────────────
# Se establecen antes de que cualquier módulo importe settings.

os.environ.setdefault("WHATSAPP_TOKEN", "test_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123456789")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_verify")
os.environ.setdefault("INTERNAL_API_KEY", "test_internal_key")
os.environ.setdefault("JWT_SECRET", "test_jwt_secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/2")
os.environ.setdefault("FACTURACION_URL", "http://facturacion:8001")
os.environ.setdefault("EMISOR_RFC_DEFAULT", "DNS010101AAA")
os.environ.setdefault("ENVIRONMENT", "test")
