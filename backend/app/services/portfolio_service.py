# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from backend.app.services.import_service import derive_per_unit_and_total
from backend.app.services.models import AnalyticsPoint, CountryReturn, DashboardAnalytics, Position, PositionCreate, PositionUpdate, TimeSeriesPoint
from backend.app.services.fx_service import SUPPORTED_CURRENCIES, convert_amount, fx_rate_lookup, get_display_currency, get_fx_rate
from backend.app.services.repositories import (
    get_or_create_account, get_broker_by_name, get_or_create_security,
    insert_import, insert_position,
)
from backend.app.core.encryption import EncryptionError, key_manager
from cryptography.fernet import InvalidToken


POSITION_SELECT_SQL = """
WITH latest_prices AS (
  SELECT security_id, price, price_date
  FROM (
    SELECT security_id, price, price_date,
           ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY price_date DESC, id DESC) AS sequence
    FROM price_history
  ) WHERE sequence = 1
)
SELECT
  p.id,
  s.id AS security_id,
  b.name AS broker_name,
  a.account_mask,
  a.account_number_enc,
  s.name AS security_name,
  s.symbol,
  s.security_type,
  s.allocation_category,
  s.sector,
  s.exchange,
  s.investment_country,
  s.mfapi_scheme_code,
  p.snapshot_date,
  p.acquisition_date,
  p.lot_number,
  p.units,
  p.per_unit_cost_basis,
  p.total_cost_basis,
  COALESCE(latest_prices.price, p.per_unit_fmv) AS per_unit_fmv,
  CASE WHEN latest_prices.price IS NOT NULL
       THEN p.units * latest_prices.price
       ELSE p.total_fmv END AS total_fmv,
  p.currency,
  latest_prices.price_date AS last_price_update
FROM positions p
JOIN accounts a ON a.id = p.account_id
JOIN brokers b ON b.id = a.broker_id
JOIN securities s ON s.id = p.security_id
LEFT JOIN latest_prices ON latest_prices.security_id = s.id
"""

POSITIONS_SQL = POSITION_SELECT_SQL + """
WHERE p.snapshot_date = (
  SELECT MAX(latest.snapshot_date) FROM positions latest WHERE latest.account_id = p.account_id
)
ORDER BY b.name, a.account_mask, s.name, p.lot_number
"""


def _position_from_row(conn: sqlite3.Connection, row, display_currency: str, rates: Optional[dict[tuple[str, str], float]] = None) -> Position:
    fmv = row["total_fmv"]
    cost = row["total_cost_basis"]
    fmv_display = convert_amount(conn, fmv, row["currency"], display_currency, rates)
    cost_display = convert_amount(conn, cost, row["currency"], display_currency, rates)
    gain = fmv_display - cost_display if fmv_display is not None and cost_display is not None else None
    native_gain = fmv - cost if fmv is not None and cost is not None else None
    pct = (native_gain / cost * 100) if native_gain is not None and cost not in (None, 0) else None
    return Position(
        id=row["id"],
        security_id=row["security_id"],
        broker_name=row["broker_name"],
        account_mask=row["account_mask"],
        account_number=_decrypt_account_number(row["account_number_enc"]),
        security_name=row["security_name"],
        symbol=row["symbol"],
        security_type=row["security_type"],
        allocation_category=row["allocation_category"],
        sector=row["sector"],
        exchange=row["exchange"],
        investment_country=row["investment_country"],
        mfapi_scheme_code=row["mfapi_scheme_code"],
        snapshot_date=row["snapshot_date"],
        acquisition_date=row["acquisition_date"],
        lot_number=row["lot_number"],
        units=row["units"],
        per_unit_cost_basis=row["per_unit_cost_basis"],
        total_cost_basis=cost,
        per_unit_fmv=row["per_unit_fmv"],
        total_fmv=fmv,
        per_unit_cost_basis_display=convert_amount(conn, row["per_unit_cost_basis"], row["currency"], display_currency, rates),
        total_cost_basis_display=cost_display,
        per_unit_fmv_display=convert_amount(conn, row["per_unit_fmv"], row["currency"], display_currency, rates),
        total_fmv_display=fmv_display,
        unrealized_gain_loss=gain,
        unrealized_gain_loss_native=native_gain,
        unrealized_gain_loss_pct=pct,
        currency=row["currency"],
        display_currency=display_currency,
        last_price_update=row["last_price_update"],
    )


