# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import sqlite3

from backend.app.core.encryption import key_manager
from backend.app.services.fx_service import SUPPORTED_CURRENCIES, convert_amount, get_display_currency
from backend.app.services.models import (
    RealEstateAsset,
    RealEstateAssetCreate,
    RealEstateAssetUpdate,
    PrivateEquityAsset, PrivateEquityAssetCreate, PrivateEquityAssetUpdate,
    StaticAccount,
    StaticAccountCreate,
    StaticAccountUpdate,
    Liability, LiabilityCreate, LiabilityUpdate,
)
from backend.app.services.repositories import fingerprint_account, mask_account


STATIC_ACCOUNT_CATEGORIES = {"Bank Account", "Retirement Account", "Other"}
PRIVATE_EQUITY_STAGES = {"Pre-seed", "Seed", "Series A", "Series B", "Series C+", "Growth", "Secondary", "Other"}
LIABILITY_TYPES = {"Short-term Loan", "Long-term Loan", "Auto Loan", "Home Loan", "Education Loan", "Personal Loan", "Credit Card", "Other"}


def _validate_currency(currency: str) -> str:
    normalized = currency.upper()
    if normalized not in SUPPORTED_CURRENCIES:
        raise ValueError("Unsupported currency.")
    return normalized


def _validate_static_category(category: str) -> str:
    normalized = category.strip()
    if normalized not in STATIC_ACCOUNT_CATEGORIES:
        raise ValueError("Unsupported static account category.")
    return normalized


def _static_account_from_row(conn: sqlite3.Connection, row) -> StaticAccount:
    display_currency = get_display_currency(conn)
    return StaticAccount(
        id=row["id"],
        category=row["category"],
        entity_name=row["entity_name"],
        account_type=row["account_type"],
        account_holder=row["account_holder"],
        account_mask=row["account_mask"],
        currency=row["currency"],
        amount=row["amount"],
        amount_display=convert_amount(conn, row["amount"], row["currency"], display_currency) or 0,
        display_currency=display_currency,
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def list_static_accounts(conn: sqlite3.Connection) -> list[StaticAccount]:
    rows = conn.execute(
        """
        SELECT id, category, entity_name, account_type, account_holder, account_mask,
               currency, amount, notes, created_at, updated_at
        FROM static_accounts
        ORDER BY category, entity_name, account_type
        """
    ).fetchall()
    return [_static_account_from_row(conn, row) for row in rows]


def create_static_account(conn: sqlite3.Connection, payload: StaticAccountCreate) -> StaticAccount:
    category = _validate_static_category(payload.category)
    currency = _validate_currency(payload.currency)
    encrypted = key_manager.encrypt(payload.account_number.strip()) if payload.account_number else None
    cursor = conn.execute(
        """
        INSERT INTO static_accounts (
          category, entity_name, account_type, account_holder, account_number_enc,
          account_mask, account_fingerprint, currency, amount, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            category,
            payload.entity_name.strip(),
            payload.account_type.strip(),
            payload.account_holder.strip(),
            encrypted,
            mask_account(payload.account_number) if payload.account_number else None,
            fingerprint_account(payload.account_number) if payload.account_number else None,
            currency,
            payload.amount,
            payload.notes,
        ),
    )
    return get_static_account(conn, int(cursor.lastrowid))


def get_static_account(conn: sqlite3.Connection, account_id: int) -> StaticAccount:
    row = conn.execute(
        """
        SELECT id, category, entity_name, account_type, account_holder, account_mask,
               currency, amount, notes, created_at, updated_at
        FROM static_accounts
        WHERE id = ?
        """,
        (account_id,),
    ).fetchone()
    if not row:
        raise ValueError("Static account not found.")
    return _static_account_from_row(conn, row)


def update_static_account(conn: sqlite3.Connection, account_id: int, payload: StaticAccountUpdate) -> StaticAccount:
    category = _validate_static_category(payload.category)
    currency = _validate_currency(payload.currency)
    encrypted = key_manager.encrypt(payload.account_number.strip()) if payload.account_number else None
    conn.execute(
        """
        UPDATE static_accounts
        SET category = ?,
            entity_name = ?,
            account_type = ?,
            account_holder = ?,
            account_number_enc = COALESCE(?, account_number_enc),
            account_mask = COALESCE(?, account_mask),
            account_fingerprint = COALESCE(?, account_fingerprint),
            currency = ?,
            amount = ?,
            notes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            category,
            payload.entity_name.strip(),
            payload.account_type.strip(),
            payload.account_holder.strip(),
            encrypted,
            mask_account(payload.account_number) if payload.account_number else None,
            fingerprint_account(payload.account_number) if payload.account_number else None,
            currency,
            payload.amount,
            payload.notes,
            account_id,
        ),
    )
    return get_static_account(conn, account_id)


