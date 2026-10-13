# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
"""MFAPI support for Indian mutual-fund NAV refreshes."""
from __future__ import annotations

import json
import math
import os
import re
import threading
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.app.core.external_api_logging import open_external_url
from backend.app.core.config import MFAPI_SCHEMES_PATH, ensure_data_dir

PROVIDER = "mfapi"
BASE_URL = "https://api.mfapi.in/mf"
_CACHE_LOCK = threading.RLock()


@dataclass(frozen=True)
class MfapiQuote:
    scheme_code: str
    scheme_name: str
    nav: float
    nav_date: str


def is_indian_mutual_fund(security_type: str | None, investment_country: str | None) -> bool:
    return (security_type or "").strip().casefold() == "mutual fund" and (investment_country or "").strip().casefold() == "india"


def _request_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "portfolio-analyser/1.0"})
    with open_external_url(request, provider=PROVIDER, timeout=20, opener=urllib.request.urlopen) as response:
        return json.loads(response.read().decode("utf-8"))


def _valid_schemes(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("MFAPI scheme list returned an unexpected response.")
    schemes = [row for row in payload if isinstance(row, dict) and row.get("schemeCode") and row.get("schemeName")]
    if not schemes:
        raise ValueError("MFAPI scheme list did not contain valid schemes.")
    return schemes


def _download_schemes() -> list[dict[str, Any]]:
    payload = _request_json(BASE_URL)
    return _valid_schemes(payload)


def _write_schemes(schemes: list[dict[str, Any]]) -> None:
    ensure_data_dir()
    temporary = MFAPI_SCHEMES_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(schemes, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(MFAPI_SCHEMES_PATH)


def cached_schemes() -> list[dict[str, Any]] | None:
    try:
        return _valid_schemes(json.loads(MFAPI_SCHEMES_PATH.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def fetch_schemes() -> list[dict[str, Any]]:
    """Use the local public scheme catalog; download it only when absent/invalid."""
    with _CACHE_LOCK:
        cached = cached_schemes()
        if cached is not None:
            return cached
        schemes = _download_schemes()
        _write_schemes(schemes)
        return schemes


def refresh_scheme_cache() -> dict[str, Any]:
    """User-requested forced refresh of the on-disk MFAPI scheme catalog."""
    with _CACHE_LOCK:
        schemes = _download_schemes()
        _write_schemes(schemes)
        return {"scheme_count": len(schemes), "updated_at": datetime.now().astimezone().isoformat()}


def fetch_latest(scheme_code: str) -> MfapiQuote:
    code = str(scheme_code).strip()
    if not code.isdigit():
        raise ValueError("MFAPI scheme code must contain digits only.")
    payload = _request_json(f"{BASE_URL}/{urllib.parse.quote(code)}/latest")
    if not isinstance(payload, dict):
        raise ValueError("MFAPI did not return a latest NAV for this scheme code.")
    meta, data = payload.get("meta"), payload.get("data")
    if not isinstance(meta, dict) or not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError("MFAPI did not return a latest NAV for this scheme code.")
    try:
        nav = float(data[0].get("nav"))
    except (TypeError, ValueError) as exc:
        raise ValueError("MFAPI returned a non-numeric NAV.") from exc
    if not math.isfinite(nav) or nav <= 0:
        raise ValueError("MFAPI returned an invalid NAV.")
    raw_date = str(data[0].get("date") or "")
    try:
        nav_date = datetime.strptime(raw_date, "%d-%m-%Y").date().isoformat()
    except ValueError as exc:
        raise ValueError("MFAPI returned an invalid NAV date.") from exc
    name = str(meta.get("scheme_name") or "").strip()
    if not name:
        raise ValueError("MFAPI did not return a scheme name.")
    return MfapiQuote(scheme_code=code, scheme_name=name, nav=nav, nav_date=nav_date)


def _tokens(value: str) -> tuple[str, ...]:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").upper()
    value = value.replace("&", " AND ")
    value = re.sub(r"\bREGULAR\b", " REGULAR PLAN ", value)
    value = re.sub(r"\bDIRECT\b", " DIRECT PLAN ", value)
    value = re.sub(r"\bDIVIDEND\b", " IDCW ", value)
    return tuple(re.findall(r"[A-Z0-9]+", value))


def resolve_scheme(name: str, schemes: list[dict[str, Any]]) -> tuple[str, str]:
    """Resolve only an unambiguous match; callers must offer manual override otherwise."""
    target = _tokens(name)
    if not target:
        raise ValueError("The mutual-fund name is empty and cannot be matched to MFAPI.")
    target_set = set(target)
    exact = [(str(row["schemeCode"]), str(row["schemeName"])) for row in schemes if _tokens(str(row["schemeName"])) == target]
    if len(exact) == 1:
        return exact[0]
    # Preserve explicitly supplied plan/option semantics.  A name without one
    # is intentionally ambiguous when several plan variants exist.
    qualifiers = {token for token in target_set if token in {"DIRECT", "REGULAR", "PLAN", "GROWTH", "IDCW"}}
    candidates = []
    for row in schemes:
        scheme_tokens = _tokens(str(row["schemeName"]))
        scheme_set = set(scheme_tokens)
        if target_set.issubset(scheme_set) and (not qualifiers or qualifiers.issubset(scheme_set)):
            candidates.append((str(row["schemeCode"]), str(row["schemeName"])))
    if len(candidates) == 1:
        return candidates[0]
    sample = "; ".join(f"{code} — {scheme_name}" for code, scheme_name in candidates[:5])
    if candidates:
        raise ValueError(f"MFAPI name match is ambiguous. Enter a scheme code manually. Candidates: {sample}")
    raise ValueError("No MFAPI scheme matched this fund name. Enter a scheme code manually.")