def _decrypt_account_number(encrypted: Optional[str]) -> Optional[str]:
    """Account data is available to authenticated API requests only.

    Service tests and internal analytics can contain synthetic account rows that
    are deliberately not encrypted, so they continue to receive no plaintext.
    """
    try:
        return key_manager.decrypt(encrypted)
    except (EncryptionError, InvalidToken):
        return None


def list_positions(conn: sqlite3.Connection) -> list[Position]:
    display_currency = get_display_currency(conn)
    rates = fx_rate_lookup(conn)
    return [_position_from_row(conn, row, display_currency, rates) for row in conn.execute(POSITIONS_SQL)]


def get_position(conn: sqlite3.Connection, position_id: int) -> Position:
    row = conn.execute(
        POSITION_SELECT_SQL + " WHERE p.id = ?",
        (position_id,),
    ).fetchone()
    if not row:
        raise ValueError("Position not found.")
    return _position_from_row(conn, row, get_display_currency(conn))


def _clean_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _clean_required(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} is required.")
    return stripped


def _validate_currency(currency: str) -> str:
    normalized = currency.upper().strip()
    if normalized not in SUPPORTED_CURRENCIES:
        raise ValueError("Unsupported currency.")
    return normalized


def _canonical_security_type(value: str) -> str:
    """Equity is the canonical name for listed stock holdings."""
    normalized = _clean_required(value, "Security type")
    return "Equity" if normalized.lower() == "stock" else normalized


