# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
from backend.app.services.analytics_cache import AnalyticsCache


def test_analytics_cache_reuses_a_revision_and_invalidates_on_change():
    cache = AnalyticsCache()
    calls = []

    assert cache.get("insights", 1, lambda: calls.append(1) or {"value": [1]}) == {"value": [1]}
    cached = cache.get("insights", 1, lambda: calls.append(2) or {"value": [2]})
    cached["value"].append(3)
    assert calls == [1]
    assert cache.get("insights", 1, lambda: {"value": [2]}) == {"value": [1]}
    assert cache.get("insights", 2, lambda: calls.append(2) or {"value": [2]}) == {"value": [2]}
    assert calls == [1, 2]
