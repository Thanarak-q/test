import type { UsageResponse } from "@/api/generated/model";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { UsagePage } from "../index";

const api = vi.hoisted(() => ({ useGetUsage: vi.fn() }));

vi.mock("@/api/generated/dashboard/dashboard", () => ({ useGetUsage: api.useGetUsage }));
vi.mock("@/api/generated/api-keys/api-keys", () => ({
  useListApiKeys: () => ({ data: [], isPending: false, isError: false }),
}));
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
  useSearch: () => ({ days: "30", key: "all", metric: "requests" }),
}));

const report: UsageResponse = {
  from: "2026-08-27",
  to: "2026-09-25",
  timezone: "Asia/Bangkok",
  clamped: false,
  quota: { limit: 1_000_000, used: 250_000, remaining: 750_000 },
  totals: { requests: 4, tokens: 1600 },
  by_source: [
    { source: "api", requests: 3, tokens: 600 },
    { source: "web", requests: 1, tokens: 1000 },
  ],
  by_key: [
    {
      key_id: "01K5ZQ3NDEKTSV4RRFFQ69G5FA",
      name: "Production server",
      key_prefix: "mthw01_01K5ZQ3NDEKTSV4RRFFQ69G5FA",
      status: "active",
      requests: 3,
      tokens: 600,
      // deliberately not 3/4: the page must show the API's figure, not its own
      request_share_pct: 66.6,
    },
  ],
  daily: [{ date: "2026-09-25", requests: 4, tokens: 1600 }],
};

afterEach(cleanup);

it("asks the API for the preset and shows its figures as given", () => {
  api.useGetUsage.mockReturnValue({ data: report, isPending: false, isError: false });

  render(<UsagePage />);

  expect(api.useGetUsage).toHaveBeenCalledWith({ days: 30, key_id: undefined });
  expect(screen.getByText("750,000")).toBeVisible();
  expect(screen.getByText("66.6%")).toBeVisible();
  expect(screen.getByText("Mathew API app")).toBeVisible();
  expect(screen.getByText("1,000 tokens")).toBeVisible();
  expect(screen.getByText("Production server")).toBeVisible();
});

it("shows the loading state while the report is pending", () => {
  api.useGetUsage.mockReturnValue({ data: undefined, isPending: true, isError: false });

  render(<UsagePage />);

  expect(screen.getByRole("status", { name: "Loading dashboard" })).toBeInTheDocument();
});
