// SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
// SPDX-License-Identifier: GPL-3.0-only
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { compactMoneyTick, GrowthView, Overview, ProjectionGuidancePage, smallPieSliceIndexes, visibleYDomain } from "../App";
import type { DashboardAnalytics, Insights } from "../lib/types";

describe("dynamic chart interactions", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("derives a close y-axis range from the visible values", () => {
    expect(visibleYDomain([{ value: 100 }, { value: 101 }], ["value"])).toEqual([99.92, 101.08]);
    expect(visibleYDomain([{ value: 100 }, { value: 101 }], ["value"], true)).toEqual([0, 109.08]);
  });

  it("keeps large currency axis ticks compact and readable", () => {
    expect(compactMoneyTick(1_234_567_890, "USD")).toBe("$1.2B");
    expect(compactMoneyTick(1_234_567_890, "INR")).toBe("₹123.5Cr");
  });

  it("explodes only pie slices below the three-percent threshold", () => {
    expect(smallPieSliceIndexes([{ value: 95 }, { value: 4.99 }, { value: 0.01 }, { value: 5 }], 105)).toEqual([2]);
    expect(smallPieSliceIndexes([{ value: 5 }, { value: 95 }], 100)).toEqual([]);
  });

  it("offers keyboard-accessible projection zoom controls", () => {
    const insights = {
      display_currency: "USD",
      projection_setup_required: false,
      cash_runway_months: 6,
      forecast: {
        end_age: 65,
        monte_carlo_terminal: { p10: 100, p50: 150 },
        series: [
          { month: 0, age: 40, p10: 100, p50: 120, p80: 130, p95: 140 },
          { month: 1, age: 41, p10: 105, p50: 125, p80: 135, p95: 145 },
          { month: 2, age: 42, p10: 110, p50: 130, p80: 140, p95: 150 },
          { month: 3, age: 43, p10: 115, p50: 135, p80: 145, p95: 155 }
        ]
      }
    } as Insights;

    render(<ProjectionGuidancePage insights={insights} />);
    const zoomIn = screen.getByRole("button", { name: "Zoom in" });
    const zoomOut = screen.getByRole("button", { name: "Zoom out" });
    const reset = screen.getByRole("button", { name: "Reset zoom" });
    expect(zoomOut).toBeDisabled();
    expect(reset).toBeDisabled();
    fireEvent.click(zoomIn);
    expect(zoomOut).toBeEnabled();
    expect(reset).toBeEnabled();
    fireEvent.click(reset);
    expect(zoomOut).toBeDisabled();
  });

  it("masks every overview value and chart until values are shown again", () => {
    const analytics = {
      display_currency: "USD",
      total_net_worth: 100,
      brokerage_value: 80,
      static_accounts_value: 10,
      real_estate_value: 5,
      total_cost_basis: 70,
      unrealized_gain_loss: 30,
      net_worth_allocation: [{ label: "Brokerage", value: 80 }],
      asset_allocation: [{ label: "Equity", value: 80 }],
      portfolio_growth: [{ date: "2026-01-01", value: 80 }, { date: "2026-02-01", value: 90 }],
      net_worth_growth: []
    } as any;
    render(<Overview analytics={analytics} positions={[]} onAllocationClick={vi.fn()} onCaptureNetWorthSnapshot={vi.fn().mockResolvedValue(undefined)} />);
    const toggle = screen.getByRole("button", { name: "Hide values" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("$100.00")).not.toBeInTheDocument();
    expect(screen.getAllByRole("status")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Show values" }));
    expect(screen.getByText("$100.00")).toBeInTheDocument();
  });

  it("shows a manual all-assets net-worth capture and reports its result", async () => {
    const analytics = {
      display_currency: "USD", total_net_worth: 100, total_liabilities: 20, brokerage_value: 80,
      static_accounts_value: 10, real_estate_value: 5, private_equity_value: 5, total_cost_basis: 70,
      unrealized_gain_loss: 10, net_worth_allocation: [], asset_allocation: [], portfolio_growth: [], net_worth_growth: []
    } as any;
    const capture = vi.fn().mockResolvedValue(undefined);
    render(<Overview analytics={analytics} positions={[]} onAllocationClick={vi.fn()} onCaptureNetWorthSnapshot={capture} />);

    expect(screen.getByRole("heading", { name: "Net Worth Over Time" })).toBeInTheDocument();
    expect(screen.getByText(/No net-worth snapshots yet/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Portfolio Growth" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Record today's snapshot" }));

    await waitFor(() => expect(capture).toHaveBeenCalledTimes(1));
    expect(capture.mock.calls[0][0]).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(await screen.findByRole("status")).toHaveTextContent("saved or updated");
  });

  it("keeps brokerage-only history in Analytics portfolio growth", () => {
    const analytics = {
      display_currency: "USD", brokerage_value: 100, static_accounts_value: 0, real_estate_value: 0,
      total_net_worth: 100, total_value: 100, total_cost_basis: 100, unrealized_gain_loss: 0,
      portfolio_growth: [{ date: "2026-01-01", value: 100 }], net_worth_growth: [],
      asset_allocation: [], broker_allocation: [], country_allocation: [], exchange_allocation: [],
      cash_vs_invested: [], net_worth_allocation: [],
      country_returns: [], country_snapshot_disclosure: "Snapshot value changes are a proxy."
    } as DashboardAnalytics;
    render(<GrowthView analytics={analytics} />);

    expect(screen.getByRole("heading", { name: "Brokerage Portfolio Growth" })).toBeInTheDocument();
    expect(screen.getByText(/Historical value of brokerage positions only/)).toBeInTheDocument();
  });
});