def delete_static_account(conn: sqlite3.Connection, account_id: int) -> None:
    cursor = conn.execute("DELETE FROM static_accounts WHERE id = ?", (account_id,))
    if cursor.rowcount == 0:
        raise ValueError("Static account not found.")


def _liability_from_row(conn: sqlite3.Connection, row) -> Liability:
    display = get_display_currency(conn)
    return Liability(id=row["id"], entity_name=row["entity_name"], liability_type=row["liability_type"], custom_type=row["custom_type"], account_reference_mask=row["account_reference_mask"], outstanding_balance=row["outstanding_balance"], currency=row["currency"], outstanding_balance_display=convert_amount(conn, row["outstanding_balance"], row["currency"], display) or 0, display_currency=display, notes=row["notes"], created_at=row["created_at"], updated_at=row["updated_at"])


def _validate_liability(payload: LiabilityCreate | LiabilityUpdate) -> tuple[str, str | None, str]:
    liability_type = payload.liability_type.strip()
    if liability_type not in LIABILITY_TYPES:
        raise ValueError("Select a supported liability type.")
    custom_type = payload.custom_type.strip() if payload.custom_type else None
    if liability_type == "Other" and not custom_type:
        raise ValueError("Specify a custom liability type when using Other.")
    return liability_type, custom_type if liability_type == "Other" else None, _validate_currency(payload.currency)


def list_liabilities(conn: sqlite3.Connection) -> list[Liability]:
    return [_liability_from_row(conn, row) for row in conn.execute("SELECT * FROM liabilities ORDER BY liability_type, entity_name")]


def get_liability(conn: sqlite3.Connection, liability_id: int) -> Liability:
    row = conn.execute("SELECT * FROM liabilities WHERE id=?", (liability_id,)).fetchone()
    if not row: raise ValueError("Liability not found.")
    return _liability_from_row(conn, row)


