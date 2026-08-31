from backend.app.core.encryption import generate_salt, key_manager
from backend.app.db.schema import init_db
from backend.app.services.broker_service import delete_broker, preview_broker_configuration, save_broker
from backend.app.services.import_service import commit_statement, preview_statement
from backend.app.services.insight_service import insights
from backend.app.services.models import BrokerDraft, ImportCommitRequest, ImportPreviewRequest
from backend.app.services.portfolio_service import dashboard


CSV = """Account,Symbol,Name,Quantity,Value\nACC-1,AAA,Alpha,2,20\n"""


def configured_broker(conn, *, name="Test Broker", locked_fields=None):
    draft = BrokerDraft(
        name=name,
        default_currency="USD",
        locked_fields=locked_fields or [],
        header_signature=["Account", "Symbol", "Quantity"],
        mappings={"account_number": "Account", "symbol": "Symbol", "security_name": "Name", "units": "Quantity", "total_fmv": "Value"},
    )
    preview = preview_broker_configuration(conn, draft, CSV, "USD")
    assert preview.valid, preview.errors
    return save_broker(conn, draft, preview)


def unlock_for_imports():
    key_manager.setup("correct horse battery staple", generate_salt())


def test_broker_preview_save_and_flat_parsing(sqlite_conn):
    init_db(sqlite_conn)
    draft = BrokerDraft(name="Flat broker", header_signature=["Ticker", "Qty"], mappings={"symbol": "Ticker", "units": "Qty"})
    csv = "Ticker,Qty\nAAA,2\nBBB,3\n"
    preview = preview_broker_configuration(sqlite_conn, draft, csv, "USD")
    assert preview.valid
    assert [row.security_name for row in preview.rows] == ["AAA", "BBB"]
    broker = save_broker(sqlite_conn, draft, preview)
    imported_preview = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=broker["id"], csv_text=csv))
    assert not imported_preview.errors
    assert len(imported_preview.rows) == 2


def test_broker_draft_accepts_partial_or_no_mappings(sqlite_conn):
    init_db(sqlite_conn)
    partial = save_broker(sqlite_conn, BrokerDraft(name="Partial", header_signature=["Ticker"], mappings={"symbol": "Ticker"}), None)
    empty = save_broker(sqlite_conn, BrokerDraft(name="Empty"), None)
    assert partial["mappings"] == {"symbol": "Ticker"}
    assert empty["header_signature"] == []


def test_import_version_conflict_and_downstream_aggregations(sqlite_conn):
    init_db(sqlite_conn)
    unlock_for_imports()
    broker = configured_broker(sqlite_conn)
    preview = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=broker["id"], csv_text=CSV, statement_date="2026-06-30"))
    result = commit_statement(sqlite_conn, ImportCommitRequest(broker_id=broker["id"], csv_text=CSV, statement_date="2026-06-30", expected_configuration_version=preview.configuration_version))
    assert result.imported_rows == 1
    # Dashboard and insights aggregate current positions, independent of the
    # broker section that produced the position.
    assert dashboard(sqlite_conn).brokerage_value == 20
    assert insights(sqlite_conn).concentration[0].label == "Alpha"
    updated = BrokerDraft(name="Test Broker", header_signature=["Account", "Symbol", "Quantity"], mappings={"account_number": "Account", "symbol": "Symbol", "security_name": "Name", "units": "Quantity", "total_fmv": "Value"})
    refreshed = preview_broker_configuration(sqlite_conn, updated, CSV, "USD")
    save_broker(sqlite_conn, updated, refreshed, broker["id"])
    try:
        commit_statement(sqlite_conn, ImportCommitRequest(broker_id=broker["id"], csv_text=CSV, statement_date="2026-07-31", expected_configuration_version=preview.configuration_version))
        assert False, "stale previews must not commit"
    except ValueError as exc:
        assert "stale" in str(exc).lower() or "changed" in str(exc).lower()


def test_one_off_lock_is_not_persisted_and_delete_guard(sqlite_conn):
    init_db(sqlite_conn)
    unlock_for_imports()
    broker = configured_broker(sqlite_conn)
    first = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=broker["id"], csv_text=CSV, statement_date="2026-06-30"))
    commit_statement(sqlite_conn, ImportCommitRequest(broker_id=broker["id"], csv_text=CSV, statement_date="2026-06-30", expected_configuration_version=first.configuration_version))
    changed = "Account,Symbol,Name,Quantity,Value\nACC-1,AAA,Changed name,2,30\n"
    preview = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=broker["id"], csv_text=changed, statement_date="2026-07-31", locked_fields=["security_name"]))
    assert preview.rows[0].security_name == "Alpha"
    assert preview.locked_fields == ["security_name"]
    assert broker["locked_fields"] == []
    try:
        delete_broker(sqlite_conn, broker["id"])
        assert False, "latest positions must prevent deletion"
    except ValueError as exc:
        assert "latest snapshot" in str(exc)


