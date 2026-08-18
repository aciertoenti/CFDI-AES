"""
Configuración centralizada del microservicio WhatsApp Bot.
Todos los secretos se leen de variables de entorno — NUNCA hardcodeados.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Servicio ──────────────────────────────────────────────────────────────
    service_name: str = "cfdi-whatsapp-bot"
    service_port: int = 8006
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ── Base de datos ─────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://cfdi:secret_bot@postgres_bot/cfdi_bot",
        alias="DATABASE_URL",
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://redis:6379/2", alias="REDIS_URL")
    session_ttl_seconds: int = 1800  # 30 min de inactividad cierra sesión

    # ── WhatsApp Business Cloud API (Meta) ───────────────────────────────────
    # Supuesto: se usa la Cloud API directa de Meta (no proveedor intermedio)
    whatsapp_token: str = Field(alias="WHATSAPP_TOKEN")
    whatsapp_phone_number_id: str = Field(alias="WHATSAPP_PHONE_NUMBER_ID")
    whatsapp_verify_token: str = Field(alias="WHATSAPP_VERIFY_TOKEN")
    whatsapp_api_version: str = "v21.0"

    @property
    def whatsapp_api_url(self) -> str:
        return (
            f"https://graph.facebook.com/{self.whatsapp_api_version}"
            f"/{self.whatsapp_phone_number_id}/messages"
        )

    # ── Microservicio CFDI-AES (Facturación) ──────────────────────────────────
    # Supuesto: llamada directa al microservicio, sin pasar por el Gateway,
    # usando API key interna. El JWT del gateway es para usuarios finales.
    facturacion_url: str = Field(
        default="http://facturacion:8001", alias="FACTURACION_URL"
    )
    ia_url: str = Field(default="http://ia:8007", alias="IA_URL")
    internal_api_key: str = Field(alias="INTERNAL_API_KEY")

    # PAC Finkok — URLs separadas para timbrado y cancelaciones
    pac_url: str = Field(
        default="https://demo-facturacion.finkok.com/servicios/soap/stamp.wsdl",
        alias="PAC_URL",
    )
    pac_cancel_url: str = Field(
        default="https://demo-facturacion.finkok.com/servicios/soap/cancel.wsdl",
        alias="PAC_CANCEL_URL",
    )

    # RFC del emisor por defecto (para el chatbot de autoservicio). El default
    # anterior (DNS010101AAA) era un placeholder que nunca se dio de alta como
    # Emisor real - EKU9003173C9 es el RFC de pruebas del SAT con CSD real
    # y verificado (ver certs_test/, administracion).
    emisor_rfc_default: str = Field(
        default="EKU9003173C9", alias="EMISOR_RFC_DEFAULT"
    )
    # negocio_id (#15) al que pertenece emisor_rfc_default - necesario desde
    # que /facturas/timbrar exige X-Negocio-Id (commit 294fc52). Fijo a
    # proposito: la arquitectura actual asume un despliegue del bot = un
    # emisor = un negocio (mismo supuesto que ya tenia emisor_rfc_default).
    # Si algun dia un mismo bot debe servir a varios negocios, esto tendria
    # que resolverse por conversacion (ej. atado al numero de WhatsApp
    # Business que recibio el mensaje, o a datos capturados del cliente),
    # no como un valor fijo de configuracion.
    negocio_id_default: int = Field(
        default=1, alias="NEGOCIO_ID_DEFAULT"
    )

    # ── Seguridad ─────────────────────────────────────────────────────────────
    jwt_secret: str = Field(alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"

    # ── Retención de datos personales ────────────────────────────────────────
    # SAT recomienda 5 años mínimo para documentos fiscales
    data_retention_days: int = 1825  # 5 años

    # ── Política de aviso de privacidad ──────────────────────────────────────
    privacy_notice_url: str = Field(
        default="https://tudominio.mx/aviso-privacidad", alias="PRIVACY_NOTICE_URL"
    )


# Instancia singleton — importar desde aquí en todo el proyecto
settings = Settings()  # type: ignore[call-arg]
