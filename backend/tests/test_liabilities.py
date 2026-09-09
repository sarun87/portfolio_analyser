from backend.app.core.encryption import generate_salt, key_manager
from backend.app.db.schema import init_db
from backend.app.services.asset_service import create_liability, delete_liability, list_liabilities, update_liability
from backend.app.services.models import LiabilityCreate, LiabilityUpdate
from backend.app.services.portfolio_service import dashboard


def _unlock():
    key_manager.setup("correct horse battery staple", generate_salt())


def test_liabilities_are_encrypted_converted_and_reduce_net_worth(sqlite_conn):
    init_db(sqlite_conn); _unlock()
    liability = create_liability(sqlite_conn, LiabilityCreate(entity_name="Example Bank", liability_type="Home Loan", account_reference="HOME-1234", outstanding_balance=125000, currency="USD"))
    assert liability.account_reference_mask == "****1234"
    assert sqlite_conn.execute("SELECT account_reference_enc FROM liabilities").fetchone()["account_reference_enc"] != "HOME-1234"
    analytics = dashboard(sqlite_conn)
    assert analytics.total_assets == 0
    assert analytics.total_liabilities == 125000
    assert analytics.total_net_worth == -125000

    updated = update_liability(sqlite_conn, liability.id, LiabilityUpdate(entity_name="Example Bank", liability_type="Other", custom_type="Bridge loan", outstanding_balance=100000, currency="USD"))
    assert updated.custom_type == "Bridge loan"
    assert updated.account_reference_mask == "****1234"
    delete_liability(sqlite_conn, liability.id)
    assert list_liabilities(sqlite_conn) == []