def test_invalid_rows_are_repairable_only_for_the_current_import(sqlite_conn):
    init_db(sqlite_conn)
    broker = configured_broker(sqlite_conn)
    csv = "Account,Symbol,Name,Quantity,Value\nACC-1,,Alpha,bad,20\n"
    preview = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=broker["id"], csv_text=csv))
    assert not preview.rows
    assert preview.invalid_rows[0].field_errors.keys() >= {"symbol", "units"}
    repaired = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=broker["id"], csv_text=csv, row_overrides={2: {"symbol": "AAA", "units": "2"}}))
    assert len(repaired.rows) == 1
    assert not repaired.invalid_rows
    assert broker["mappings"]["symbol"] == "Symbol"


def test_invalid_rows_can_be_ignored_for_one_import(sqlite_conn):
    init_db(sqlite_conn)
    unlock_for_imports()
    broker = configured_broker(sqlite_conn)
    csv = "Account,Symbol,Name,Quantity,Value\nACC-1,AAA,Alpha,2,20\nACC-1,,Broken,bad,20\n"
    preview = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=broker["id"], csv_text=csv, statement_date="2026-08-01", ignored_row_numbers=[3]))
    assert len(preview.rows) == 1
    assert not preview.invalid_rows
    assert [row.row_number for row in preview.ignored_rows] == [3]
    result = commit_statement(sqlite_conn, ImportCommitRequest(broker_id=broker["id"], csv_text=csv, statement_date="2026-08-01", ignored_row_numbers=[3], expected_configuration_version=preview.configuration_version))
    assert result.imported_rows == 1


def test_later_import_reconciles_adds_updates_and_deletes(sqlite_conn):
    init_db(sqlite_conn)
    unlock_for_imports()
    broker = configured_broker(sqlite_conn)
    first = "Account,Symbol,Name,Quantity,Value\nACC-1,AAA,Alpha,2,20\nACC-1,BBB,Beta,4,40\n"
    first_preview = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=broker["id"], csv_text=first, statement_date="2026-06-30"))
    commit_statement(sqlite_conn, ImportCommitRequest(broker_id=broker["id"], csv_text=first, statement_date="2026-06-30", expected_configuration_version=first_preview.configuration_version))
    second = "Account,Symbol,Name,Quantity,Value\nACC-1,AAA,Alpha,3,30\nACC-1,CCC,Gamma,1,10\n"
    preview = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=broker["id"], csv_text=second, statement_date="2026-07-31"))
    assert len(preview.new_rows) == len(preview.modified_rows) == len(preview.deleted_rows) == 1
    result = commit_statement(sqlite_conn, ImportCommitRequest(broker_id=broker["id"], csv_text=second, statement_date="2026-07-31", expected_configuration_version=preview.configuration_version))
    assert (result.added_rows, result.modified_rows, result.deleted_rows) == (1, 1, 1)


def test_import_strips_acquisition_date_postfix_before_preview_and_reconciliation(sqlite_conn):
    init_db(sqlite_conn)
    unlock_for_imports()
    csv = "Account,Symbol,Name,Quantity,Value,Purchase Date,Lot\nACC-1,AAA,Alpha,2,20,20260823;043233,L1\n"
    draft = BrokerDraft(
        name="Dated broker", default_currency="USD", header_signature=["Account", "Symbol", "Quantity"],
        mappings={"account_number": "Account", "symbol": "Symbol", "security_name": "Name", "units": "Quantity", "total_fmv": "Value", "acquisition_date": "Purchase Date", "lot_number": "Lot"},
    )
    saved = save_broker(sqlite_conn, draft, preview_broker_configuration(sqlite_conn, draft, csv, "USD"))
    first = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=saved["id"], csv_text=csv, statement_date="2026-08-31"))
    assert first.rows[0].acquisition_date == "20260823"
    commit_statement(sqlite_conn, ImportCommitRequest(broker_id=saved["id"], csv_text=csv, statement_date="2026-08-31", expected_configuration_version=first.configuration_version))

    updated_csv = csv.replace("2,20", "3,30")
    second = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=saved["id"], csv_text=updated_csv, statement_date="2026-09-30"))
    assert (len(second.new_rows), len(second.modified_rows), len(second.deleted_rows)) == (0, 1, 0)
    commit_statement(sqlite_conn, ImportCommitRequest(broker_id=saved["id"], csv_text=updated_csv, statement_date="2026-09-30", expected_configuration_version=second.configuration_version))
    position = sqlite_conn.execute("SELECT acquisition_date, units FROM positions").fetchone()
    assert tuple(position) == ("20260823", 3)
