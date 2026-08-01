"""
Logs estructurados en JSON (structlog).
Nunca registrar: tokens, contraseñas, contenido del CSD, RFC completo en DEBUG.
"""
import logging
import sys

import structlog

from core.config import settings


def configure_logging() -> None:
    """Configurar structlog con salida JSON lista para ingestión en ELK / CloudWatch."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)
