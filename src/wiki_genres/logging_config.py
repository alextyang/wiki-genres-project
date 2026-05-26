"""structlog configuration. Call ``configure_logging()`` once at process startup."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Set up structlog with either JSON or pretty-print output."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if fmt == "pretty":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(
            exception_formatter=structlog.dev.plain_traceback
        )
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,  # keep False while testing configs
    )

    # Also configure stdlib logging so any library noise respects the level.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=logging.getLevelName(level.upper()),
    )
