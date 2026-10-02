from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from fastapi import APIRouter, Cookie, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from io import BytesIO
from starlette.background import BackgroundTask
from typing import Optional

from backend.app.core.config import AUTH_CONFIG_PATH, SESSION_COOKIE_SECURE, TRUSTED_ORIGINS

from backend.app.core.encryption import (
    EncryptionError, generate_salt, key_manager, load_encryption_config, save_encryption_config,
)
from backend.app.db.database import database_manager, get_connection
from backend.app.db.schema import init_db
from backend.app.services.classification_service import classify_all, classify_security
from backend.app.services.asset_service import (
    create_real_estate_asset,
    create_static_account,
    delete_real_estate_asset,
    create_private_equity_asset, delete_private_equity_asset, list_private_equity_assets, update_private_equity_asset,
    create_liability, delete_liability, list_liabilities, update_liability,
    delete_static_account,
    list_real_estate_assets,
    list_static_accounts,
    update_real_estate_asset,
    update_static_account,
)
from backend.app.services.import_service import commit_statement, preview_statement
from backend.app.services.models import (
    AuthStatus,
    Broker,
    BrokerConfigPreview,
    BrokerConfigPreviewRequest,
    BrokerDraft,
    BrokerSaveRequest,
    ChangePassphraseRequest,
    DatabaseTransferRequest,
    CleanDatabaseResult,
    ClassificationRefreshResult,
    CurrencySetting,
    ReportBranding, ReportBrandingUpdate, ReportRequest,
    DashboardAnalytics,
    FxRate,
    FxRateUpdate,
    ImportCommitRequest,
    ImportPreview,
    ImportPreviewRequest,
    ImportResult,
    Position,
    PositionBulkUpdateItem,
    PositionCreate,
    PositionUpdate,
    PriceRefreshResult, PriceRefreshJobStatus,
    RealEstateAsset,
    RealEstateAssetCreate,
    RealEstateAssetUpdate,
    PrivateEquityAsset, PrivateEquityAssetCreate, PrivateEquityAssetUpdate,
    SetupRequest,
    StaticAccount,
    StaticAccountCreate,
    StaticAccountUpdate,
    Liability, LiabilityCreate, LiabilityUpdate,
    UnlockRequest,
    FinancialAssumptions,
    AllocationTarget,
    AllocationTargetSet,
    AllocationCategoryCreate,
    Goal,
    GoalCreate,
    GoalUpdate,
    GoalsSummary,
    InsightFinding,
    Insights,
    SnapshotComparison,
    SavedScenario,
    ScenarioAnalysis,
    ScenarioInput,
    StressTestRequest,
    StressTestResult,
    ExposureAnalysis, FundComposition, FundCompositionInput, PublicMetadataPreview, PublicMetadataAcceptance, FundMetadata, PeerResearch, FundHtmlSyncRequest,
    HistoryRefreshResult, ManualMarketSeriesInput, MarketHistoryInput, RiskAnalysis, RiskSettings,
    FeeAnalysis, FeeSettings, SecurityFee, SecurityFeeInput, PortfolioFee, PortfolioFeeInput, ScheduledExpense, ScheduledExpenseInput,
    FundDataSecurity, FundDataRefreshRequest, FundDataRefreshResult, MfapiSchemeCacheUpdate,
)
from backend.app.services.allocation_category_service import create_category, delete_category, list_categories
from backend.app.services.portfolio_service import create_position, dashboard, delete_position_history, list_positions, profit_loss, update_position, update_positions
from backend.app.services.price_service import refresh_all, refresh_security
from backend.app.services.price_refresh_jobs import price_refresh_jobs
from backend.app.services.fx_service import (
    SUPPORTED_CURRENCIES,
    get_display_currency,
    list_fx_rates,
    refresh_fx_rates,
    set_display_currency,
    set_fx_rate,
)
from backend.app.services.repositories import (
    clean_brokerage_data,
    clean_portfolio_data,
    clean_real_estate_data,
    clean_private_equity_data,
    clean_liability_data,
    clean_static_account_data,
    get_brokers,
)
from backend.app.services.database_transfer_service import (
    TransferError,
    create_export_file,
    import_export,
    inspect_export,
)
from backend.app.services.broker_service import delete_broker, preview_broker_configuration, save_broker
from backend.app.services.insight_service import (
    create_goal, delete_goal, get_assumptions, insights, list_goals_summary, list_targets,
    replace_targets, save_assumptions, snapshot_comparison, update_goal, list_scheduled_expenses,
    save_scheduled_expense, delete_scheduled_expense,
)
from backend.app.services.scenario_service import (
    analyze_scenario, delete_scenario, list_scenarios, run_stress_test, save_scenario, update_scenario,
)
from backend.app.services.exposure_service import (
    cached_public_preview, exposure_analysis, get_composition, preview_public_metadata, save_composition, accept_public_metadata, get_fund_metadata, research_peers, cached_peer_research,
)
from backend.app.services.fund_data_service import list_fund_data, refresh_fund_data
from backend.app.services.mfapi_service import refresh_scheme_cache
from backend.app.services.risk_service import (
    get_risk_settings, refresh_market_history, risk_analysis, save_manual_history, save_manual_market_series, save_risk_settings,
)
from backend.app.services.fee_service import (
    accept_public_fee, delete_portfolio_fee, fee_analysis, get_fee_settings, list_portfolio_fees,
    list_security_fees, save_fee_settings, save_portfolio_fee, save_security_fee,
)
from backend.app.services.analytics_cache import analytics_cache
from backend.app.services.report_service import generate_report, get_branding, save_branding


