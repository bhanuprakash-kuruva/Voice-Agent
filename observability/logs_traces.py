import logging
import socket
from pythonjsonlogger import jsonlogger

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from opentelemetry.propagate import set_global_textmap
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from opentelemetry.trace import get_current_span

from observability.context import get_correlation_id


# --------------------------------
# CORRELATION + TRACE FILTER
# --------------------------------

class CorrelationTraceFilter(logging.Filter):
    def filter(self, record):
        record.correlation_id = get_correlation_id()

        span = get_current_span()
        span_context = span.get_span_context()

        if span_context and span_context.trace_id:
            record.trace_id = format(span_context.trace_id, "032x")
        else:
            record.trace_id = None

        return True


# --------------------------------
# TRACING SETUP
# --------------------------------

from opentelemetry.trace import get_tracer_provider

def setup_tracing():

    if isinstance(get_tracer_provider(), TracerProvider):
        return trace.get_tracer("voice-rag")

    resource = Resource.create({
        "service.name": "voice-rag-agent",
        "service.version": "2.0",
        "service.instance.id": socket.gethostname()
    })

    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(
        endpoint="localhost:30417",
        insecure=True
    )

    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)

    set_global_textmap(TraceContextTextMapPropagator())

    return trace.get_tracer("voice-rag")
# --------------------------------
# LOGGING SETUP
# --------------------------------

def setup_logging():

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler()

        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(message)s %(correlation_id)s %(trace_id)s"
        )

        handler.setFormatter(formatter)
        handler.addFilter(CorrelationTraceFilter())

        logger.addHandler(handler)

    return logger