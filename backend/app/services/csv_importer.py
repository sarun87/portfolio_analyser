from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date
from typing import Any, Optional

from backend.app.services.classification_service import fallback_category
from backend.app.services.location_service import resolve_security_location
from backend.app.services.models import ImportPreview, InvalidRow, PreviewRow
from backend.app.services.repositories import fingerprint_account, import_exists

CANONICAL_FIELDS = ["account_number", "security_name", "symbol", "security_type", "allocation_category", "sector", "acquisition_date", "lot_number", "units", "per_unit_cost_basis", "total_cost_basis", "per_unit_fmv", "total_fmv", "currency", "exchange", "investment_country"]
LOCKABLE_FIELDS = set(CANONICAL_FIELDS) - {"account_number"}
EDITABLE_REPAIR_FIELDS = {"symbol", "units", "per_unit_cost_basis", "total_cost_basis"}
ALIASES = {
    "account_number": ["account number", "account", "account id", "client account id"], "security_name": ["security name", "description", "security description", "name"],
    "symbol": ["symbol", "ticker", "ticker symbol"], "security_type": ["security type", "asset type", "asset class", "type"], "units": ["quantity", "units", "shares", "qty", "position"],
    "per_unit_cost_basis": ["per unit cost basis", "cost basis per share", "cost basis price"], "total_cost_basis": ["total cost basis", "cost basis", "cost basis money"],
    "per_unit_fmv": ["per unit fmv", "current price", "mark price", "price"], "total_fmv": ["total fmv", "market value", "position value", "value"],
    "currency": ["currency", "ccy"], "exchange": ["exchange", "listing exchange"], "investment_country": ["investment country", "country", "domicile"],
    "allocation_category": ["allocation category"], "sector": ["sector"], "acquisition_date": ["acquisition date", "purchase date"], "lot_number": ["lot number", "lot", "tax lot"],
}

def normalize_header(value: str) -> str: return re.sub(r"[^a-z0-9]+", " ", value.strip().lower()).strip()
def clean_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None
def parse_number(value: Any) -> Optional[float]:
    text = clean_text(value)
    if not text or text in {"-", "--", "N/A", "n/a"}: return None
    negative = text.startswith("(") and text.endswith(")")
    try: number = float(text.strip("()").replace("$", "").replace(",", "").replace("%", ""))
    except ValueError: return None
    return -number if negative else number
def suggest_mapping(headers: list[str]) -> dict[str, str]:
    originals = {normalize_header(h): h for h in headers}
    return {field: originals[normalize_header(alias)] for field, aliases in ALIASES.items() for alias in aliases if normalize_header(alias) in originals}
def csv_records(text: str) -> list[list[str]]: return list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))

def flat_records(text: str, signature: list[str]) -> tuple[list[str], list[dict[str, str]], int]:
    records = csv_records(text)
    candidates = [(i, [x.strip() for x in row]) for i, row in enumerate(records) if any(x.strip() for x in row)]
    normalized_signature = {normalize_header(item) for item in signature}
    if normalized_signature:
        match = next(((i, row) for i, row in candidates if normalized_signature <= {normalize_header(x) for x in row}), None)
    else:
        match = max(candidates[:25], key=lambda item: len(suggest_mapping(item[1])), default=None)
    if not match: return [], [], 0
    index, headers = match
    rows = []
    for record in records[index + 1:]:
        if not any(x.strip() for x in record): continue
        padded = record + [""] * max(0, len(headers) - len(record))
        rows.append(dict(zip(headers, padded[:len(headers)])))
    return headers, rows, index + 2

def derive_per_unit_and_total(units: float, per_unit_value: Optional[float], total_value: Optional[float]):
    if units:
        if per_unit_value is None and total_value is not None: per_unit_value = total_value / units
        if total_value is None and per_unit_value is not None: total_value = per_unit_value * units
    return per_unit_value, total_value

def normalize_row(raw: dict[str, str], mapping: dict[str, str], row_number: int, statement_currency: str, override: Optional[dict[str, Optional[str]]] = None):
    override = override or {}
    def source_value(field: str): return clean_text(raw.get(mapping[field])) if mapping.get(field) else None
    def value(field: str): return clean_text(override[field]) if field in override else source_value(field)
    raw_values = {field: source_value(field) for field in mapping}
    errors: dict[str, list[str]] = {}
    def fail(field: str, message: str): errors.setdefault(field, []).append(message)
    symbol = value("symbol")
    if not symbol: fail("symbol", "Symbol is required.")
    units = parse_number(value("units"))
    if units is None: fail("units", "Units must be a number.")
    cost_values = {}
    for field in ("per_unit_cost_basis", "total_cost_basis"):
        if mapping.get(field):
            cost_values[field] = parse_number(value(field))
            if cost_values[field] is None: fail(field, "Cost basis must be a number when this field is mapped.")
        else: cost_values[field] = None
    currency = (value("currency") or statement_currency).upper()
    if currency not in {"USD", "INR", "GBP", "EUR"}: fail("currency", f"Unsupported currency {currency}.")
    editable_values = {field: value(field) for field in EDITABLE_REPAIR_FIELDS if mapping.get(field) or field in override}
    if errors:
        return None, InvalidRow(row_number=row_number, raw_values=raw_values, field_errors=errors, editable_values=editable_values)
    assert units is not None and symbol is not None
    name = value("security_name") or symbol
    kind = value("security_type") or ("Cash" if name.lower() == "cash" else "Other")
    exchange, country, source = resolve_security_location(symbol, value("exchange"))
    if value("investment_country"): country, source = value("investment_country"), "statement"
    pcb, tcb = derive_per_unit_and_total(units, cost_values["per_unit_cost_basis"], cost_values["total_cost_basis"])
    pfmv, tfmv = derive_per_unit_and_total(units, parse_number(value("per_unit_fmv")), parse_number(value("total_fmv")))
    return PreviewRow(row_number=row_number, account_number=value("account_number"), security_name=name, symbol=symbol, security_type=kind, allocation_category=value("allocation_category") or fallback_category(symbol, name, kind), sector=value("sector") or "Unclassified", acquisition_date=value("acquisition_date"), lot_number=value("lot_number"), units=units, per_unit_cost_basis=pcb, total_cost_basis=tcb, per_unit_fmv=pfmv, total_fmv=tfmv, currency=currency, exchange=exchange, investment_country=country, location_status=source), None

