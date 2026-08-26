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

  it("sends a protected password-change request", async () => {
    await api.changePassphrase("new password");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/change-passphrase");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf-test");
    expect(init.body).toBe(JSON.stringify({ new_passphrase: "new password" }));
  });
});
