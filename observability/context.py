from contextvars import ContextVar
import uuid

correlation_id_var = ContextVar("correlation_id", default=None)

def set_correlation_id(cid: str):
    correlation_id_var.set(cid)

def get_correlation_id():
    cid = correlation_id_var.get()
    if not cid:
        cid = str(uuid.uuid4())
        correlation_id_var.set(cid)
    return cid