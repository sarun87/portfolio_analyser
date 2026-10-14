# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
import logging
import urllib.error
import urllib.request

import pytest

from backend.app.core import external_api_logging
from backend.app.services import exposure_service


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class HtmlResponse(Response):
    headers = {}

    def read(self, *_args):
        return b"<html><body>Fund data</body></html>"


@pytest.fixture(autouse=True)
def isolated_external_api_logger(tmp_path, monkeypatch):
    logger = logging.getLogger(external_api_logging.LOGGER_NAME)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    monkeypatch.setattr(external_api_logging, "LOG_DIR", tmp_path)
    yield tmp_path
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()


def test_logs_successful_external_call_with_status_and_sanitized_endpoint(isolated_external_api_logger):
    request = urllib.request.Request("https://api.example.test/v1/quote?token=secret&symbol=CSPX")

    with external_api_logging.open_external_url(
        request, provider="example-provider", timeout=5, opener=lambda *_args, **_kwargs: Response()
    ) as response:
        assert response.status == 200
    content = (isolated_external_api_logger / external_api_logging.LOG_FILE_NAME).read_text()
    assert "provider=example-provider" in content
    assert "method=GET" in content
    assert "endpoint=https://api.example.test/v1/quote" in content
    assert "outcome=success status=200" in content
    assert "duration_ms=" in content
    assert "token=secret" not in content
    assert "symbol=CSPX" not in content


def test_logs_http_and_network_failures_without_leaking_exception_text(isolated_external_api_logger):
    request = urllib.request.Request("https://api.example.test/v1/quote?api_key=secret")

    with pytest.raises(urllib.error.HTTPError), external_api_logging.open_external_url(
            request,
            provider="example-provider",
            timeout=5,
            opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.HTTPError(request.full_url, 429, "secret", None, None)),
        ):
        pass
    with pytest.raises(urllib.error.URLError), external_api_logging.open_external_url(
            request,
            provider="example-provider",
            timeout=5,
            opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("secret")),
        ):
        pass

    content = (isolated_external_api_logger / external_api_logging.LOG_FILE_NAME).read_text()
    assert "outcome=failed status=429" in content
    assert "error=HTTPError" in content
    assert "outcome=failed status=none" in content
    assert "error=URLError" in content
    assert "api_key=secret" not in content
    assert " secret" not in content


def test_logs_response_processing_failure_with_the_received_http_status(isolated_external_api_logger):
    request = urllib.request.Request("https://api.example.test/v1/quote")

    with pytest.raises(ValueError), external_api_logging.open_external_url(
        request, provider="example-provider", timeout=5, opener=lambda *_args, **_kwargs: Response()
    ):
        raise ValueError("invalid provider payload")

    content = (isolated_external_api_logger / external_api_logging.LOG_FILE_NAME).read_text()
    assert "outcome=failed status=200" in content
    assert "error=ValueError" in content
    assert "invalid provider payload" not in content


def test_public_html_sync_is_logged_through_the_external_call_wrapper(isolated_external_api_logger, monkeypatch):
    class Opener:
        def open(self, *_args, **_kwargs):
            return HtmlResponse()

    monkeypatch.setattr(exposure_service, "_public_url", lambda url: url)
    monkeypatch.setattr(exposure_service.urllib.request, "build_opener", lambda *_args: Opener())

    assert "Fund data" in exposure_service._fetch_html("https://www.google.com/finance/quote/CSPX:LON?token=secret", "google-finance-html")

    content = (isolated_external_api_logger / external_api_logging.LOG_FILE_NAME).read_text()
    assert "provider=google-finance-html" in content
    assert "endpoint=https://www.google.com/finance/quote/CSPX:LON" in content
    assert "token=secret" not in content


def test_setup_is_idempotent_and_uses_configured_rotation(isolated_external_api_logger):
    logger = external_api_logging.setup_external_api_logging()
    assert external_api_logging.setup_external_api_logging() is logger

    assert len(logger.handlers) == 1
    handler = logger.handlers[0]
    assert handler.maxBytes == external_api_logging.MAX_BYTES
    assert handler.backupCount == external_api_logging.BACKUP_COUNT
