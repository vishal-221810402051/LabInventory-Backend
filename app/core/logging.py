from __future__ import annotations

import logging
import sys
from typing import Any

from pythonjsonlogger.json import JsonFormatter


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        from app.core.correlation import current_correlation_id

        if not hasattr(record, "correlation_id"):
            record.correlation_id = current_correlation_id()
        return True


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = JsonFormatter(
        fmt=(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(event)s "
            "%(correlation_id)s %(http_method)s %(request_path)s %(response_status)s "
            "%(duration_ms)s"
        ),
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "logger",
        },
    )
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationIdFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def extra(**values: Any) -> dict[str, Any]:
    return values
