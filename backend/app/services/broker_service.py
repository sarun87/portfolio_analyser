from __future__ import annotations

import json
import sqlite3

from backend.app.services.csv_importer import CANONICAL_FIELDS, LOCKABLE_FIELDS, flat_records, preview_with_mapping, suggest_mapping
from backend.app.services.models import BrokerConfigPreview, BrokerDraft
from backend.app.services.repositories import get_broker


def _validate(draft: BrokerDraft, require_import_mapping: bool = True) -> list[str]:
    errors = []
    if not draft.name.strip(): errors.append("Broker name is required.")
    if draft.default_currency.upper() not in {"USD", "INR", "GBP", "EUR"}: errors.append("Unsupported default currency.")
    if set(draft.locked_fields) - LOCKABLE_FIELDS: errors.append("Locked fields contain unsupported values.")
    if require_import_mapping and not draft.header_signature: errors.append("A CSV header signature is required.")
    if require_import_mapping and (not draft.mappings.get("symbol") or not draft.mappings.get("units")): errors.append("Symbol and units mappings are required.")
    if set(draft.mappings) - set(CANONICAL_FIELDS): errors.append("Mappings contain unknown fields.")
    return errors


def preview_broker_configuration(conn: sqlite3.Connection, draft: BrokerDraft, csv_text: str, statement_currency: str | None) -> BrokerConfigPreview:
    headers, _, _ = flat_records(csv_text, draft.header_signature)
    signature = draft.header_signature or headers
    mappings = draft.mappings or suggest_mapping(headers)
    temporary = {"id": -1, "name": draft.name, "default_currency": draft.default_currency, "locked_fields": draft.locked_fields, "configuration_version": 0}
    result = preview_with_mapping(conn, temporary, signature, mappings, csv_text, None, statement_currency, draft.locked_fields)
    normalized_draft = draft.model_copy(update={"header_signature": signature, "mappings": mappings})
    errors = list(dict.fromkeys(_validate(normalized_draft) + result.errors))
    return BrokerConfigPreview(header_signature=signature, detected_headers=headers, mappings=mappings, rows=result.rows, invalid_rows=result.invalid_rows, errors=errors, valid=bool(result.rows) and not errors)


def save_broker(conn: sqlite3.Connection, draft: BrokerDraft, preview: BrokerConfigPreview | None, broker_id: int | None = None) -> dict:
    effective = draft.model_copy(update={"header_signature": preview.header_signature, "mappings": preview.mappings}) if preview else draft
    # A broker can be intentionally saved as an incomplete draft. Import
    # preview/commit are the strict boundary for required mappings.
    errors = _validate(effective, require_import_mapping=False)
    if errors: raise ValueError(" ".join(errors))
    values = (effective.name.strip(), effective.default_currency.upper(), effective.notes, json.dumps(sorted(set(effective.locked_fields))), json.dumps(effective.header_signature), json.dumps(effective.mappings))
    if broker_id is None:
        cursor = conn.execute("INSERT INTO brokers (name, default_currency, notes, locked_fields_json, header_signature_json, mappings_json) VALUES (?, ?, ?, ?, ?, ?)", values)
        broker_id = cursor.lastrowid
    else:
        if not get_broker(conn, broker_id): raise ValueError("Broker not found.")
        conn.execute("UPDATE brokers SET name=?, default_currency=?, notes=?, locked_fields_json=?, header_signature_json=?, mappings_json=?, configuration_version=configuration_version+1 WHERE id=?", (*values, broker_id))
    return get_broker(conn, broker_id)


def delete_broker(conn: sqlite3.Connection, broker_id: int) -> None:
    broker = get_broker(conn, broker_id)
    if not broker: raise ValueError("Broker not found.")
    active = conn.execute("""SELECT 1 FROM positions p JOIN accounts a ON a.id=p.account_id WHERE a.broker_id=? AND p.snapshot_date=(SELECT MAX(p2.snapshot_date) FROM positions p2 WHERE p2.account_id=p.account_id) LIMIT 1""", (broker_id,)).fetchone()
    if active: raise ValueError("Broker cannot be deleted while an account has a latest snapshot.")
    conn.execute("DELETE FROM statement_imports WHERE broker_id=?", (broker_id,))
    conn.execute("DELETE FROM accounts WHERE broker_id=?", (broker_id,))
    conn.execute("DELETE FROM brokers WHERE id=?", (broker_id,))
