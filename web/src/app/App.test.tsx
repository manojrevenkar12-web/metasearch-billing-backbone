import { screen } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "./App";
import { renderWithClient } from "../test/render";
import type { Dashboard } from "../shared/types";

const data: Dashboard = {
  world: "dev",
  headline: { backbone_error_pct: 1.2, first_version_error_pct: 7.0, true_billing_eur: 500000, disputes: [2, 36] },
  invoices: [
    { partner: "P01", name: "Alder Air", month: "2026-09", currency: "EUR", issued: "2026-10-03T06:00:00+00:00", notes: 0, first_err_pct: 1.8, final_err_pct: 1.8, held_days: 1 },
    { partner: "P01", name: "Alder Air", month: "2026-10", currency: "EUR", issued: null, notes: 0, first_err_pct: null, final_err_pct: null, held_days: 9 },
  ],
  variants: [{ key: "backbone", label: "Backbone", final_error_pct: 1.2, invoices_wrong_final: 3, partner_disputes: 2 }],
  incidents: [{ incident: "outage", where: "cheapflights", start: "2026-09-30T17:00:00+00:00", caught: true, first_check: "files_complete", hours_to_alert: 13 }],
};

function mockFetch(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(response as Response);
}

test("shows a loading state, then the board", async () => {
  mockFetch({ ok: true, json: async () => data });
  renderWithClient(<App />);
  expect(screen.getByRole("status", { name: "Loading" })).toBeTruthy();
  expect(await screen.findByText("Alder Air")).toBeTruthy();
  expect(screen.getByText(/ISSUED 03 OCT/)).toBeTruthy();
  expect(screen.getByText("HELD")).toBeTruthy();
  expect(screen.getByText("files_complete")).toBeTruthy();
});

test("explains a failed load and offers a retry", async () => {
  mockFetch({ ok: false, status: 500 });
  renderWithClient(<App />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
});

test("an empty close says when the first one runs", async () => {
  mockFetch({ ok: true, json: async () => ({ ...data, invoices: [] }) });
  renderWithClient(<App />);
  expect(await screen.findByText(/first close runs/)).toBeTruthy();
});