def create_liability(conn: sqlite3.Connection, payload: LiabilityCreate) -> Liability:
    liability_type, custom_type, currency = _validate_liability(payload); reference = payload.account_reference.strip() if payload.account_reference else None
    cursor = conn.execute("""INSERT INTO liabilities(entity_name, liability_type, custom_type, account_reference_enc, account_reference_mask, outstanding_balance, currency, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (payload.entity_name.strip(), liability_type, custom_type, key_manager.encrypt(reference) if reference else None, mask_account(reference) if reference else None, payload.outstanding_balance, currency, payload.notes))
    return get_liability(conn, int(cursor.lastrowid))


def update_liability(conn: sqlite3.Connection, liability_id: int, payload: LiabilityUpdate) -> Liability:
    liability_type, custom_type, currency = _validate_liability(payload); reference = payload.account_reference.strip() if payload.account_reference else None
    existing = conn.execute("SELECT account_reference_enc, account_reference_mask FROM liabilities WHERE id=?", (liability_id,)).fetchone()
    if not existing: raise ValueError("Liability not found.")
    encrypted_reference = None if payload.remove_account_reference else key_manager.encrypt(reference) if reference else existing["account_reference_enc"]
    reference_mask = None if payload.remove_account_reference else mask_account(reference) if reference else existing["account_reference_mask"]
    cursor = conn.execute("""UPDATE liabilities SET entity_name=?, liability_type=?, custom_type=?, account_reference_enc=?, account_reference_mask=?, outstanding_balance=?, currency=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""", (payload.entity_name.strip(), liability_type, custom_type, encrypted_reference, reference_mask, payload.outstanding_balance, currency, payload.notes, liability_id))
    if cursor.rowcount == 0: raise ValueError("Liability not found.")
    return get_liability(conn, liability_id)


def delete_liability(conn: sqlite3.Connection, liability_id: int) -> None:
    if conn.execute("DELETE FROM liabilities WHERE id=?", (liability_id,)).rowcount == 0: raise ValueError("Liability not found.")


def _real_estate_from_row(conn: sqlite3.Connection, row) -> RealEstateAsset:
    display_currency = get_display_currency(conn)
    return RealEstateAsset(
        id=row["id"],
        property_info=row["property_info"],
        entity_name=row["entity_name"],
        purchase_date=row["purchase_date"],
        purchase_value=row["purchase_value"],
        current_value=row["current_value"],
        purchase_value_display=convert_amount(conn, row["purchase_value"], row["currency"], display_currency) or 0,
        current_value_display=convert_amount(conn, row["current_value"], row["currency"], display_currency) or 0,
        currency=row["currency"],
        display_currency=display_currency,
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def list_real_estate_assets(conn: sqlite3.Connection) -> list[RealEstateAsset]:
    rows = conn.execute(
        """
        SELECT id, property_info, entity_name, purchase_date, purchase_value,
               current_value, currency, notes, created_at, updated_at
        FROM real_estate_assets
        ORDER BY property_info
        """
    ).fetchall()
    return [_real_estate_from_row(conn, row) for row in rows]


def create_real_estate_asset(conn: sqlite3.Connection, payload: RealEstateAssetCreate) -> RealEstateAsset:
    currency = _validate_currency(payload.currency)
    cursor = conn.execute(
        """
        INSERT INTO real_estate_assets (
          property_info, entity_name, purchase_date, purchase_value,
          current_value, currency, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.property_info.strip(),
            payload.entity_name.strip() if payload.entity_name else None,
            payload.purchase_date,
            payload.purchase_value,
            payload.current_value,
            currency,
            payload.notes,
        ),
    )
    return get_real_estate_asset(conn, int(cursor.lastrowid))


def get_real_estate_asset(conn: sqlite3.Connection, asset_id: int) -> RealEstateAsset:
    row = conn.execute(
        """
        SELECT id, property_info, entity_name, purchase_date, purchase_value,
               current_value, currency, notes, created_at, updated_at
        FROM real_estate_assets
        WHERE id = ?
        """,
        (asset_id,),
    ).fetchone()
    if not row:
        raise ValueError("Real estate asset not found.")
    return _real_estate_from_row(conn, row)


