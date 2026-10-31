// SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
// SPDX-License-Identifier: GPL-3.0-only
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";

describe("cookie-authenticated API requests", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    document.cookie = "portfolio_csrf=csrf-test; path=/";
    fetchMock.mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue({ configured: true, unlocked: true }) });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    document.cookie = "portfolio_csrf=; Max-Age=0; path=/";
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("uses same-origin cookies without exposing an authorization header", async () => {
    await api.authStatus();
    const [, init] = fetchMock.mock.calls[0];
    expect(init.credentials).toBe("same-origin");
    expect(new Headers(init.headers).get("Authorization")).toBeNull();
  });

  it("adds the CSRF header to protected writes", async () => {
    await api.lock();
    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf-test");
  });

  it("records a local-date net-worth snapshot using a protected request", async () => {
    await api.captureNetWorthSnapshot("2026-10-29");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/analytics/net-worth-snapshots");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf-test");
    expect(init.body).toBe(JSON.stringify({ snapshot_date: "2026-10-29" }));
  });

  it("sends a protected password-change request", async () => {
    await api.changePassphrase("new password");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/change-passphrase");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf-test");
    expect(init.body).toBe(JSON.stringify({ new_passphrase: "new password" }));
  });

  it("inspects an uploaded database snapshot using a protected multipart request", async () => {
    const file = new File(["snapshot"], "portfolio.db", { type: "application/vnd.sqlite3" });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: vi.fn().mockResolvedValue({ categories: ["broker-definitions"] })
    });

    const result = await api.inspectDatabase(file);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/database/inspect");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf-test");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
    expect(result.categories).toEqual(["broker-definitions"]);
  });
});
