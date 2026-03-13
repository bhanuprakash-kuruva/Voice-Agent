import logging
from pythonjsonlogger import jsonlogger

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter


def setup_tracing():

    resource = Resource.create({
        "service.name": "voice-rag-agent",
        "service.version": "1.0"
    })

    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(
        endpoint="http://localhost:30417",
        insecure=True
    )

    processor = BatchSpanProcessor(exporter)

    provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)

    return trace.get_tracer("voice-rag")


def setup_logging():

    logger = logging.getLogger()

    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler()

    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(message)s"
    )

    handler.setFormatter(formatter)

    logger.addHandler(handler)

    return logger