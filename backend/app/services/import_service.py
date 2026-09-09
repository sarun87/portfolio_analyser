from backend.app.services.csv_importer import derive_per_unit_and_total, preview_with_mapping, sanitize_acquisition_date
from backend.app.services.models import ImportCommitRequest, ImportReconciliationRow, ImportResult, ImportPreview
from backend.app.services.repositories import fingerprint_account, get_or_create_account, get_broker, get_or_create_security, import_exists, insert_import


FIELDS = ["security_name", "symbol", "security_type", "allocation_category", "sector", "exchange", "investment_country", "acquisition_date", "lot_number", "units", "per_unit_cost_basis", "total_cost_basis", "per_unit_fmv", "total_fmv", "currency"]

def _key(account_id, symbol, lot, acquisition_date, per_unit_cost_basis):
    """Return the stable identity of a holding row within an account.

    Many brokers do not provide a tax-lot identifier.  For those statements,
    acquisition date and cost per unit distinguish otherwise identical lots.
    ``None`` remains a distinct, supported value for statements without cost
    information; it must not be replaced with zero.
    """
    return (
        account_id,
        (symbol or "").strip().upper(),
        (lot or "").strip(),
        sanitize_acquisition_date(acquisition_date) or "",
        per_unit_cost_basis,
    )
def _row_values(row): return {field: getattr(row, field) for field in FIELDS}

def _current_rows(conn, broker_id, account_ids):
    if not account_ids: return {}
    marks = ",".join("?" for _ in account_ids)
    rows = conn.execute(f"""SELECT p.*, s.name security_name, s.symbol, s.security_type, s.allocation_category, s.sector, s.exchange, s.investment_country
      FROM positions p JOIN securities s ON s.id=p.security_id
      WHERE p.account_id IN ({marks}) AND p.snapshot_date=(SELECT MAX(q.snapshot_date) FROM positions q WHERE q.account_id=p.account_id)""", account_ids).fetchall()
    return {_key(r["account_id"], r["symbol"], r["lot_number"], r["acquisition_date"], r["per_unit_cost_basis"]): r for r in rows}

def _reconcile(conn, preview: ImportPreview):
    broker = get_broker(conn, preview.broker_id)
    accounts = {}
    for row in preview.rows:
        found = conn.execute("SELECT id FROM accounts WHERE broker_id=? AND account_fingerprint=?", (preview.broker_id, fingerprint_account(row.account_number))).fetchone()
        accounts[row.account_number or "UNKNOWN"] = found["id"] if found else None
    current = _current_rows(conn, preview.broker_id, [item for item in accounts.values() if item])
    incoming = {}
    for row in preview.rows:
        account_id = accounts[row.account_number or "UNKNOWN"]
        if account_id: incoming[_key(account_id, row.symbol, row.lot_number, row.acquisition_date, row.per_unit_cost_basis)] = row
    new, modified = [], []
    for row in preview.rows:
        account_id = accounts[row.account_number or "UNKNOWN"]
        existing = current.get(_key(account_id, row.symbol, row.lot_number, row.acquisition_date, row.per_unit_cost_basis)) if account_id else None
        if not existing: new.append(row); continue
        proposed = _row_values(row); old = {field: existing[field] for field in FIELDS}
        changed = [field for field in FIELDS if old[field] != proposed[field]]
        if changed: modified.append(ImportReconciliationRow(row_number=row.row_number, current_values=old, proposed_values=proposed, changed_fields=changed))
    ignored = {(item.raw_values.get("account_number") or "UNKNOWN", (item.raw_values.get("symbol") or "").strip().upper(), (item.raw_values.get("lot_number") or "").strip(), sanitize_acquisition_date(item.raw_values.get("acquisition_date")) or "") for item in preview.ignored_rows}
    deleted = []
    for key, existing in current.items():
        account_name = next((name for name, ident in accounts.items() if ident == key[0]), "UNKNOWN")
        # Ignored rows may be invalid before a cost basis can be derived, so
        # their preservation key intentionally excludes the new cost element.
        if key not in incoming and (account_name, key[1], key[2], key[3]) not in ignored:
            values = {field: existing[field] for field in FIELDS}; deleted.append(ImportReconciliationRow(current_values=values, proposed_values={}, changed_fields=[]))
    preview.new_rows, preview.modified_rows, preview.deleted_rows = new, modified, deleted
    return accounts, current