def update_real_estate_asset(conn: sqlite3.Connection, asset_id: int, payload: RealEstateAssetUpdate) -> RealEstateAsset:
    currency = _validate_currency(payload.currency)
    conn.execute(
        """
        UPDATE real_estate_assets
        SET property_info = ?,
            entity_name = ?,
            purchase_date = ?,
            purchase_value = ?,
            current_value = ?,
            currency = ?,
            notes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            payload.property_info.strip(),
            payload.entity_name.strip() if payload.entity_name else None,
            payload.purchase_date,
            payload.purchase_value,
            payload.current_value,
            currency,
            payload.notes,
            asset_id,
        ),
    )
    return get_real_estate_asset(conn, asset_id)


def delete_real_estate_asset(conn: sqlite3.Connection, asset_id: int) -> None:
    cursor = conn.execute("DELETE FROM real_estate_assets WHERE id = ?", (asset_id,))
    if cursor.rowcount == 0:
        raise ValueError("Real estate asset not found.")


def _private_equity_from_row(conn: sqlite3.Connection, row) -> PrivateEquityAsset:
    display = get_display_currency(conn)
    purchase = row["quantity"] * row["purchase_price_per_unit"]
    current = row["quantity"] * row["last_valuation_per_unit"]
    return PrivateEquityAsset(
        id=row["id"], company_name=row["company_name"], stage=row["stage"], share_class=row["share_class"],
        quantity=row["quantity"], purchase_price_per_unit=row["purchase_price_per_unit"], investment_date=row["investment_date"],
        last_valuation_per_unit=row["last_valuation_per_unit"], valuation_date=row["valuation_date"], ownership_percent=row["ownership_percent"],
        valuation_source=row["valuation_source"], currency=row["currency"], notes=row["notes"], purchase_value=purchase,
        current_value=current, unrealized_gain_loss=current-purchase,
        purchase_value_display=convert_amount(conn, purchase, row["currency"], display) or 0,
        current_value_display=convert_amount(conn, current, row["currency"], display) or 0,
        unrealized_gain_loss_display=convert_amount(conn, current-purchase, row["currency"], display) or 0,
        display_currency=display, created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _validate_private_equity(payload: PrivateEquityAssetCreate | PrivateEquityAssetUpdate) -> tuple[str, str, str]:
    stage = payload.stage.strip()
    if stage not in PRIVATE_EQUITY_STAGES and not stage.startswith("Other:"):
        raise ValueError("Use a preset private-equity stage or prefix a custom stage with 'Other:'.")
    share_class = payload.share_class.strip().title()
    if share_class not in {"Common", "Preferred"}:
        raise ValueError("Share class must be Common or Preferred.")
    return stage, share_class, _validate_currency(payload.currency)


def list_private_equity_assets(conn: sqlite3.Connection) -> list[PrivateEquityAsset]:
    return [_private_equity_from_row(conn, row) for row in conn.execute("SELECT * FROM private_equity_assets ORDER BY company_name")]


def get_private_equity_asset(conn: sqlite3.Connection, asset_id: int) -> PrivateEquityAsset:
    row = conn.execute("SELECT * FROM private_equity_assets WHERE id=?", (asset_id,)).fetchone()
    if not row:
        raise ValueError("Private equity asset not found.")
    return _private_equity_from_row(conn, row)


def create_private_equity_asset(conn: sqlite3.Connection, payload: PrivateEquityAssetCreate) -> PrivateEquityAsset:
    stage, share_class, currency = _validate_private_equity(payload)
    cursor = conn.execute("""INSERT INTO private_equity_assets(company_name,stage,share_class,quantity,purchase_price_per_unit,investment_date,last_valuation_per_unit,valuation_date,ownership_percent,valuation_source,currency,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (payload.company_name.strip(), stage, share_class, payload.quantity, payload.purchase_price_per_unit,
        payload.investment_date, payload.last_valuation_per_unit, payload.valuation_date, payload.ownership_percent, payload.valuation_source, currency, payload.notes))
    return get_private_equity_asset(conn, int(cursor.lastrowid))


def update_private_equity_asset(conn: sqlite3.Connection, asset_id: int, payload: PrivateEquityAssetUpdate) -> PrivateEquityAsset:
    stage, share_class, currency = _validate_private_equity(payload)
    cursor = conn.execute("""UPDATE private_equity_assets SET company_name=?,stage=?,share_class=?,quantity=?,purchase_price_per_unit=?,investment_date=?,last_valuation_per_unit=?,valuation_date=?,ownership_percent=?,valuation_source=?,currency=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
        (payload.company_name.strip(),stage,share_class,payload.quantity,payload.purchase_price_per_unit,payload.investment_date,payload.last_valuation_per_unit,payload.valuation_date,payload.ownership_percent,payload.valuation_source,currency,payload.notes,asset_id))
    if cursor.rowcount == 0: raise ValueError("Private equity asset not found.")
    return get_private_equity_asset(conn, asset_id)


def delete_private_equity_asset(conn: sqlite3.Connection, asset_id: int) -> None:
    if conn.execute("DELETE FROM private_equity_assets WHERE id=?", (asset_id,)).rowcount == 0:
        raise ValueError("Private equity asset not found.")
