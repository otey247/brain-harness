"""OpenTelemetry tracing, optional.

Pydantic AI emits OTel spans for each model request and tool call. Call
``setup_tracing()`` once at startup; set ``OTEL_EXPORTER_OTLP_ENDPOINT`` to send
spans to any OTLP backend (Langfuse, Phoenix, Honeycomb, Azure Monitor).
Message content is excluded unless ``BRAIN_TRACE_CONTENT=1``, because bundle
text may be private.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def setup_tracing(service_name: str = "brain-harness") -> bool:
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from pydantic_ai import Agent, InstrumentationSettings
    except ImportError:
        log.warning("tracing requested but the 'otel' extra is not installed")
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    include = os.environ.get("BRAIN_TRACE_CONTENT") == "1"
    Agent.instrument_all(InstrumentationSettings(tracer_provider=provider, include_content=include))
    return True