def preview_statement(conn, request) -> ImportPreview:
    broker = get_broker(conn, request.broker_id)
    if not broker: raise ValueError("Broker not found.")
    preview = preview_with_mapping(conn, broker, broker["header_signature"], broker["mappings"], request.csv_text, request.statement_date, request.statement_currency, request.locked_fields, request.row_overrides, request.ignored_row_numbers)
    if not preview.errors:
        # Same-date imports are rejected before a potentially misleading reconciliation preview.
        for row in preview.rows:
            account = conn.execute("SELECT id FROM accounts WHERE broker_id=? AND account_fingerprint=?", (request.broker_id, fingerprint_account(row.account_number))).fetchone()
            if account and conn.execute("SELECT 1 FROM positions WHERE account_id=? AND snapshot_date=? LIMIT 1", (account["id"], preview.statement_date)).fetchone():
                preview.errors.append(f"Account {row.account_number or 'UNKNOWN'} already has an import for {preview.statement_date}.")
                break
    if not preview.errors: _reconcile(conn, preview)
    return preview

def commit_statement(conn, request: ImportCommitRequest) -> ImportResult:
    preview = preview_statement(conn, request)
    if request.expected_configuration_version != preview.configuration_version: raise ValueError("Broker configuration changed or preview is stale. Refresh the preview before committing.")
    if preview.duplicate or import_exists(conn, preview.fingerprint): return ImportResult(import_id=0, imported_rows=0, duplicate=True)
    if preview.errors or preview.invalid_rows: raise ValueError("Import preview has unresolved layout, mapping, or row validation errors.")
    if not preview.rows: raise ValueError("No valid rows to import.")
    accounts, current = _reconcile(conn, preview)
    first = None
    for row in preview.rows:
        name = row.account_number or "UNKNOWN"
        if not accounts[name]: accounts[name] = get_or_create_account(conn, request.broker_id, row.account_number)
        first = first or accounts[name]
    import_id = insert_import(conn, broker_id=request.broker_id, account_id=first, statement_date=preview.statement_date, source_filename=request.filename, row_count=len(preview.rows), fingerprint=preview.fingerprint, detected_columns=preview.detected_columns, errors=[], locked_fields=preview.locked_fields)
    changed_keys = set()
    for row in preview.rows:
        account_id = accounts[row.account_number or "UNKNOWN"]; key = _key(account_id, row.symbol, row.lot_number, row.acquisition_date, row.per_unit_cost_basis); existing = current.get(key)
        security_id = get_or_create_security(conn, name=row.security_name, security_type=row.security_type, symbol=row.symbol, exchange=row.exchange, investment_country=row.investment_country, location_source=row.location_status)
        from backend.app.services.allocation_category_service import register_category
        register_category(conn, row.allocation_category)
        conn.execute("UPDATE securities SET allocation_category=?, sector=? WHERE id=?", (row.allocation_category, row.sector, security_id))
        pcb, tcb = derive_per_unit_and_total(row.units, row.per_unit_cost_basis, row.total_cost_basis); pfmv, tfmv = derive_per_unit_and_total(row.units, row.per_unit_fmv, row.total_fmv)
        if existing:
            conn.execute("""UPDATE positions SET import_id=?, security_id=?, snapshot_date=?, acquisition_date=?, lot_number=?, units=?, per_unit_cost_basis=?, total_cost_basis=?, per_unit_fmv=?, total_fmv=?, currency=? WHERE id=?""", (import_id, security_id, preview.statement_date, row.acquisition_date, row.lot_number, row.units, pcb, tcb, pfmv, tfmv, row.currency, existing["id"])); changed_keys.add(key)
        else:
            conn.execute("INSERT INTO positions (import_id,account_id,security_id,snapshot_date,acquisition_date,lot_number,units,per_unit_cost_basis,total_cost_basis,per_unit_fmv,total_fmv,currency) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (import_id, account_id, security_id, preview.statement_date, row.acquisition_date, row.lot_number, row.units, pcb, tcb, pfmv, tfmv, row.currency))
    deleted = 0
    ignored = {(item.raw_values.get("account_number") or "UNKNOWN", (item.raw_values.get("symbol") or "").strip().upper(), (item.raw_values.get("lot_number") or "").strip(), sanitize_acquisition_date(item.raw_values.get("acquisition_date")) or "") for item in preview.ignored_rows}
    for key, existing in current.items():
        account_name = next((name for name, ident in accounts.items() if ident == key[0]), "UNKNOWN")
        # See the matching comment in _reconcile: ignored invalid rows do not
        # necessarily have a usable per-unit cost basis.
        if key not in changed_keys and (account_name, key[1], key[2], key[3]) not in ignored:
            conn.execute("DELETE FROM positions WHERE id=?", (existing["id"],)); deleted += 1
    return ImportResult(import_id=import_id, imported_rows=len(preview.rows), duplicate=False, added_rows=len(preview.new_rows), modified_rows=len(preview.modified_rows), deleted_rows=deleted)
