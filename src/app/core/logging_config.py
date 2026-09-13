"""Central logging configuration for the PDF QA system backend.

This module implements the shared logging setup used by every phase.  All log
output is written to stdout in a consistent, greppable format; DEBUG-level
logs are only emitted when ``settings.DEBUG`` is true, preventing sensitive
traces from being flooded into production logs.
"""

import logging
import sys

from app.core.config import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging() -> None:
    """Configure the root logger for the application.

    Realizes the logging foundation needed by FR-36 (error handling): full
    tracebacks are logged server-side at ERROR level while clients receive
    sanitized JSON error bodies.  Call this once during app startup.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    # Avoid duplicate handlers when the app reloads in uvicorn --reload mode.
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger configured by :func:`configure_logging`.

    Args:
        name: Usually ``__name__`` of the calling module.

    Returns:
        A ready-to-use :class:`logging.Logger` instance.
    """
    return logging.getLogger(name)