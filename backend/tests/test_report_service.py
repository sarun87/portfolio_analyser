import sqlite3
from types import SimpleNamespace

from backend.app.db.schema import init_db
from backend.app.services.models import ReportRequest
from backend.app.services.report_service import _component_rows, generate_report


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_summary_component_totals_include_every_net_worth_category():
    analytics = SimpleNamespace(
        display_currency="USD",
        brokerage_value=100,
        real_estate_value=300,
        private_equity_value=400,
        net_worth_allocation=[
            SimpleNamespace(label="Bank Account", value=20),
            SimpleNamespace(label="Retirement Account", value=30),
            SimpleNamespace(label="Other", value=40),
        ],
    )

    assert _component_rows(analytics) == [
        ["Brokerage", "$100.00"], ["Bank Account", "$20.00"],
        ["Retirement Account", "$30.00"], ["Other", "$40.00"],
        ["Real Estate", "$300.00"], ["Private Equity", "$400.00"],
    ]


def test_summary_is_one_page_and_detail_includes_summary_before_appendix():
    conn = _connection()
    try:
        summary = generate_report(conn, ReportRequest(title="Test report", report_type="summary"))
        detail = generate_report(conn, ReportRequest(title="Test report", report_type="detail"))
    finally:
        conn.close()

    assert summary.startswith(b"%PDF")
    assert detail.startswith(b"%PDF")
    # Summary has one /Page object plus the PDF page-tree object. Detail adds
    # the holdings appendix page even when there are no recorded holdings.
    assert summary.count(b"/Type /Page") == 2
    assert detail.count(b"/Type /Page") == 3
