from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import auth_router, router
from backend.app.core.config import FRONTEND_DIST, TRUSTED_ORIGINS, ensure_data_dir, validate_security_configuration
from backend.app.core.encryption import key_manager
from backend.app.core.external_api_logging import setup_external_api_logging
from backend.app.db.database import database_manager


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_data_dir()
    setup_external_api_logging()
    try:
        yield
    finally:
        database_manager.lock()
        key_manager.lock()


app = FastAPI(title="Portfolio Analyser", version="0.1.0", lifespan=lifespan)
validate_security_configuration()

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(TRUSTED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(router)


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    index = FRONTEND_DIST / "index.html"
    candidate = FRONTEND_DIST / full_path
    if full_path and candidate.exists() and candidate.is_file():
        return FileResponse(candidate)
    if index.exists():
        return FileResponse(index)
    return {
        "message": "Portfolio Analyser API is running. Build the frontend with `cd frontend && npm run build`."
    }
