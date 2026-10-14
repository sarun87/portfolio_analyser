// SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
// SPDX-License-Identifier: GPL-3.0-only
import "@testing-library/jest-dom/vitest";

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
