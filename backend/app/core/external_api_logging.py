# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
"""Safe, rotating logging for outbound public-data requests."""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from backend.app.core.config import LOG_DIR, ensure_log_dir


LOGGER_NAME = "portfolio.external_api"
LOG_FILE_NAME = "external_api.log"
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 6


def setup_external_api_logging() -> logging.Logger:
    """Return the dedicated external API logger without adding duplicate handlers."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    log_path = LOG_DIR / LOG_FILE_NAME
    if any(getattr(handler, "baseFilename", None) == str(log_path) for handler in logger.handlers):
        return logger

    ensure_log_dir()
    handler = RotatingFileHandler(log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"))
    logger.addHandler(handler)
    return logger


def _sanitized_url(url: str) -> str:
    """Remove query data and credentials before an endpoint reaches a local log."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _response_status(response: Any) -> int | str:
    status = getattr(response, "status", None)
    if status is None:
        getcode = getattr(response, "getcode", None)
        status = getcode() if callable(getcode) else None
    return status if isinstance(status, int) else "unknown"


@contextmanager
def open_external_url(
    request: urllib.request.Request,
    *,
    provider: str,
    timeout: float,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Any:
    """Yield an outbound response and emit exactly one completion record."""
    logger = setup_external_api_logging()
    started = time.perf_counter()
    endpoint = _sanitized_url(request.full_url)
    method = request.get_method()
    try:
        response = opener(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        duration_ms = round((time.perf_counter() - started) * 1000)
        logger.warning("provider=%s method=%s endpoint=%s outcome=failed status=%s duration_ms=%s error=%s", provider, method, endpoint, exc.code, duration_ms, type(exc).__name__)
        raise
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000)
        logger.warning("provider=%s method=%s endpoint=%s outcome=failed status=none duration_ms=%s error=%s", provider, method, endpoint, duration_ms, type(exc).__name__)
        raise
    status = _response_status(response)
    try:
        with response as open_response:
            yield open_response
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000)
        logger.warning("provider=%s method=%s endpoint=%s outcome=failed status=%s duration_ms=%s error=%s", provider, method, endpoint, status, duration_ms, type(exc).__name__)
        raise
    duration_ms = round((time.perf_counter() - started) * 1000)
    logger.info("provider=%s method=%s endpoint=%s outcome=success status=%s duration_ms=%s", provider, method, endpoint, status, duration_ms)