SESSION_COOKIE_NAME = "portfolio_session"
CSRF_COOKIE_NAME = "portfolio_csrf"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def set_session_cookies(response: Response) -> None:
    session_token = key_manager.session_token
    csrf_token = key_manager.csrf_token
    if not session_token or not csrf_token:
        raise RuntimeError("Cannot create a session cookie while locked.")
    response.set_cookie(SESSION_COOKIE_NAME, session_token, httponly=True, secure=SESSION_COOKIE_SECURE, samesite="lax", path="/api")
    # The frontend reads only this anti-CSRF value; the authentication token remains HttpOnly.
    response.set_cookie(CSRF_COOKIE_NAME, csrf_token, httponly=False, secure=SESSION_COOKIE_SECURE, samesite="lax", path="/")


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/api", secure=SESSION_COOKIE_SECURE, samesite="lax")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=SESSION_COOKIE_SECURE, samesite="lax")


def require_unlocked(
    request: Request,
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    csrf_cookie: Optional[str] = Cookie(default=None, alias=CSRF_COOKIE_NAME),
    csrf_header: Optional[str] = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    if not key_manager.is_unlocked or not database_manager.is_unlocked:
        raise HTTPException(status_code=423, detail="Portfolio database is locked.")
    if not key_manager.authenticate(session_token):
        raise HTTPException(status_code=401, detail="A valid unlock session is required.")
    if request.method in UNSAFE_METHODS:
        origin = request.headers.get("origin", "").rstrip("/")
        if origin not in TRUSTED_ORIGINS:
            raise HTTPException(status_code=403, detail="Request origin is not trusted. Add the browser-facing origin to PORTFOLIO_TRUSTED_ORIGINS.")
        if not (key_manager.authenticate_csrf(session_token, csrf_cookie) and key_manager.authenticate_csrf(session_token, csrf_header)):
            raise HTTPException(status_code=403, detail="A valid CSRF token is required.")


auth_router = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(require_unlocked)])


