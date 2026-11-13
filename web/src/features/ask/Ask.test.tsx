import { fireEvent, screen } from "@testing-library/react";
import { vi } from "vitest";
import { Ask } from "./Ask";
import { renderWithClient } from "../../test/render";

test("a refused question says why", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: async () => ({ question: "q", answered: false, refusal: "Click revenue (EUR) cannot be cut by brand" }),
  } as Response);
  renderWithClient(<Ask />);
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
  expect(await screen.findByText(/cannot be cut by brand/)).toBeTruthy();
});

test("an offline service shows how to start it", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: false, status: 502 } as Response);
  renderWithClient(<Ask />);
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
  expect(await screen.findByText(/mbb serve/)).toBeTruthy();
});
