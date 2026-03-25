import logging
import socket
import sys
import os
from typing import Optional, Dict, Any
from pythonjsonlogger import jsonlogger

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from opentelemetry.propagate import set_global_textmap
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.trace import get_current_span

from observability.context import get_correlation_id, get_user_id, get_session_id


# --------------------------------
# ENHANCED LOG FILTER
# --------------------------------

class EnhancedCorrelationTraceFilter(logging.Filter):
    """Enhanced filter that adds correlation, trace, and user context to logs"""
    
    def filter(self, record):
        # Add correlation ID
        record.correlation_id = get_correlation_id()
        
        # Add user context
        record.user_id = get_user_id() or "anonymous"
        record.session_id = get_session_id() or "unknown"
        
        # Add trace context
        span = get_current_span()
        span_context = span.get_span_context()
        
        if span_context and span_context.trace_id:
            record.trace_id = format(span_context.trace_id, "032x")
            record.span_id = format(span_context.span_id, "016x")
        else:
            record.trace_id = None
            record.span_id = None
        
        # Add service context
        record.service_name = "voice-rag-agent"
        record.service_version = "2.0"
        
        return True


# --------------------------------
# ENHANCED JSON FORMATTER
# --------------------------------

class EnhancedJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with additional fields"""
    
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        
        # Add timestamp in ISO format
        log_record['timestamp'] = self.formatTime(record)
        
        # Ensure all observability fields are present
        log_record['correlation_id'] = getattr(record, 'correlation_id', None)
        log_record['trace_id'] = getattr(record, 'trace_id', None)
        log_record['span_id'] = getattr(record, 'span_id', None)
        log_record['user_id'] = getattr(record, 'user_id', None)
        log_record['session_id'] = getattr(record, 'session_id', None)
        
        # Add log level as string
        log_record['level'] = record.levelname
        log_record['logger'] = record.name


# --------------------------------
# STAGE BOUNDARY LOGGER HELPER
# --------------------------------

def log_stage_boundary(stage: str, action: str, correlation_id: str = None, **kwargs):
    """Log stage entry/exit with clear visual markers for console and JSON"""
    if correlation_id is None:
        correlation_id = get_correlation_id()
    
    logger = logging.getLogger(__name__)
    
    # Log as JSON for structured logging
    logger.info({
        "event": f"stage_{action}",
        "stage": stage,
        "correlation_id": correlation_id,
        "message": f"{'▶' if action == 'enter' else '◀'} {stage.upper()} {action.upper()}",
        **kwargs
    })
    
    # Also print to console with colors if available
    if action == "enter":
        print(f"\n{'='*50}")
        print(f"🔵 [{stage.upper()}] START - {correlation_id[:8]}...")
        print(f"{'='*50}")
    else:
        print(f"🟢 [{stage.upper()}] COMPLETE - {kwargs.get('duration', 'N/A')}s")
        print(f"{'='*50}")


# --------------------------------
# TRACING SETUP (ENHANCED)
# --------------------------------

_tracer_provider_initialized = False
_tracer_instance = None

def setup_tracing(service_name: str = "voice-rag-agent", 
                  service_version: str = "2.0",
                  sampling_rate: float = 1.0,
                  enable_console_exporter: bool = False):
    """
    Setup OpenTelemetry tracing with enhanced configuration
    """
    global _tracer_provider_initialized, _tracer_instance
    
    from opentelemetry.trace import get_tracer_provider
    
    if _tracer_provider_initialized and isinstance(get_tracer_provider(), TracerProvider):
        if _tracer_instance:
            return _tracer_instance
        return trace.get_tracer(service_name)
    
    # Create resource with enhanced attributes
    resource = Resource.create({
        "service.name": service_name,
        "service.version": service_version,
        "service.instance.id": socket.gethostname(),
        "service.namespace": "voice-rag",
        "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        "host.name": socket.gethostname(),
    })
    
    # Configure sampler
    sampler = ParentBased(TraceIdRatioBased(sampling_rate))
    
    # Create tracer provider
    provider = TracerProvider(resource=resource, sampler=sampler)
    
    # Configure OTLP exporter
    otlp_endpoint = os.getenv("OTLP_ENDPOINT", "localhost:30417")
    exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        insecure=True
    )
    
    # Add span processors
    processor = BatchSpanProcessor(
        exporter,
        max_queue_size=2048,
        schedule_delay_millis=5000,
        max_export_batch_size=512
    )
    provider.add_span_processor(processor)
    
    # Add console exporter for debugging if enabled
    if enable_console_exporter:
        console_processor = BatchSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(console_processor)
    
    # Set global tracer provider
    trace.set_tracer_provider(provider)
    
    # Set global propagator
    set_global_textmap(TraceContextTextMapPropagator())
    
    _tracer_provider_initialized = True
    _tracer_instance = trace.get_tracer(service_name)
    
    return _tracer_instance


# --------------------------------
# ENHANCED LOGGING SETUP
# --------------------------------

_logger_initialized = False

def setup_logging(log_level: str = "INFO", 
                  log_file: Optional[str] = None,
                  enable_console: bool = True):
    """
    Setup enhanced logging configuration
    """
    global _logger_initialized
    
    if _logger_initialized:
        return logging.getLogger()
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Create JSON formatter
    json_formatter = EnhancedJsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level"
        }
    )
    
    # Add console handler with color support
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(json_formatter)
        console_handler.addFilter(EnhancedCorrelationTraceFilter())
        root_logger.addHandler(console_handler)
    
    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(json_formatter)
        file_handler.addFilter(EnhancedCorrelationTraceFilter())
        root_logger.addHandler(file_handler)
    
    _logger_initialized = True
    
    # Return logger for this module
    return logging.getLogger(__name__)


# --------------------------------
# UTILITY FUNCTIONS
# --------------------------------

def get_tracer():
    """Get the configured tracer instance"""
    if not _tracer_instance:
        return setup_tracing()
    return _tracer_instance

def create_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """Helper to create a span with common attributes"""
    tracer = get_tracer()
    span = tracer.start_span(name)
    
    if attributes:
        for key, value in attributes.items():
            span.set_attribute(key, value)
    
    # Add correlation context to span
    span.set_attribute("correlation_id", get_correlation_id())
    span.set_attribute("user_id", get_user_id() or "anonymous")
    
    return span