def create_position(conn: sqlite3.Connection, payload: PositionCreate) -> Position:
    broker_name = _clean_required(payload.broker_name, "Broker")
    security_name = _clean_required(payload.security_name, "Security name")
    security_type = _canonical_security_type(payload.security_type)
    allocation_category = _clean_required(payload.allocation_category, "Allocation category")
    from backend.app.services.allocation_category_service import register_category
    register_category(conn, allocation_category)
    sector = _clean_required(payload.sector, "Sector")
    snapshot_date = _clean_required(payload.snapshot_date, "Snapshot date")
    exchange = _clean_required(payload.exchange, "Exchange")
    investment_country = _clean_required(payload.investment_country, "Investment country")
    currency = _validate_currency(payload.currency)
    symbol = _clean_optional(payload.symbol.upper() if payload.symbol else None)
    acquisition_date = _clean_optional(payload.acquisition_date)
    lot_number = _clean_optional(payload.lot_number)
    per_unit_cost_basis, total_cost_basis = derive_per_unit_and_total(
        payload.units, payload.per_unit_cost_basis, payload.total_cost_basis,
    )
    per_unit_fmv, total_fmv = derive_per_unit_and_total(
        payload.units, payload.per_unit_fmv, payload.total_fmv,
    )

    broker = get_broker_by_name(conn, broker_name)
    if not broker:
        raise ValueError("Select an existing configured broker before adding a manual position.")
    broker_id = broker["id"]
    account_id = get_or_create_account(conn, broker_id, _clean_optional(payload.account_number))
    security_id = get_or_create_security(
        conn,
        name=security_name,
        security_type=security_type,
        symbol=symbol,
        exchange=exchange,
        investment_country=investment_country,
        location_source="manual",
    )
    conn.execute(
        """
        UPDATE securities
        SET allocation_category = ?, sector = ?, classification_source = 'manual', classified_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (allocation_category, sector, security_id),
    )
    import_id = insert_import(
        conn,
        broker_id=broker_id,
        account_id=account_id,
        statement_date=snapshot_date,
        source_filename=None,
        row_count=1,
        fingerprint=f"manual:{uuid.uuid4().hex}",
        detected_columns=[],
        errors=[],
        locked_fields=[],
    )
    position_id = insert_position(
        conn,
        import_id=import_id,
        account_id=account_id,
        security_id=security_id,
        snapshot_date=snapshot_date,
        acquisition_date=acquisition_date,
        lot_number=lot_number,
        units=payload.units,
        per_unit_cost_basis=per_unit_cost_basis,
        total_cost_basis=total_cost_basis,
        per_unit_fmv=per_unit_fmv,
        total_fmv=total_fmv,
        currency=currency,
    )
    return get_position(conn, position_id)


def update_position(conn: sqlite3.Connection, position_id: int, payload: PositionUpdate) -> Position:
    existing = conn.execute(
        """
        SELECT p.id, p.security_id, p.account_id, p.per_unit_fmv, p.total_fmv, a.broker_id, s.mfapi_scheme_code
        FROM positions p
        JOIN accounts a ON a.id = p.account_id
        JOIN securities s ON s.id = p.security_id
        WHERE p.id = ?
        """,
        (position_id,),
    ).fetchone()
    if not existing:
        raise ValueError("Position not found.")

    security_name = _clean_required(payload.security_name, "Security name")
    security_type = _canonical_security_type(payload.security_type)
    allocation_category = _clean_required(payload.allocation_category, "Allocation category")
    from backend.app.services.allocation_category_service import register_category
    register_category(conn, allocation_category)
    sector = _clean_required(payload.sector, "Sector")
    snapshot_date = _clean_required(payload.snapshot_date, "Snapshot date")
    currency = _validate_currency(payload.currency)
    from backend.app.services.mfapi_service import fetch_latest, is_indian_mutual_fund
    eligible_mfapi = is_indian_mutual_fund(security_type, payload.investment_country)
    scheme_code = _clean_optional(payload.mfapi_scheme_code)
    scheme_code_supplied = "mfapi_scheme_code" in payload.model_fields_set
    # Validate only an actual code change. Existing saved codes are included by
    # the normal edit form and must not make unrelated edits depend on MFAPI.
    next_scheme_code = scheme_code if scheme_code_supplied else existing["mfapi_scheme_code"]
    if next_scheme_code and eligible_mfapi and next_scheme_code != existing["mfapi_scheme_code"]:
        # Validate before any database write so an invalid manual override does
        # not partially apply a position edit.
        fetch_latest(next_scheme_code)
    symbol = _clean_optional(payload.symbol.upper() if payload.symbol else None)
    acquisition_date = _clean_optional(payload.acquisition_date)
    lot_number = _clean_optional(payload.lot_number)
    per_unit_cost_basis, total_cost_basis = derive_per_unit_and_total(
        payload.units,
        payload.per_unit_cost_basis,
        payload.total_cost_basis,
    )
    per_unit_fmv, total_fmv = derive_per_unit_and_total(
        payload.units,
        payload.per_unit_fmv,
        payload.total_fmv,
    )

    account_id = (
        existing["account_id"] if payload.account_number is None
        else get_or_create_account(conn, existing["broker_id"], _clean_optional(payload.account_number))
    )
    if account_id != existing["account_id"]:
        # Account numbers identify the account, not one snapshot row. Preserve
        # its complete position history when correcting the number.
        conn.execute("UPDATE positions SET account_id=? WHERE account_id=?", (account_id, existing["account_id"]))
        conn.execute("UPDATE statement_imports SET account_id=? WHERE account_id=?", (account_id, existing["account_id"]))
    conn.execute(
        """
        UPDATE securities
        SET symbol = ?,
            name = ?,
            security_type = ?,
            allocation_category = ?,
            sector = ?,
            exchange = ?,
            investment_country = ?,
            mfapi_scheme_code = ?,
            location_source = 'manual',
            location_resolved_at = CURRENT_TIMESTAMP,
            classification_source = 'manual',
            classified_at = CURRENT_TIMESTAMP,
            price_refresh_supported = ?
        WHERE id = ?
        """,
        (
            symbol,
            security_name,
            security_type,
            allocation_category,
            sector,
            _clean_required(payload.exchange, "Exchange"),
            _clean_required(payload.investment_country, "Investment country"),
            next_scheme_code if eligible_mfapi else None,
            0 if security_type.lower() == "cash" else 1,
            existing["security_id"],
        ),
    )
    conn.execute(
        """
        UPDATE positions
        SET account_id = ?,
            snapshot_date = ?,
            acquisition_date = ?,
            lot_number = ?,
            units = ?,
            per_unit_cost_basis = ?,
            total_cost_basis = ?,
            per_unit_fmv = ?,
            total_fmv = ?,
            currency = ?
        WHERE id = ?
        """,
        (
            account_id,
            snapshot_date,
            acquisition_date,
            lot_number,
            payload.units,
            per_unit_cost_basis,
            total_cost_basis,
            per_unit_fmv,
            total_fmv,
            currency,
            position_id,
        ),
    )
    if per_unit_fmv != existing["per_unit_fmv"] or total_fmv != existing["total_fmv"]:
        # A direct portfolio edit is an explicit manual valuation. Remove the
        # cached market quote that would otherwise override it when positions
        # are read back; the next price refresh can establish a new quote.
        conn.execute("DELETE FROM price_history WHERE security_id=?", (existing["security_id"],))
    return get_position(conn, position_id)


def update_positions(conn: sqlite3.Connection, updates: list[tuple[int, PositionUpdate]]) -> list[Position]:
    """Apply a set of position edits atomically, including direct service callers."""
    conn.execute("SAVEPOINT bulk_position_updates")
    try:
        result = [update_position(conn, position_id, payload) for position_id, payload in updates]
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT bulk_position_updates")
        conn.execute("RELEASE SAVEPOINT bulk_position_updates")
        raise
    conn.execute("RELEASE SAVEPOINT bulk_position_updates")
    return result


def delete_position_history(conn: sqlite3.Connection, position_id: int) -> None:
    """Remove the selected account/security/lot holding from every snapshot."""
    row = conn.execute("SELECT account_id, security_id, lot_number, acquisition_date FROM positions WHERE id=?", (position_id,)).fetchone()
    if not row:
        raise ValueError("Position not found.")
    conn.execute("""DELETE FROM positions WHERE account_id=? AND security_id=?
        AND COALESCE(lot_number, '')=COALESCE(?, '')
        AND COALESCE(acquisition_date, '')=COALESCE(?, '')""",
        (row["account_id"], row["security_id"], row["lot_number"], row["acquisition_date"]))


def profit_loss(conn: sqlite3.Connection) -> list[Position]:
    return sorted(
        list_positions(conn),
        key=lambda position: position.unrealized_gain_loss_native or 0,
        reverse=True,
    )


def _net_worth_balances_by_currency(conn: sqlite3.Connection) -> dict[str, float]:
    balances: dict[str, float] = {}

    def add(currency: str, amount: float) -> None:
        key = (currency or "USD").upper()
        balances[key] = balances.get(key, 0.0) + float(amount or 0)

    for position in list_positions(conn):
        add(position.currency, position.total_fmv or 0)
    for row in conn.execute("SELECT currency, SUM(amount) AS value FROM static_accounts GROUP BY currency"):
        add(row["currency"], row["value"])
    for row in conn.execute("SELECT currency, SUM(current_value) AS value FROM real_estate_assets GROUP BY currency"):
        add(row["currency"], row["value"])
    for row in conn.execute("SELECT currency, SUM(quantity * last_valuation_per_unit) AS value FROM private_equity_assets GROUP BY currency"):
        add(row["currency"], row["value"])
    for row in conn.execute("SELECT currency, SUM(outstanding_balance) AS value FROM liabilities GROUP BY currency"):
        add(row["currency"], -(row["value"] or 0))
    return balances


def capture_net_worth_snapshot(conn: sqlite3.Connection, snapshot_date: date) -> TimeSeriesPoint:
    """Capture one all-assets net-worth point for a user-selected local date."""
    date_key = snapshot_date.isoformat()
    conn.execute("SAVEPOINT capture_net_worth_snapshot")
    try:
        balances = _net_worth_balances_by_currency(conn)
        targets = set(SUPPORTED_CURRENCIES) | set(balances)
        rates = {
            (source, target): get_fx_rate(conn, source, target)
            for source in balances
            for target in targets
        }
        captured_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO portfolio_net_worth_snapshots(snapshot_date, captured_at) VALUES (?, ?)
               ON CONFLICT(snapshot_date) DO UPDATE SET captured_at = excluded.captured_at""",
            (date_key, captured_at),
        )
        conn.execute("DELETE FROM portfolio_net_worth_snapshot_balances WHERE snapshot_date = ?", (date_key,))
        conn.execute("DELETE FROM portfolio_net_worth_snapshot_fx_rates WHERE snapshot_date = ?", (date_key,))
        conn.executemany(
            "INSERT INTO portfolio_net_worth_snapshot_balances(snapshot_date, currency, net_amount) VALUES (?, ?, ?)",
            [(date_key, currency, amount) for currency, amount in balances.items()],
        )
        conn.executemany(
            "INSERT INTO portfolio_net_worth_snapshot_fx_rates(snapshot_date, from_currency, to_currency, rate) VALUES (?, ?, ?, ?)",
            [(date_key, source, target, rate) for (source, target), rate in rates.items()],
        )
        display_currency = get_display_currency(conn)
        value = sum(amount * rates[(currency, display_currency)] for currency, amount in balances.items())
        conn.execute("RELEASE SAVEPOINT capture_net_worth_snapshot")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT capture_net_worth_snapshot")
        conn.execute("RELEASE SAVEPOINT capture_net_worth_snapshot")
        raise

    return TimeSeriesPoint(date=date_key, value=value)


