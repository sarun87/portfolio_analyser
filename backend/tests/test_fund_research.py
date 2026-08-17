import json
import sqlite3
import urllib.error

from backend.app.db.schema import init_db
from backend.app.services import exposure_service
from backend.app.services.exposure_service import accept_public_metadata, research_peers
from backend.app.services.models import PeerCandidate, PeerResearch


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.execute("INSERT INTO securities(symbol, name, security_type, allocation_category, exchange, investment_country) VALUES ('FUND', 'Held Fund', 'ETF', 'International', 'NYSE', 'United States')")
    return conn


def test_accept_public_facts_without_holdings_preserves_existing_composition():
    conn = _conn()
    security_id = conn.execute("SELECT id FROM securities").fetchone()["id"]
    conn.execute("""INSERT INTO reference_cache(cache_key, provider, payload_json, fetched_at) VALUES (?, ?, ?, ?)
                 """, (f"security:{security_id}:metadata", "yahoo-summary", json.dumps({
                     "composition": None, "as_of_date": "2026-01-31",
                     "expense_ratio_percent": 0.1,
                     "facts": {"category": "Large Blend", "expense_ratio_percent": 0.1},
                 }), "2026-02-01T00:00:00+00:00"))

    accepted = accept_public_metadata(conn, security_id)

    assert accepted.composition is None
    assert accepted.metadata.category == "Large Blend"
    assert accepted.metadata.as_of_date == "2026-01-31"
    assert conn.execute("SELECT COUNT(*) AS count FROM fund_compositions").fetchone()["count"] == 0


def test_failed_peer_refresh_returns_previous_cached_research(monkeypatch):
    conn = _conn()
    security_id = conn.execute("SELECT id FROM securities").fetchone()["id"]
    conn.execute("""INSERT INTO fund_metadata(security_id, provider, category, reviewed_at)
                 VALUES (?, 'yahoo-summary', 'Large Blend', '2026-01-01T00:00:00+00:00')""", (security_id,))
    previous = PeerResearch(security_id=security_id, retrieved_at="2026-01-01T00:00:00+00:00", provider="yahoo-search",
                            candidates=[PeerCandidate(symbol="PEER", name="Prior Peer", category="Large Blend", expense_ratio_percent=0.1,
                                                      matched_horizon="5-year", matched_return_percent=10, rank=1)], note="Prior result")
    conn.execute("INSERT INTO reference_cache(cache_key, provider, payload_json, fetched_at) VALUES (?, ?, ?, ?)",
                 (f"security:{security_id}:peers", "yahoo-search", previous.model_dump_json(), previous.retrieved_at))
    monkeypatch.setattr(exposure_service.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")))

    result = research_peers(conn, security_id)

    assert result.candidates[0].symbol == "PEER"
    assert any("previous cached" in warning.lower() for warning in result.warnings)
    assert json.loads(conn.execute("SELECT payload_json FROM reference_cache WHERE cache_key=?", (f"security:{security_id}:peers",)).fetchone()["payload_json"])["note"] == "Prior result"
