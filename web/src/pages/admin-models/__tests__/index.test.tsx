import type { AdminModelResponse } from "@/api/generated/model";
import { ApiError } from "@/api/mutator";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminModelsPage, ModelActionDialog } from "../index";

const api = vi.hoisted(() => ({
  enableModel: vi.fn(),
  disableModel: vi.fn(),
  query: {} as Record<string, unknown>,
}));

vi.mock("@/api/generated/admin/admin", () => ({
  enableModel: api.enableModel,
  disableModel: api.disableModel,
  getListModelsQueryKey: () => ["POST", "/v1/admin/models/list"],
  useListModels: () => api.query,
}));

const model = (overrides: Partial<AdminModelResponse> = {}): AdminModelResponse => ({
  id: 1,
  name: "gpt-4o",
  context_window: 128_000,
  max_output_tokens: 16_384,
  status: "enabled",
  ...overrides,
});

const wrap = (node: ReactNode) =>
  render(<QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>);

const flush = () =>
  act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("admin models", () => {
  it("lists every model with its limits and status", () => {
    api.query = {
      data: [
        model(),
        model({ id: 2, name: "gpt-4.1", context_window: 1_047_576, status: "disabled" }),
      ],
      isPending: false,
      isError: false,
      error: null,
    };
    wrap(<AdminModelsPage />);

    expect(screen.getByText("128,000")).toBeVisible();
    expect(screen.getByText("gpt-4.1").closest("tr")).toHaveClass("revoked-row");
    expect(screen.getByRole("button", { name: "Disable" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Enable" })).toBeVisible();
  });

  it("tells a non-admin the page is for admins", () => {
    api.query = {
      data: undefined,
      isPending: false,
      isError: true,
      error: new ApiError("identity_forbidden", "nope", 403),
    };
    wrap(<AdminModelsPage />);

    expect(screen.getByRole("heading", { name: "Admins only" })).toBeVisible();
  });

  it("confirms with the model name and disables it", async () => {
    api.disableModel.mockResolvedValue({ ok: true });
    const onClose = vi.fn();
    wrap(<ModelActionDialog action="disable" model={model()} onClose={onClose} />);

    expect(screen.getByRole("dialog")).toHaveTextContent("Disable “gpt-4o”?");
    fireEvent.click(screen.getByRole("button", { name: "Disable “gpt-4o”" }));
    await flush();

    expect(api.disableModel).toHaveBeenCalledWith({ id: 1 });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("never reports success when the change is not in effect yet", async () => {
    api.disableModel.mockRejectedValue(new ApiError("llm_model_change_pending", "pending", 500));
    const onClose = vi.fn();
    wrap(<ModelActionDialog action="disable" model={model()} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Disable “gpt-4o”" }));
    await flush();

    expect(screen.getByRole("alert")).toHaveTextContent("not in effect yet");
    expect(onClose).not.toHaveBeenCalled();
  });
});
