import type { KeySummaryResponse } from "@/api/generated/model";
import { ApiError } from "@/api/mutator";
import { Dialog } from "@/components/ui/dialog";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiKeysPage, CreateKeyDialog, KeyActionDialog } from "../index";

const api = vi.hoisted(() => ({
  createApiKey: vi.fn(),
  deleteApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
  listed: [] as KeySummaryResponse[],
}));

vi.mock("@/api/generated/api-keys/api-keys", () => ({
  createApiKey: api.createApiKey,
  deleteApiKey: api.deleteApiKey,
  revokeApiKey: api.revokeApiKey,
  getListApiKeysQueryKey: () => ["POST", "/v1/api-keys/list"],
  useListApiKeys: () => ({
    data: api.listed,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: { children: ReactNode }) => <a href="/usage">{children}</a>,
  useNavigate: () => vi.fn(),
  useSearch: () => ({ q: "", status: "all", page: 1, preview: "normal" }),
}));

const KEY_ID = "01K5ZQ3NDEKTSV4RRFFQ69G5FA";
const PREFIX = `mthw01_${KEY_ID}`;
const SECRET_KEY = `${PREFIX}_Abcdef0123456789Abcdef0123456789`;

const summary = (overrides: Partial<KeySummaryResponse> = {}): KeySummaryResponse => ({
  id: KEY_ID,
  name: "Production server",
  key_prefix: PREFIX,
  status: "active",
  created_at: "2026-09-01T03:00:00Z",
  last_used_at: "2026-09-20T03:00:00Z",
  never_used: false,
  ...overrides,
});

const wrap = (node: ReactNode) =>
  render(<QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>);

const flush = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
};

const createKey = async (name = "Integration test") => {
  const onClose = vi.fn();
  wrap(<CreateKeyDialog onClose={onClose} />);
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: name } });
  fireEvent.click(screen.getByRole("button", { name: "Create secret key" }));
  await flush();
  return { onClose };
};

const code = () => document.querySelector(".secret-value")!;

