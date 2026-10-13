// SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
// SPDX-License-Identifier: GPL-3.0-only
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/styles.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
