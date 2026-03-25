from contextvars import ContextVar
import uuid
from typing import Optional

correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
session_id_var: ContextVar[Optional[str]] = ContextVar("session_id", default=None)

def set_correlation_id(cid: str) -> None:
    """Set correlation ID for the current context"""
    correlation_id_var.set(cid)

def get_correlation_id() -> str:
    """Get or generate correlation ID"""
    cid = correlation_id_var.get()
    if not cid:
        cid = str(uuid.uuid4())
        correlation_id_var.set(cid)
    return cid

def set_request_id(rid: str) -> None:
    """Set request ID for the current context"""
    request_id_var.set(rid)

def get_request_id() -> Optional[str]:
    """Get request ID"""
    return request_id_var.get()

def set_user_id(uid: str) -> None:
    """Set user ID for the current context"""
    user_id_var.set(uid)

def get_user_id() -> Optional[str]:
    """Get user ID"""
    return user_id_var.get()

def set_session_id(sid: str) -> None:
    """Set session ID for the current context"""
    session_id_var.set(sid)

def get_session_id() -> Optional[str]:
    """Get session ID"""
    return session_id_var.get()

def clear_context() -> None:
    """Clear all context variables"""
    correlation_id_var.set(None)
    request_id_var.set(None)
    user_id_var.set(None)
    session_id_var.set(None)

def get_trace_id() -> str:
    """Get current trace ID from OpenTelemetry"""
    try:
        from opentelemetry.trace import get_current_span
        span = get_current_span()
        span_context = span.get_span_context()
        if span_context and span_context.trace_id:
            return format(span_context.trace_id, "032x")
    except Exception:
        pass
    return "no-trace"

class ObservabilityContext:
    """Context manager for observability context"""
    
    def __init__(self, correlation_id: Optional[str] = None, 
                 request_id: Optional[str] = None,
                 user_id: Optional[str] = None,
                 session_id: Optional[str] = None):
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.request_id = request_id
        self.user_id = user_id
        self.session_id = session_id
        self._previous_context = {}
    
    def __enter__(self):
        self._previous_context = {
            'correlation_id': correlation_id_var.get(),
            'request_id': request_id_var.get(),
            'user_id': user_id_var.get(),
            'session_id': session_id_var.get()
        }
        
        set_correlation_id(self.correlation_id)
        if self.request_id:
            set_request_id(self.request_id)
        if self.user_id:
            set_user_id(self.user_id)
        if self.session_id:
            set_session_id(self.session_id)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        correlation_id_var.set(self._previous_context['correlation_id'])
        request_id_var.set(self._previous_context['request_id'])
        user_id_var.set(self._previous_context['user_id'])
        session_id_var.set(self._previous_context['session_id'])