def net_worth_snapshot_history(conn: sqlite3.Connection, display_currency: Optional[str] = None) -> list[TimeSeriesPoint]:
    currency = (display_currency or get_display_currency(conn)).upper()
    points: list[TimeSeriesPoint] = []
    for snapshot in conn.execute("SELECT snapshot_date FROM portfolio_net_worth_snapshots ORDER BY snapshot_date"):
        balances = conn.execute(
            "SELECT currency, net_amount FROM portfolio_net_worth_snapshot_balances WHERE snapshot_date = ?",
            (snapshot["snapshot_date"],),
        ).fetchall()
        rates = {
            (row["from_currency"], row["to_currency"]): float(row["rate"])
            for row in conn.execute(
                "SELECT from_currency, to_currency, rate FROM portfolio_net_worth_snapshot_fx_rates WHERE snapshot_date = ?",
                (snapshot["snapshot_date"],),
            )
        }
        value = 0.0
        for row in balances:
            source = row["currency"].upper()
            rate = 1.0 if source == currency else rates.get((source, currency))
            if rate is None:
                raise ValueError(
                    f"Net-worth snapshot on {snapshot['snapshot_date']} is missing its captured {source}/{currency} FX rate."
                )
            value += float(row["net_amount"]) * rate
        points.append(TimeSeriesPoint(date=snapshot["snapshot_date"], value=value))
    return points