@auth_router.get("/auth/status", response_model=AuthStatus)
def auth_status(session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> AuthStatus:
    salt, verifier = load_encryption_config()
    unlocked = (
        key_manager.is_unlocked and database_manager.is_unlocked
        and key_manager.authenticate(session_token)
    )
    return AuthStatus(configured=bool(salt and verifier), unlocked=unlocked)


@auth_router.post("/auth/setup", response_model=AuthStatus)
def setup_auth(request: SetupRequest, response: Response) -> AuthStatus:
    salt, verifier = load_encryption_config()
    if salt and verifier:
        raise HTTPException(status_code=409, detail="Encryption has already been configured.")
    salt = generate_salt()
    try:
        verifier_token = key_manager.setup(request.passphrase, salt)
        save_encryption_config(salt, verifier_token)
        database_manager.unlock()
        with get_connection() as conn:
            init_db(conn)
    except EncryptionError as exc:
        database_manager.lock()
        key_manager.lock()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_session_cookies(response)
    return AuthStatus(configured=True, unlocked=True)


@auth_router.post("/auth/unlock", response_model=AuthStatus)
def unlock_auth(request: UnlockRequest, response: Response) -> AuthStatus:
    salt, verifier = load_encryption_config()
    if not salt or not verifier:
        raise HTTPException(status_code=409, detail="Encryption has not been configured.")
    try:
        key_manager.unlock(request.passphrase, salt, verifier)
        database_manager.unlock()
        with get_connection() as conn:
            init_db(conn)
    except EncryptionError as exc:
        database_manager.lock()
        key_manager.lock()
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    set_session_cookies(response)
    return AuthStatus(configured=True, unlocked=True)


@router.post("/auth/lock", response_model=AuthStatus)
def lock_auth(response: Response) -> AuthStatus:
    # Cancellation precedes closing the encrypted connection.  The job manager
    # serializes this with its short write commits, preventing lock-race writes.
    price_refresh_jobs.cancel()
    database_manager.lock()
    key_manager.lock()
    salt, verifier = load_encryption_config()
    clear_session_cookies(response)
    return AuthStatus(configured=bool(salt and verifier), unlocked=False)


@router.post("/auth/logout", response_model=AuthStatus)
def logout_auth(response: Response, session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> AuthStatus:
    """Revoke only this browser session; the shared portfolio stays unlocked."""
    key_manager.revoke_session(session_token)
    salt, verifier = load_encryption_config()
    clear_session_cookies(response)
    return AuthStatus(configured=bool(salt and verifier), unlocked=False)


@router.post("/auth/change-passphrase", response_model=AuthStatus)
def change_passphrase(request: ChangePassphraseRequest, response: Response) -> AuthStatus:
    """Re-encrypt the persisted database and replace its password verifier."""
    try:
        salt, replacement_fernet, verifier = key_manager.prepare_passphrase_change(request.new_passphrase)
        staged_config = AUTH_CONFIG_PATH.with_suffix(AUTH_CONFIG_PATH.suffix + ".rotation")
        save_encryption_config(salt, verifier, staged_config)
        previous_snapshot = database_manager.path.read_bytes() if database_manager.path.exists() else None
        replacement_snapshot = database_manager.encrypted_snapshot(replacement_fernet)
        replaced_snapshot = False
        try:
            database_manager.replace_encrypted_snapshot(replacement_snapshot)
            replaced_snapshot = True
            staged_config.replace(AUTH_CONFIG_PATH)
        except OSError:
            if replaced_snapshot:
                if previous_snapshot is None:
                    database_manager.path.unlink(missing_ok=True)
                else:
                    database_manager.replace_encrypted_snapshot(previous_snapshot)
            raise
        key_manager.activate_fernet(replacement_fernet)
    except (EncryptionError, OSError) as exc:
        staged_config = AUTH_CONFIG_PATH.with_suffix(AUTH_CONFIG_PATH.suffix + ".rotation")
        staged_config.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not change the encryption password.") from exc
    set_session_cookies(response)
    return AuthStatus(configured=True, unlocked=True)


@router.get("/brokers", response_model=list[Broker])
def brokers() -> list[Broker]:
    with get_connection() as conn:
        return [Broker(**row) for row in get_brokers(conn)]


@router.post("/brokers/preview", response_model=BrokerConfigPreview)
def preview_broker(payload: BrokerConfigPreviewRequest) -> BrokerConfigPreview:
    with get_connection() as conn:
        try:
            return preview_broker_configuration(conn, payload.draft, payload.csv_text, payload.statement_currency)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/brokers", response_model=Broker)
def create_broker(payload: BrokerSaveRequest) -> Broker:
    with get_connection() as conn:
        try:
            preview = preview_broker_configuration(conn, payload.draft, payload.sample_csv, payload.statement_currency) if payload.sample_csv else None
            return Broker(**save_broker(conn, payload.draft, preview))
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/brokers/{broker_id}", response_model=Broker)
def update_broker(broker_id: int, payload: BrokerSaveRequest) -> Broker:
    with get_connection() as conn:
        try:
            preview = preview_broker_configuration(conn, payload.draft, payload.sample_csv, payload.statement_currency) if payload.sample_csv else None
            return Broker(**save_broker(conn, payload.draft, preview, broker_id))
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/brokers/{broker_id}")
def remove_broker(broker_id: int) -> dict[str, bool]:
    with get_connection() as conn:
        try: delete_broker(conn, broker_id)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"deleted": True}


@router.post("/imports/preview", response_model=ImportPreview)
def preview_import(request: ImportPreviewRequest) -> ImportPreview:
    with get_connection() as conn:
        try:
            return preview_statement(conn, request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/imports/commit", response_model=ImportResult)
def commit_import(request: ImportCommitRequest) -> ImportResult:
    with get_connection() as conn:
        try:
            return commit_statement(conn, request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except EncryptionError as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc


@router.get("/positions", response_model=list[Position])
def positions() -> list[Position]:
    with get_connection() as conn:
        return list_positions(conn)


@router.post("/positions", response_model=Position)
def add_position(payload: PositionCreate) -> Position:
    with get_connection() as conn:
        try:
            return create_position(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/positions/bulk", response_model=list[Position])
def edit_positions_bulk(updates: list[PositionBulkUpdateItem]) -> list[Position]:
    if not updates:
        raise HTTPException(status_code=400, detail="At least one position update is required.")
    if len({item.position_id for item in updates}) != len(updates):
        raise HTTPException(status_code=400, detail="A position can only be updated once per bulk request.")
    with get_connection() as conn:
        try:
            return update_positions(conn, [(item.position_id, item.payload) for item in updates])
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.put("/positions/{position_id}", response_model=Position)
def edit_position(position_id: int, payload: PositionUpdate) -> Position:
    with get_connection() as conn:
        try:
            return update_position(conn, position_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.delete("/positions/{position_id}")
def remove_position(position_id: int) -> dict[str, bool]:
    with get_connection() as conn:
        try:
            delete_position_history(conn, position_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True}


@router.get("/profit-loss", response_model=list[Position])
def pl() -> list[Position]:
    with get_connection() as conn:
        return profit_loss(conn)


@router.get("/analytics/dashboard", response_model=DashboardAnalytics)
def analytics_dashboard() -> DashboardAnalytics:
    with get_connection() as conn:
        return analytics_cache.get("dashboard", database_manager.revision, lambda: dashboard(conn))


@router.get("/report-branding", response_model=ReportBranding)
def report_branding() -> ReportBranding:
    with get_connection() as conn:
        return get_branding(conn)


@router.put("/report-branding", response_model=ReportBranding)
def update_report_branding(payload: ReportBrandingUpdate) -> ReportBranding:
    with get_connection() as conn:
        try:
            return save_branding(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reports/generate")
def download_report(payload: ReportRequest):
    with get_connection() as conn:
        try:
            pdf = generate_report(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"net-worth-{payload.report_type.lower()}-report.pdf"
    return StreamingResponse(BytesIO(pdf), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/insights", response_model=Insights)
def portfolio_insights() -> Insights:
    with get_connection() as conn:
        return analytics_cache.get("insights:basic", database_manager.revision, lambda: insights(conn, include_forecast=False))


@router.get("/insights/projection", response_model=Insights)
def portfolio_projection_insights() -> Insights:
    with get_connection() as conn:
        return analytics_cache.get("insights:projection", database_manager.revision, lambda: insights(conn, include_forecast=True))


@router.get("/review-inbox", response_model=list[InsightFinding])
def portfolio_review_inbox() -> list[InsightFinding]:
    with get_connection() as conn:
        from backend.app.services.advanced_findings import advanced_findings
        severity = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        return analytics_cache.get("review-inbox", database_manager.revision, lambda: sorted(insights(conn, include_forecast=False).findings + advanced_findings(conn), key=lambda item: (severity[item.severity], item.impact_amount or 0), reverse=True))


@router.get("/snapshot-comparison", response_model=SnapshotComparison)
def compare_latest_snapshots() -> SnapshotComparison:
    with get_connection() as conn:
        return snapshot_comparison(conn)


@router.get("/scenarios", response_model=list[SavedScenario])
def scenarios() -> list[SavedScenario]:
    with get_connection() as conn:
        return list_scenarios(conn)


@router.post("/scenarios", response_model=SavedScenario)
def add_scenario(payload: ScenarioInput) -> SavedScenario:
    with get_connection() as conn:
        try:
            return save_scenario(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/scenarios/{scenario_id}", response_model=SavedScenario)
def edit_scenario(scenario_id: int, payload: ScenarioInput) -> SavedScenario:
    with get_connection() as conn:
        try:
            return update_scenario(conn, scenario_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.delete("/scenarios/{scenario_id}")
def remove_scenario(scenario_id: int) -> dict[str, bool]:
    with get_connection() as conn:
        try:
            delete_scenario(conn, scenario_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True}


@router.post("/scenarios/analyze", response_model=ScenarioAnalysis)
def analyze_proposed_scenario(payload: ScenarioInput) -> ScenarioAnalysis:
    with get_connection() as conn:
        try:
            return analyze_scenario(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/stress-tests/run", response_model=StressTestResult)
def stress_test(payload: StressTestRequest) -> StressTestResult:
    with get_connection() as conn:
        try:
            return run_stress_test(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/look-through", response_model=ExposureAnalysis)
def look_through() -> ExposureAnalysis:
    with get_connection() as conn:
        return analytics_cache.get("exposure", database_manager.revision, lambda: exposure_analysis(conn))


@router.get("/fund-data", response_model=list[FundDataSecurity])
def fund_data() -> list[FundDataSecurity]:
    with get_connection() as conn:
        return list_fund_data(conn)


@router.post("/fund-data/refresh", response_model=list[FundDataRefreshResult])
def refresh_funds(payload: FundDataRefreshRequest) -> list[FundDataRefreshResult]:
    with get_connection() as conn:
        return refresh_fund_data(conn, payload.security_ids)


@router.post("/mfapi/schemes/refresh", response_model=MfapiSchemeCacheUpdate)
def refresh_mfapi_schemes() -> MfapiSchemeCacheUpdate:
    try:
        return MfapiSchemeCacheUpdate(**refresh_scheme_cache())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not update the MFAPI scheme list: {exc}") from exc


@router.get("/fund-compositions/{security_id}", response_model=Optional[FundComposition])
def fund_composition(security_id: int) -> Optional[FundComposition]:
    with get_connection() as conn:
        return get_composition(conn, security_id)


@router.put("/fund-compositions/{security_id}", response_model=FundComposition)
def update_fund_composition(security_id: int, payload: FundCompositionInput) -> FundComposition:
    with get_connection() as conn:
        try:
            return save_composition(conn, security_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/public-metadata/{security_id}/preview", response_model=PublicMetadataPreview)
def public_metadata_preview(security_id: int, payload: FundHtmlSyncRequest) -> PublicMetadataPreview:
    with get_connection() as conn:
        try:
            return preview_public_metadata(conn, security_id, payload.source, payload.url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/fund-compositions/{security_id}/accept-public", response_model=PublicMetadataAcceptance)
def accept_public_composition(security_id: int) -> PublicMetadataAcceptance:
    with get_connection() as conn:
        try:
            return accept_public_metadata(conn, security_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/fund-metadata/{security_id}", response_model=Optional[FundMetadata])
def fund_metadata(security_id: int) -> Optional[FundMetadata]:
    with get_connection() as conn:
        return get_fund_metadata(conn, security_id)


@router.post("/fund-peers/{security_id}/research", response_model=PeerResearch)
def find_fund_peers(security_id: int) -> PeerResearch:
    with get_connection() as conn:
        try: return research_peers(conn, security_id)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/fund-peers/{security_id}", response_model=PeerResearch)
def cached_fund_peers(security_id: int) -> PeerResearch:
    with get_connection() as conn:
        try: return cached_peer_research(conn, security_id)
        except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/risk/settings", response_model=RiskSettings)
def risk_settings() -> RiskSettings:
    with get_connection() as conn:
        return get_risk_settings(conn)


@router.put("/risk/settings", response_model=RiskSettings)
def update_risk_settings(payload: RiskSettings) -> RiskSettings:
    with get_connection() as conn:
        return save_risk_settings(conn, payload)


@router.post("/market-history/refresh", response_model=list[HistoryRefreshResult])
def refresh_history() -> list[HistoryRefreshResult]:
    with get_connection() as conn:
        return refresh_market_history(conn)


@router.put("/market-history/{security_id}", response_model=HistoryRefreshResult)
def import_market_history(security_id: int, payload: MarketHistoryInput) -> HistoryRefreshResult:
    with get_connection() as conn:
        try:
            return save_manual_history(conn, security_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/market-history/manual-series", response_model=HistoryRefreshResult)
def import_manual_reference_history(payload: ManualMarketSeriesInput) -> HistoryRefreshResult:
    with get_connection() as conn:
        try:
            return save_manual_market_series(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/risk-analysis", response_model=RiskAnalysis)
def portfolio_risk_analysis() -> RiskAnalysis:
    with get_connection() as conn:
        return analytics_cache.get("risk", database_manager.revision, lambda: risk_analysis(conn))


@router.get("/security-fees", response_model=list[SecurityFee])
def security_fees() -> list[SecurityFee]:
    with get_connection() as conn:
        return list_security_fees(conn)


@router.put("/security-fees/{security_id}", response_model=SecurityFee)
def update_security_fee(security_id: int, payload: SecurityFeeInput) -> SecurityFee:
    with get_connection() as conn:
        try:
            return save_security_fee(conn, security_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/security-fees/{security_id}/accept-public", response_model=SecurityFee)
def accept_public_expense_ratio(security_id: int) -> SecurityFee:
    with get_connection() as conn:
        try:
            return accept_public_fee(conn, security_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/portfolio-fees", response_model=list[PortfolioFee])
def portfolio_fees() -> list[PortfolioFee]:
    with get_connection() as conn:
        return list_portfolio_fees(conn)


@router.post("/portfolio-fees", response_model=PortfolioFee)
def add_portfolio_fee(payload: PortfolioFeeInput) -> PortfolioFee:
    with get_connection() as conn:
        try:
            return save_portfolio_fee(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/portfolio-fees/{fee_id}", response_model=PortfolioFee)
def update_portfolio_fee(fee_id: int, payload: PortfolioFeeInput) -> PortfolioFee:
    with get_connection() as conn:
        try:
            return save_portfolio_fee(conn, payload, fee_id)
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.delete("/portfolio-fees/{fee_id}")
def remove_portfolio_fee(fee_id: int) -> dict[str, bool]:
    with get_connection() as conn:
        try:
            delete_portfolio_fee(conn, fee_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True}


@router.get("/fees/settings", response_model=FeeSettings)
def fee_settings() -> FeeSettings:
    with get_connection() as conn:
        return get_fee_settings(conn)


@router.put("/fees/settings", response_model=FeeSettings)
def update_fee_settings(payload: FeeSettings) -> FeeSettings:
    with get_connection() as conn:
        return save_fee_settings(conn, payload)


@router.get("/fee-analysis", response_model=FeeAnalysis)
def portfolio_fee_analysis() -> FeeAnalysis:
    with get_connection() as conn:
        return analytics_cache.get("fees", database_manager.revision, lambda: fee_analysis(conn))


@router.get("/settings/assumptions", response_model=FinancialAssumptions)
def financial_assumptions() -> FinancialAssumptions:
    with get_connection() as conn:
        return get_assumptions(conn)


@router.put("/settings/assumptions", response_model=FinancialAssumptions)
def update_financial_assumptions(payload: FinancialAssumptions) -> FinancialAssumptions:
    with get_connection() as conn:
        try:
            return save_assumptions(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/scheduled-expenses", response_model=list[ScheduledExpense])
def scheduled_expenses() -> list[ScheduledExpense]:
    with get_connection() as conn:
        return list_scheduled_expenses(conn)


@router.post("/scheduled-expenses", response_model=ScheduledExpense)
def create_scheduled_expense(payload: ScheduledExpenseInput) -> ScheduledExpense:
    with get_connection() as conn:
        try:
            return save_scheduled_expense(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/scheduled-expenses/{expense_id}", response_model=ScheduledExpense)
def update_scheduled_expense(expense_id: int, payload: ScheduledExpenseInput) -> ScheduledExpense:
    with get_connection() as conn:
        try:
            return save_scheduled_expense(conn, payload, expense_id)
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.delete("/scheduled-expenses/{expense_id}")
def remove_scheduled_expense(expense_id: int) -> dict:
    with get_connection() as conn:
        try:
            delete_scheduled_expense(conn, expense_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True}


@router.get("/allocation-targets", response_model=list[AllocationTarget])
def allocation_targets(dimension: Optional[str] = None) -> list[AllocationTarget]:
    with get_connection() as conn:
        return list_targets(conn, dimension)


@router.put("/allocation-targets/{dimension}", response_model=list[AllocationTarget])
def update_allocation_targets(dimension: str, payload: AllocationTargetSet) -> list[AllocationTarget]:
    with get_connection() as conn:
        try:
            return replace_targets(conn, dimension, payload.targets)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/allocation-categories", response_model=list[str])
def allocation_categories() -> list[str]:
    with get_connection() as conn:
        return list_categories(conn)


@router.post("/allocation-categories", response_model=str)
def add_allocation_category(payload: AllocationCategoryCreate) -> str:
    with get_connection() as conn:
        try:
            return create_category(conn, payload.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/allocation-categories/{name}")
def remove_allocation_category(name: str) -> dict[str, bool]:
    with get_connection() as conn:
        try:
            delete_category(conn, name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"deleted": True}


@router.get("/goals", response_model=GoalsSummary)
def goals() -> GoalsSummary:
    with get_connection() as conn:
        return analytics_cache.get("goals", database_manager.revision, lambda: list_goals_summary(conn))


@router.post("/goals", response_model=Goal)
def add_goal(payload: GoalCreate) -> Goal:
    with get_connection() as conn:
        try:
            return create_goal(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/goals/{goal_id}", response_model=Goal)
def edit_goal(goal_id: int, payload: GoalUpdate) -> Goal:
    with get_connection() as conn:
        try:
            return update_goal(conn, goal_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.delete("/goals/{goal_id}")
def remove_goal(goal_id: int) -> dict[str, bool]:
    with get_connection() as conn:
        try:
            delete_goal(conn, goal_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True}


@router.post("/prices/refresh/{security_id}", response_model=PriceRefreshResult)
def refresh_one(security_id: int) -> PriceRefreshResult:
    with get_connection() as conn:
        return refresh_security(conn, security_id)


@router.post("/prices/refresh-all", response_model=list[PriceRefreshResult])
def refresh_prices() -> list[PriceRefreshResult]:
    with get_connection() as conn:
        return refresh_all(conn)


@router.post("/prices/refresh-jobs", response_model=PriceRefreshJobStatus)
def start_price_refresh_job() -> PriceRefreshJobStatus:
    try:
        return price_refresh_jobs.start()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/prices/refresh-jobs/active", response_model=Optional[PriceRefreshJobStatus])
def active_price_refresh_job() -> Optional[PriceRefreshJobStatus]:
    return price_refresh_jobs.active()


@router.get("/prices/refresh-jobs/{job_id}", response_model=PriceRefreshJobStatus)
def get_price_refresh_job(job_id: str) -> PriceRefreshJobStatus:
    job = price_refresh_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Price refresh job not found.")
    return job


@router.post("/prices/refresh-jobs/{job_id}/cancel", response_model=PriceRefreshJobStatus)
def cancel_price_refresh_job(job_id: str) -> PriceRefreshJobStatus:
    job = price_refresh_jobs.cancel(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Price refresh job not found.")
    return job


def reset_application(response: Response) -> CleanDatabaseResult:
    price_refresh_jobs.cancel()
    database_manager.discard()
    AUTH_CONFIG_PATH.unlink(missing_ok=True)
    key_manager.lock()
    clear_session_cookies(response)
    return CleanDatabaseResult(
        cleaned=True,
        reset=True,
        message="All application data, settings, and encryption credentials were removed.",
    )


@router.post("/database/export")
def export_database(payload: DatabaseTransferRequest) -> FileResponse:
    """Create a user-requested, plain SQLite snapshot without retaining it."""
    try:
        with get_connection() as conn:
            snapshot = create_export_file(conn, payload.categories)
    except TransferError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(
        snapshot,
        media_type="application/vnd.sqlite3",
        filename="portfolio-analyser-export.db",
        background=BackgroundTask(snapshot.unlink, missing_ok=True),
    )


@router.post("/database/inspect")
async def inspect_database(file: UploadFile = File(...)) -> dict[str, list[str]]:
    """Validate an uploaded export and report the categories it contains."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
            temporary = Path(handle.name)
            total = 0
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > 100 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Import files must be 100 MB or smaller.")
                handle.write(chunk)
        try:
            with get_connection() as conn:
                categories = inspect_export(conn, temporary)
        except TransferError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"categories": categories}
    finally:
        await file.close()
        if temporary:
            temporary.unlink(missing_ok=True)


@router.post("/database/import")
async def import_database(file: UploadFile = File(...), categories: str = Form(...)) -> dict[str, object]:
    """Validate an uploaded export fully before replacing selected live data."""
    try:
        requested = json.loads(categories)
        if not isinstance(requested, list):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Import categories must be a JSON list.") from exc
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
            temporary = Path(handle.name)
            total = 0
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > 100 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Import files must be 100 MB or smaller.")
                handle.write(chunk)
        try:
            with get_connection() as conn:
                counts = import_export(conn, temporary, requested)
        except TransferError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"imported": True, "categories": requested, "record_counts": counts}
    finally:
        await file.close()
        if temporary:
            temporary.unlink(missing_ok=True)


@router.post("/database/clean", response_model=CleanDatabaseResult)
def clean_database(response: Response) -> CleanDatabaseResult:
    return reset_application(response)


@router.post("/database/clean/{scope}", response_model=CleanDatabaseResult)
def clean_database_scope(scope: str, response: Response) -> CleanDatabaseResult:
    normalized = scope.lower().strip()
    cleaners = {
        "brokerage": (clean_brokerage_data, "Brokerage data cleared."),
        "static": (clean_static_account_data, "Static banking data cleared."),
        "real-estate": (clean_real_estate_data, "Real estate data cleared."),
        "private-equity": (clean_private_equity_data, "Private equity data cleared."),
        "liabilities": (clean_liability_data, "Liabilities data cleared."),
    }
    if normalized == "all":
        return reset_application(response)
    if normalized not in cleaners:
        raise HTTPException(status_code=400, detail="Unsupported clean scope.")
    cleaner, message = cleaners[normalized]
    with get_connection() as conn:
        cleaner(conn)
        return CleanDatabaseResult(
            cleaned=True,
            message=f"{message} Encryption settings, broker definitions, display currency, and FX rates were preserved.",
        )


@router.post("/securities/classify/{security_id}", response_model=ClassificationRefreshResult)
def classify_one_security(security_id: int) -> ClassificationRefreshResult:
    with get_connection() as conn:
        return classify_security(conn, security_id)


@router.post("/securities/classify-all", response_model=list[ClassificationRefreshResult])
def classify_securities() -> list[ClassificationRefreshResult]:
    with get_connection() as conn:
        return classify_all(conn)


@router.get("/currency", response_model=CurrencySetting)
def currency_setting() -> CurrencySetting:
    with get_connection() as conn:
        return CurrencySetting(display_currency=get_display_currency(conn), supported_currencies=SUPPORTED_CURRENCIES)


@router.post("/currency/{currency}", response_model=CurrencySetting)
def update_currency(currency: str) -> CurrencySetting:
    with get_connection() as conn:
        try:
            return set_display_currency(conn, currency)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/fx-rates", response_model=list[FxRate])
def fx_rates() -> list[FxRate]:
    with get_connection() as conn:
        return list_fx_rates(conn)


@router.post("/fx-rates", response_model=FxRate)
def update_fx_rate(rate: FxRateUpdate) -> FxRate:
    with get_connection() as conn:
        try:
            return set_fx_rate(conn, rate)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/fx-rates/refresh", response_model=list[FxRate])
def refresh_rates() -> list[FxRate]:
    with get_connection() as conn:
        return refresh_fx_rates(conn)


@router.get("/static-accounts", response_model=list[StaticAccount])
def static_accounts() -> list[StaticAccount]:
    with get_connection() as conn:
        return list_static_accounts(conn)


@router.post("/static-accounts", response_model=StaticAccount)
def add_static_account(payload: StaticAccountCreate) -> StaticAccount:
    with get_connection() as conn:
        try:
            return create_static_account(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/static-accounts/{account_id}", response_model=StaticAccount)
def edit_static_account(account_id: int, payload: StaticAccountUpdate) -> StaticAccount:
    with get_connection() as conn:
        try:
            return update_static_account(conn, account_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.delete("/static-accounts/{account_id}")
def remove_static_account(account_id: int) -> dict[str, bool]:
    with get_connection() as conn:
        try:
            delete_static_account(conn, account_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True}


@router.get("/real-estate", response_model=list[RealEstateAsset])
def real_estate_assets() -> list[RealEstateAsset]:
    with get_connection() as conn:
        return list_real_estate_assets(conn)


@router.post("/real-estate", response_model=RealEstateAsset)
def add_real_estate_asset(payload: RealEstateAssetCreate) -> RealEstateAsset:
    with get_connection() as conn:
        try:
            return create_real_estate_asset(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/real-estate/{asset_id}", response_model=RealEstateAsset)
def edit_real_estate_asset(asset_id: int, payload: RealEstateAssetUpdate) -> RealEstateAsset:
    with get_connection() as conn:
        try:
            return update_real_estate_asset(conn, asset_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.delete("/real-estate/{asset_id}")
def remove_real_estate_asset(asset_id: int) -> dict[str, bool]:
    with get_connection() as conn:
        try:
            delete_real_estate_asset(conn, asset_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True}


@router.get("/private-equity", response_model=list[PrivateEquityAsset])
def private_equity_assets() -> list[PrivateEquityAsset]:
    with get_connection() as conn: return list_private_equity_assets(conn)


@router.post("/private-equity", response_model=PrivateEquityAsset)
def add_private_equity_asset(payload: PrivateEquityAssetCreate) -> PrivateEquityAsset:
    with get_connection() as conn:
        try: return create_private_equity_asset(conn, payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/private-equity/{asset_id}", response_model=PrivateEquityAsset)
def edit_private_equity_asset(asset_id: int, payload: PrivateEquityAssetUpdate) -> PrivateEquityAsset:
    with get_connection() as conn:
        try: return update_private_equity_asset(conn, asset_id, payload)
        except ValueError as exc: raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.delete("/private-equity/{asset_id}")
def remove_private_equity_asset(asset_id: int) -> dict[str, bool]:
    with get_connection() as conn:
        try: delete_private_equity_asset(conn, asset_id)
        except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True}


@router.get("/liabilities", response_model=list[Liability])
def liabilities() -> list[Liability]:
    with get_connection() as conn:
        return list_liabilities(conn)


@router.post("/liabilities", response_model=Liability)
def add_liability(payload: LiabilityCreate) -> Liability:
    with get_connection() as conn:
        try:
            return create_liability(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/liabilities/{liability_id}", response_model=Liability)
def edit_liability(liability_id: int, payload: LiabilityUpdate) -> Liability:
    with get_connection() as conn:
        try:
            return update_liability(conn, liability_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.delete("/liabilities/{liability_id}")
def remove_liability(liability_id: int) -> dict[str, bool]:
    with get_connection() as conn:
        try:
            delete_liability(conn, liability_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True}
