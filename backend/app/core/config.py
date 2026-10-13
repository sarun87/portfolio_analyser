# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
DATABASE_PATH = DATA_DIR / "portfolio.db.encrypted"
AUTH_CONFIG_PATH = DATA_DIR / "auth.json"
MFAPI_SCHEMES_PATH = DATA_DIR / "mfapi_schemes.json"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
APP_ENV = os.getenv("PORTFOLIO_ENV", "development").lower()
SESSION_COOKIE_SECURE = os.getenv("PORTFOLIO_SESSION_COOKIE_SECURE", "true" if APP_ENV == "production" else "false").lower() == "true"
TRUSTED_ORIGINS = tuple(
    origin.strip().rstrip("/")
    for origin in os.getenv("PORTFOLIO_TRUSTED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000").split(",")
    if origin.strip()
)


def validate_security_configuration() -> None:
    if APP_ENV != "production":
        return
    if not SESSION_COOKIE_SECURE:
        raise RuntimeError("Production requires PORTFOLIO_SESSION_COOKIE_SECURE=true.")
    if not TRUSTED_ORIGINS or any(not origin.startswith("https://") for origin in TRUSTED_ORIGINS):
        raise RuntimeError("Production requires HTTPS PORTFOLIO_TRUSTED_ORIGINS.")


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
