"""Custom application exception hierarchy (FR-36, NFR-15).

Provides domain-specific exception classes that map to meaningful HTTP
status codes via the centralized handler registered in ``app/main.py``.
Every exception carries a ``detail`` string and an ``error_code`` for
machine-readable error identification.

Usage::

    raise NotFoundError(f"Page {page_id} not found.")
    raise ConflictError("Page is already approved.")
    raise UpstreamServiceError("LLM call failed.")

The :func:`~app.main.unhandled_exception_handler` handler catches every
:class:`AppException` subclass and returns a JSON body with the
appropriate HTTP status and the ``detail`` message.
"""

from __future__ import annotations


class AppException(Exception):
    """Base application exception -- maps to 500 Internal Server Error.

    Subclasses override *status_code* to produce different HTTP responses.
    """

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or "Internal server error")
        self.detail = detail or "Internal server error"


class ValidationError(AppException):
    """Maps to 422 Unprocessable Entity -- bad request payload or state."""

    status_code: int = 422
    error_code: str = "validation_error"


class BadRequestError(AppException):
    """Maps to 400 Bad Request -- request is syntactically valid but semantically empty/invalid."""

    status_code: int = 400
    error_code: str = "bad_request"


class PayloadTooLargeError(AppException):
    """Maps to 413 Payload Too Large -- OD-7 Raw Mode size/page-limit exceeded."""

    status_code: int = 413
    error_code: str = "payload_too_large"


class NotFoundError(AppException):
    """Maps to 404 Not Found -- entity does not exist or not owned by user."""

    status_code: int = 404
    error_code: str = "not_found"


class ConflictError(AppException):
    """Maps to 409 Conflict -- invalid status transition (FR-37 guard)."""

    status_code: int = 409
    error_code: str = "conflict"


class UpstreamServiceError(AppException):
    """Maps to 502 Bad Gateway -- external dependency failure."""

    status_code: int = 502
    error_code: str = "upstream_service_error"