describe("API key dialogs", () => {
  beforeEach(() => {
    api.createApiKey.mockResolvedValue({
      id: KEY_ID,
      name: "Integration test",
      key: SECRET_KEY,
      key_prefix: PREFIX,
      created_at: "2026-09-25T03:00:00Z",
    });
    api.deleteApiKey.mockResolvedValue({ ok: true });
    api.revokeApiKey.mockResolvedValue({ ok: true });
    api.listed = [];
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("validates names, trims them, and guards a pending create from duplicate submits", async () => {
    let resolve: (value: unknown) => void = () => {};
    api.createApiKey.mockReturnValue(new Promise((done) => (resolve = done)));
    wrap(<CreateKeyDialog onClose={vi.fn()} />);
    const input = screen.getByLabelText("Name");
    const submit = screen.getByRole("button", { name: "Create secret key" });

    expect(submit).toBeDisabled();
    fireEvent.change(input, { target: { value: "  Integration test  " } });
    fireEvent.click(submit);
    expect(submit).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    fireEvent.submit(input.closest("form")!);
    resolve({ id: KEY_ID, key: SECRET_KEY, key_prefix: PREFIX });
    await flush();

    expect(api.createApiKey).toHaveBeenCalledTimes(1);
    expect(api.createApiKey).toHaveBeenCalledWith({ name: "Integration test" });
  });

  it("masks with the API's prefix, copies, and auto-masks after 60 seconds", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    await createKey();

    expect(code().tagName).toBe("CODE");
    expect(code()).toHaveTextContent(PREFIX);
    expect(code()).not.toHaveTextContent(SECRET_KEY);
    fireEvent.click(screen.getByRole("button", { name: "Copy secret key" }));
    await flush();
    expect(writeText).toHaveBeenCalledWith(SECRET_KEY);
    expect(screen.getByRole("status")).toHaveTextContent("Copied to clipboard");
    expect(window.location.href).not.toContain(SECRET_KEY);

    fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    expect(code()).toHaveTextContent(SECRET_KEY);
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(code()).not.toHaveTextContent(SECRET_KEY);
    fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    act(() => vi.advanceTimersByTime(59_999));
    expect(code()).toHaveTextContent(SECRET_KEY);
    act(() => vi.advanceTimersByTime(1));
    expect(code()).not.toHaveTextContent(SECRET_KEY);

    fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    fireEvent(document, new Event("visibilitychange"));
    expect(code()).not.toHaveTextContent(SECRET_KEY);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  });

  it("clears the secret on pagehide and closes only through “I've saved it”", async () => {
    const { onClose } = await createKey();
    fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    expect(document.body).toHaveTextContent(SECRET_KEY);

    fireEvent(window, new Event("pagehide"));
    expect(document.body).not.toHaveTextContent(SECRET_KEY);

    cleanup();
    const saved = await createKey("Saved test");
    fireEvent.click(screen.getByRole("button", { name: "I've saved it" }));
    expect(saved.onClose).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("deletes a key whose create finished after the page went away", async () => {
    let resolve: (value: unknown) => void = () => {};
    api.createApiKey.mockReturnValue(new Promise((done) => (resolve = done)));
    wrap(<CreateKeyDialog onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Interrupted" } });
    fireEvent.click(screen.getByRole("button", { name: "Create secret key" }));
    fireEvent(window, new Event("pagehide"));
    resolve({ id: KEY_ID, key: SECRET_KEY, key_prefix: PREFIX });
    await flush();

    expect(api.deleteApiKey).toHaveBeenCalledWith({ id: KEY_ID });
    expect(document.body).not.toHaveTextContent(SECRET_KEY);
  });

  it("discard deletes the key, and a failed discard keeps the dialog open", async () => {
    api.deleteApiKey.mockRejectedValueOnce(new ApiError("internal_error", "boom", 500));
    const { onClose } = await createKey();

    fireEvent.click(screen.getByRole("button", { name: "Discard key" }));
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent("We couldn't discard this key. Try again.");
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Discard key" }));
    await flush();
    expect(api.deleteApiKey).toHaveBeenLastCalledWith({ id: KEY_ID });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(document.body).not.toHaveTextContent(SECRET_KEY);
  });

  it("shows the server's message when the key limit is reached", async () => {
    api.createApiKey.mockRejectedValue(
      new ApiError(
        "identity_api_key_limit_reached",
        "You can have up to 5 active API keys. Revoke one before creating another.",
        409,
      ),
    );
    await createKey();

    expect(screen.getByRole("alert")).toHaveTextContent("up to 5 active API keys");
  });

  it("shows a manual-copy message when the clipboard rejects", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    await createKey();
    fireEvent.click(screen.getByRole("button", { name: "Copy secret key" }));
    await flush();

    expect(screen.getByRole("alert")).toHaveTextContent(/select it and copy it manually/i);
  });

  it("confirms revoke with the key name and guards duplicate clicks", async () => {
    const onClose = vi.fn();
    wrap(<KeyActionDialog action="revoke" entry={summary()} onClose={onClose} />);
    expect(screen.getByRole("dialog")).toHaveTextContent("Revoke “Production server”?");
    const revoke = screen.getByRole("button", { name: "Revoke “Production server”" });

    fireEvent.click(revoke);
    expect(revoke).toBeDisabled();
    fireEvent.click(revoke);
    await flush();

    expect(api.revokeApiKey).toHaveBeenCalledTimes(1);
    expect(api.revokeApiKey).toHaveBeenCalledWith({ id: KEY_ID });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("never reports success when cache invalidation failed", async () => {
    api.revokeApiKey.mockRejectedValue(
      new ApiError("identity_api_key_revocation_pending", "The key is not revoked yet.", 500),
    );
    const onClose = vi.fn();
    wrap(<KeyActionDialog action="revoke" entry={summary()} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Revoke “Production server”" }));
    await flush();

    expect(screen.getByRole("alert")).toHaveTextContent("The key is not revoked yet. Try again.");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("confirms delete with the key name", async () => {
    const onClose = vi.fn();
    wrap(
      <KeyActionDialog action="delete" entry={summary({ status: "revoked" })} onClose={onClose} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete “Production server”" }));
    await flush();

    expect(api.deleteApiKey).toHaveBeenCalledWith({ id: KEY_ID });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("applies dismissal rules and restores focus for shared dialogs", () => {
    const trigger = document.createElement("button");
    document.body.append(trigger);
    trigger.focus();
    const dismiss = vi.fn();
    const { unmount } = render(
      <Dialog title="Dismissible" onClose={dismiss}>
        <p>Body</p>
      </Dialog>,
    );
    fireEvent(screen.getByRole("dialog"), new Event("cancel", { bubbles: true, cancelable: true }));
    expect(dismiss).toHaveBeenCalledTimes(1);
    unmount();
    expect(trigger).toHaveFocus();

    const blockedDismiss = vi.fn();
    render(
      <Dialog title="Protected" onClose={blockedDismiss} dismissible={false}>
        <p>Body</p>
      </Dialog>,
    );
    const protectedDialog = screen.getByRole("dialog");
    expect(screen.queryByRole("button", { name: "Close dialog" })).not.toBeInTheDocument();
    const cancel = new Event("cancel", { bubbles: true, cancelable: true });
    fireEvent(protectedDialog, cancel);
    fireEvent.click(protectedDialog);
    expect(cancel.defaultPrevented).toBe(true);
    expect(blockedDismiss).not.toHaveBeenCalled();
    trigger.remove();
  });

  it("renders the API's prefix, dims revoked rows, and marks unused keys", () => {
    api.listed = [
      summary(),
      summary({
        id: "01K5ZQ3NDEKTSV4RRFFQ69G5FB",
        name: "Local testing",
        key_prefix: "mthw01_01K5ZQ3NDEKTSV4RRFFQ69G5FB",
        last_used_at: null,
        never_used: true,
      }),
      summary({
        id: "01K5ZQ3NDEKTSV4RRFFQ69G5FC",
        name: "Previous deployment",
        key_prefix: "mthw01_01K5ZQ3NDEKTSV4RRFFQ69G5FC",
        status: "revoked",
      }),
    ];
    wrap(<ApiKeysPage />);

    expect(screen.getAllByRole("columnheader").map((header) => header.textContent?.trim())).toEqual(
      ["Name", "Key", "Status", "Last used", "Actions"],
    );
    expect(screen.getByText(PREFIX)).toBeVisible();
    expect(screen.getByText("Previous deployment").closest("tr")).toHaveClass("revoked-row");
    expect(screen.getByText("Never used")).toBeVisible();
    expect(screen.getByRole("button", { name: "Revoke Production server" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Delete Previous deployment" })).toBeVisible();
    expect(screen.getByTitle("Active key capacity")).toHaveTextContent("2 / 5 keys");
  });

  it("disables creation at the active-key limit", () => {
    api.listed = Array.from({ length: 5 }, (_, index) =>
      summary({ id: `01K5ZQ3NDEKTSV4RRFFQ69G5F${index}`, name: `Key ${index}` }),
    );
    wrap(<ApiKeysPage />);

    expect(screen.getByRole("button", { name: "Create new secret key" })).toBeDisabled();
    expect(screen.getByTitle("Active key capacity")).toHaveTextContent("5 / 5 keys");
    expect(screen.getByText("Revoke a key before creating another.")).toBeVisible();
  });
});