def apply_locked_fields(conn, broker_id: int, rows: list[PreviewRow], locked_fields: list[str]) -> list[PreviewRow]:
    protected = set(locked_fields) & LOCKABLE_FIELDS; result = []
    for row in rows:
        if not protected: result.append(row); continue
        previous = conn.execute("""SELECT p.*, s.name security_name, s.symbol, s.security_type, s.allocation_category, s.sector, s.exchange, s.investment_country, s.location_source previous_location_status FROM positions p JOIN accounts a ON a.id=p.account_id JOIN securities s ON s.id=p.security_id WHERE a.broker_id=? AND a.account_fingerprint=? AND COALESCE(s.symbol,'')=COALESCE(?, '') AND COALESCE(p.lot_number,'')=COALESCE(?, '') ORDER BY CASE WHEN s.exchange=? THEN 0 ELSE 1 END, p.snapshot_date DESC, p.id DESC LIMIT 1""", (broker_id, fingerprint_account(row.account_number), row.symbol.upper().strip() if row.symbol else None, row.lot_number, row.exchange)).fetchone()
        if not previous: result.append(row); continue
        updates = {field: previous[field] for field in protected}
        if protected & {"exchange", "investment_country"}: updates["location_status"] = previous["previous_location_status"] or "locked-prior-snapshot"
        result.append(row.model_copy(update=updates))
    return result

def build_fingerprint(broker_id: int, statement_date: str, currency: str, rows: list[PreviewRow]) -> str:
    return hashlib.sha256(json.dumps({"broker": broker_id, "date": statement_date, "currency": currency, "rows": [r.model_dump() for r in rows]}, sort_keys=True).encode()).hexdigest()

def preview_with_mapping(conn, broker: dict, header_signature: list[str], mappings: dict[str, str], csv_text: str, statement_date: Optional[str], statement_currency: Optional[str], locked_fields: Optional[list[str]], row_overrides: Optional[dict[int, dict[str, Optional[str]]]] = None, ignored_row_numbers: Optional[list[int]] = None) -> ImportPreview:
    currency = (statement_currency or broker.get("default_currency") or "USD").upper(); errors = []
    headers, raw_rows, start = flat_records(csv_text, header_signature)
    if not headers: errors.append("Configured CSV header layout was not found.")
    unknown = set(mappings) - set(CANONICAL_FIELDS)
    if unknown: errors.append("Mappings contain unknown fields.")
    if not mappings.get("symbol") or not mappings.get("units"): errors.append("Symbol and units mappings are required.")
    if headers and any(column not in headers for column in mappings.values()): errors.append("One or more mapped columns are not present in the CSV header.")
    rows: list[PreviewRow] = []; invalid_rows: list[InvalidRow] = []; ignored_rows: list[InvalidRow] = []
    ignored = set(ignored_row_numbers or [])
    if not errors:
        for number, raw in enumerate(raw_rows, start=start):
            row, invalid = normalize_row(raw, mappings, number, currency, (row_overrides or {}).get(number))
            if invalid and number in ignored: ignored_rows.append(invalid)
            elif invalid: invalid_rows.append(invalid)
            elif row: rows.append(row)
    effective_locks = sorted(set(broker.get("locked_fields", []) if locked_fields is None else locked_fields) & LOCKABLE_FIELDS)
    rows = apply_locked_fields(conn, broker["id"], rows, effective_locks)
    effective_date = statement_date or date.today().isoformat(); fingerprint = build_fingerprint(broker["id"], effective_date, currency, rows)
    return ImportPreview(broker_id=broker["id"], broker_name=broker["name"], configuration_version=broker["configuration_version"], statement_date=effective_date, detected_columns=headers, suggested_mapping=mappings, rows=rows, invalid_rows=invalid_rows, ignored_rows=ignored_rows, errors=errors, duplicate=import_exists(conn, fingerprint), fingerprint=fingerprint, locked_fields=effective_locks)
