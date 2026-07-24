from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

from app.core.logging import CorrelationIdFilter
from app.core.request_context import (
    current_correlation_id,
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from tests.conftest import assert_uuid


def test_request_context_imports_when_fastapi_is_blocked() -> None:
    code = """
import importlib.abc
import sys

class BlockFastApi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("fastapi", "starlette")):
            raise ModuleNotFoundError(fullname)
        return None

sys.meta_path.insert(0, BlockFastApi())
import app.core.request_context
print("request context import OK")
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "request context import OK" in result.stdout


def test_logging_imports_when_fastapi_is_blocked() -> None:
    code = """
import importlib.abc
import sys

class BlockFastApi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("fastapi", "starlette")):
            raise ModuleNotFoundError(fullname)
        return None

sys.meta_path.insert(0, BlockFastApi())
import app.core.logging
print("logging import OK")
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "logging import OK" in result.stdout


def test_logging_filter_reads_current_correlation_id() -> None:
    token = set_correlation_id("11111111-2222-4333-8444-555555555555")
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)
    try:
        CorrelationIdFilter().filter(record)
    finally:
        reset_correlation_id(token)

    assert record.correlation_id == "11111111-2222-4333-8444-555555555555"


def test_logging_filter_handles_missing_correlation_id() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)

    CorrelationIdFilter().filter(record)

    assert record.correlation_id is None


def test_get_correlation_id_generates_uuid_when_missing() -> None:
    correlation_id = get_correlation_id()

    assert_uuid(correlation_id)
    set_correlation_id(None)


def test_set_and_reset_correlation_context() -> None:
    token = set_correlation_id("11111111-2222-4333-8444-555555555555")
    assert current_correlation_id() == "11111111-2222-4333-8444-555555555555"

    reset_correlation_id(token)

    assert current_correlation_id() is None


def test_sequential_correlation_contexts_do_not_leak() -> None:
    first_token = set_correlation_id("11111111-2222-4333-8444-555555555555")
    assert current_correlation_id() == "11111111-2222-4333-8444-555555555555"
    reset_correlation_id(first_token)

    second_token = set_correlation_id("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    try:
        assert current_correlation_id() == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    finally:
        reset_correlation_id(second_token)

    assert current_correlation_id() is None


async def test_concurrent_async_correlation_contexts_do_not_leak() -> None:
    async def run_with_context(correlation_id: str) -> tuple[str, str | None]:
        token = set_correlation_id(correlation_id)
        try:
            await asyncio.sleep(0)
            return correlation_id, current_correlation_id()
        finally:
            reset_correlation_id(token)

    results = await asyncio.gather(
        run_with_context("11111111-2222-4333-8444-555555555555"),
        run_with_context("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"),
    )

    assert results == [
        (
            "11111111-2222-4333-8444-555555555555",
            "11111111-2222-4333-8444-555555555555",
        ),
        (
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        ),
    ]
    assert current_correlation_id() is None
