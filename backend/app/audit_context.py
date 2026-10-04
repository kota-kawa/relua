"""Scope audit correlation to one MCP call, including its nested writes."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_run_id: ContextVar[str | None] = ContextVar("audit_run_id", default=None)


def get_audit_run_id() -> str | None:
    return _run_id.get()


@contextmanager
def audit_run(run_id: str | None) -> Iterator[None]:
    token = _run_id.set(run_id)
    try:
        yield
    finally:
        _run_id.reset(token)