def dashboard(conn: sqlite3.Connection) -> DashboardAnalytics:
    display_currency = get_display_currency(conn)
    positions = list_positions(conn)
    brokerage_value = sum(position.total_fmv_display or 0 for position in positions)
    total_cost = sum(position.total_cost_basis_display or 0 for position in positions)
    gain = brokerage_value - total_cost
    pct = gain / total_cost * 100 if total_cost else None

    growth_totals: dict[str, float] = {}
    snapshot_dates = [row["snapshot_date"] for row in conn.execute("SELECT DISTINCT snapshot_date FROM positions ORDER BY snapshot_date")]
    for snapshot_date in snapshot_dates:
        # Each date represents the complete portfolio as it stood then: use
        # the latest available snapshot for every account, not only accounts
        # that happened to import on that exact date.
        rows = conn.execute(
            """SELECT p.currency, COALESCE(p.total_fmv, p.units * COALESCE(p.per_unit_fmv, 0), 0) AS value
               FROM positions p
               WHERE p.snapshot_date = (
                 SELECT MAX(previous.snapshot_date) FROM positions previous
                 WHERE previous.account_id = p.account_id AND previous.snapshot_date <= ?
               )""",
            (snapshot_date,),
        ).fetchall()
        growth_totals[snapshot_date] = sum(
            convert_amount(conn, row["value"] or 0, row["currency"], display_currency) or 0
            for row in rows
        )
    # Add/replace today's point with live position values (including any
    # current price overlays), so the graph reaches the current portfolio.
    if positions:
        growth_totals[date.today().isoformat()] = brokerage_value

    asset_totals: dict[str, float] = {}
    broker_totals: dict[str, float] = {}
    country_totals: dict[str, float] = {}
    exchange_totals: dict[str, float] = {}
    cash = 0.0
    invested = 0.0
    for position in positions:
        value = position.total_fmv_display or 0
        # Cash is represented once, alongside bank balances, rather than as a
        # regular asset bucket as well as a cash slice.
        if position.security_type.lower() != "cash":
            asset_totals[position.allocation_category] = asset_totals.get(position.allocation_category, 0) + value
        broker_totals[position.broker_name] = broker_totals.get(position.broker_name, 0) + value
        country_totals[position.investment_country] = country_totals.get(position.investment_country, 0) + value
        exchange_totals[position.exchange] = exchange_totals.get(position.exchange, 0) + value
        if position.security_type.lower() == "cash":
            cash += value
        else:
            invested += value

    static_rows = conn.execute(
        """
        SELECT category, currency, SUM(amount) AS value
        FROM static_accounts
        GROUP BY category, currency
        """
    ).fetchall()
    static_accounts_value = 0.0
    static_category_totals: dict[str, float] = {}
    for row in static_rows:
        value = convert_amount(conn, row["value"] or 0, row["currency"], display_currency) or 0
        static_accounts_value += value
        static_category_totals[row["category"]] = static_category_totals.get(row["category"], 0) + value
    bank_cash = static_category_totals.get("Bank Account", 0)
    asset_totals["Cash"] = cash + bank_cash
    retirement_value = static_category_totals.get("Retirement Account", 0)
    if retirement_value:
        asset_totals["Retirement"] = asset_totals.get("Retirement", 0) + retirement_value

    country_current: dict[str, dict[str, float]] = {}
    for position in positions:
        bucket = country_current.setdefault(position.investment_country, {"value": 0.0, "cost": 0.0})
        bucket["value"] += position.total_fmv_display or 0
        bucket["cost"] += position.total_cost_basis_display or 0
    snapshot_dates_all = [row["snapshot_date"] for row in conn.execute("SELECT DISTINCT snapshot_date FROM positions ORDER BY snapshot_date")]
    country_history: dict[str, tuple[float, float]] = {}
    if snapshot_dates_all:
        for cutoff in (snapshot_dates_all[0], snapshot_dates_all[-1]):
            values: dict[str, float] = {}
            rows = conn.execute("""SELECT s.investment_country, p.currency, SUM(COALESCE(p.total_fmv, p.units * COALESCE(p.per_unit_fmv, 0), 0)) value
                FROM positions p JOIN securities s ON s.id=p.security_id
                WHERE p.snapshot_date=(SELECT MAX(p2.snapshot_date) FROM positions p2 WHERE p2.account_id=p.account_id AND p2.snapshot_date<=?)
                GROUP BY s.investment_country, p.currency""", (cutoff,)).fetchall()
            for row in rows:
                values[row["investment_country"]] = values.get(row["investment_country"], 0) + (convert_amount(conn, row["value"], row["currency"], display_currency) or 0)
            for country in set(country_current) | set(values):
                earlier, _ = country_history.get(country, (0.0, 0.0))
                country_history[country] = (values.get(country, 0.0), values.get(country, 0.0)) if cutoff == snapshot_dates_all[0] else (earlier, values.get(country, 0.0))
    country_returns = []
    for country, values in sorted(country_current.items()):
        early, late = country_history.get(country, (values["value"], values["value"]))
        unrealized = values["value"] - values["cost"]
        country_returns.append(CountryReturn(country=country, current_market_value=values["value"], cost_basis=values["cost"], unrealized_return=unrealized, unrealized_return_percent=unrealized / values["cost"] * 100 if values["cost"] else None, earliest_snapshot_value=early, latest_snapshot_value=late, snapshot_value_change_percent=(late - early) / early * 100 if early else None))

    real_estate_rows = conn.execute(
        """
        SELECT currency, SUM(current_value) AS value
        FROM real_estate_assets
        GROUP BY currency
        """
    ).fetchall()
    real_estate_value = sum(
        convert_amount(conn, row["value"] or 0, row["currency"], display_currency) or 0
        for row in real_estate_rows
    )
    private_equity_value = sum(convert_amount(conn, row["value"] or 0, row["currency"], display_currency) or 0 for row in conn.execute(
        "SELECT currency, SUM(quantity * last_valuation_per_unit) AS value FROM private_equity_assets GROUP BY currency"
    ))
    total_assets = brokerage_value + static_accounts_value + real_estate_value + private_equity_value
    liability_rows = conn.execute("SELECT currency, SUM(outstanding_balance) AS value FROM liabilities GROUP BY currency").fetchall()
    total_liabilities = sum(convert_amount(conn, row["value"] or 0, row["currency"], display_currency) or 0 for row in liability_rows)
    total_net_worth = total_assets - total_liabilities

    net_worth_allocation = [AnalyticsPoint(label="Brokerage", value=brokerage_value)]
    for label in ["Bank Account", "Retirement Account", "Other"]:
        net_worth_allocation.append(AnalyticsPoint(label=label, value=static_category_totals.get(label, 0)))
    net_worth_allocation.append(AnalyticsPoint(label="Real Estate", value=real_estate_value))
    net_worth_allocation.append(AnalyticsPoint(label="Private Equity", value=private_equity_value))

    return DashboardAnalytics(
        display_currency=display_currency,
        brokerage_value=brokerage_value,
        static_accounts_value=static_accounts_value,
        real_estate_value=real_estate_value,
        private_equity_value=private_equity_value,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        total_net_worth=total_net_worth,
        total_value=total_net_worth,
        total_cost_basis=total_cost,
        unrealized_gain_loss=gain,
        unrealized_gain_loss_pct=pct,
        portfolio_growth=[TimeSeriesPoint(date=date, value=value) for date, value in sorted(growth_totals.items())],
        net_worth_growth=net_worth_snapshot_history(conn, display_currency),
        asset_allocation=[AnalyticsPoint(label=label, value=value) for label, value in sorted(asset_totals.items())],
        broker_allocation=[AnalyticsPoint(label=label, value=value) for label, value in sorted(broker_totals.items())],
        country_allocation=[AnalyticsPoint(label=label, value=value) for label, value in sorted(country_totals.items())],
        exchange_allocation=[AnalyticsPoint(label=label, value=value) for label, value in sorted(exchange_totals.items())],
        cash_vs_invested=[
            AnalyticsPoint(label="Cash", value=cash + bank_cash),
            AnalyticsPoint(label="Invested", value=invested),
        ],
        net_worth_allocation=[point for point in net_worth_allocation if point.value > 0],
        country_returns=country_returns,
    )
