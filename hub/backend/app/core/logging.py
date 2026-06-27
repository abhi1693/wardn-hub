import logging
import sys

from pythonjsonlogger.json import JsonFormatter

from app.core.config import get_settings


class TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for attribute in ("otelTraceID", "otelSpanID", "otelTraceSampled", "otelServiceName"):
            if not hasattr(record, attribute):
                setattr(record, attribute, "")
        return True


def configure_logging() -> None:
    settings = get_settings()

    handler = logging.StreamHandler(sys.stdout)
    log_format = "%(asctime)s %(levelname)s %(name)s %(message)s"
    if settings.otel_enabled:
        handler.addFilter(TraceContextFilter())
        log_format += " %(otelTraceID)s %(otelSpanID)s %(otelTraceSampled)s %(otelServiceName)s"

    handler.setFormatter(
        JsonFormatter(
            log_format,
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.upper())
