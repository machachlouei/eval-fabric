"""TraceStore protocol and backend dispatcher.

The runner does not know which backend it talks to; it just calls the methods
on the protocol below. New backends register themselves under the
``eval_fabric.tracestore.backends`` entry point so they can be selected by URI
scheme.
"""

from eval_fabric.tracestore.protocol import TraceStore
from eval_fabric.tracestore.sqlite import SQLiteTraceStore
from eval_fabric.tracestore.uri import open_trace_store, register_backend

__all__ = [
    "SQLiteTraceStore",
    "TraceStore",
    "open_trace_store",
    "register_backend",
]
