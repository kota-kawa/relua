import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app.audit_context import audit_run, get_audit_run_id
from app.mcp_server import _guarded


def test_nested_calls_inherit_run_and_errors_restore_outer_context():
    inner = _guarded("batch.item", get_audit_run_id)

    def write(run_id=None):
        assert inner() == run_id
        raise RuntimeError("private server detail")

    guarded = _guarded("write", write)
    with audit_run("outer-execution"):
        with pytest.raises(ToolError, match="internal_error"):
            guarded("inner-execution")
        assert get_audit_run_id() == "outer-execution"
    assert get_audit_run_id() is None


def test_concurrent_async_calls_keep_separate_run_ids():
    async def write(run_id=None):
        before = get_audit_run_id()
        await asyncio.sleep(0)
        return before, get_audit_run_id()

    async def execute():
        guarded = _guarded("write", write)
        return await asyncio.gather(guarded(run_id="first-execution"), guarded(run_id="second-execution"))

    assert asyncio.run(execute()) == [
        ("first-execution", "first-execution"), ("second-execution", "second-execution"),
    ]
    assert get_audit_run_id() is None
