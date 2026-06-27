import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_tracer_provider_configured = False
_global_instrumentation_configured = False
_sqlalchemy_instrumented = False


def configure_telemetry(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.otel_enabled:
        return

    _configure_tracer_provider(settings)
    _instrument_app(app, settings)
    _instrument_global_libraries()
    _instrument_sqlalchemy()


def _configure_tracer_provider(settings: Settings) -> None:
    global _tracer_provider_configured

    if _tracer_provider_configured:
        return

    provider = TracerProvider(
        resource=Resource.create(_build_resource_attributes(settings)),
        sampler=ParentBased(TraceIdRatioBased(settings.otel_traces_sample_ratio)),
    )
    exporter = OTLPSpanExporter(
        endpoint=settings.otel_exporter_otlp_traces_endpoint or None,
        headers=_parse_key_value_pairs(settings.otel_exporter_otlp_traces_headers) or None,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer_provider_configured = True


def _instrument_app(app: FastAPI, settings: Settings) -> None:
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=settings.otel_excluded_urls or None,
    )


def _instrument_global_libraries() -> None:
    global _global_instrumentation_configured

    if _global_instrumentation_configured:
        return

    HTTPXClientInstrumentor().instrument()
    LoggingInstrumentor().instrument(set_logging_format=False)
    _global_instrumentation_configured = True


def _instrument_sqlalchemy() -> None:
    global _sqlalchemy_instrumented

    if _sqlalchemy_instrumented:
        return

    try:
        from app.db.session import engine

        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        _sqlalchemy_instrumented = True
    except Exception:
        logger.exception("SQLAlchemy OpenTelemetry instrumentation failed")


def _build_resource_attributes(settings: Settings) -> dict[str, str]:
    attributes = {
        "service.name": settings.otel_service_name,
        "service.namespace": settings.otel_service_namespace,
        "service.version": settings.app_version,
        "deployment.environment.name": settings.environment,
    }
    attributes.update(_parse_key_value_pairs(settings.otel_resource_attributes))
    return attributes


def _parse_key_value_pairs(value: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in value.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue

        key, pair_value = item.split("=", 1)
        key = key.strip()
        if key:
            pairs[key] = pair_value.strip()
    return pairs
