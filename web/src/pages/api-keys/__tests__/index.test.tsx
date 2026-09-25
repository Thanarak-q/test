import { Dialog } from "@/components/ui/dialog";
import { $demoKeys, createDemoKey, resetDemoKeys } from "@/stores/demo";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiKeysPage, CreateKeyDialog, RevokeKeyDialog } from "../index";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: { children: ReactNode }) => <a href="/usage">{children}</a>,
  useNavigate: () => vi.fn(),
  useSearch: () => ({ q: "", status: "all", page: 1, preview: "normal" }),
}));

const flushDemoOperation = async () => {
  await act(async () => {
    vi.runOnlyPendingTimers();
    await Promise.resolve();
    await Promise.resolve();
  });
};

const renderCreateDialog = () => {
  const onClose = vi.fn();
  const onCreated = vi.fn();
  render(<CreateKeyDialog onClose={onClose} onCreated={onCreated} startEmpty={false} />);
  return { onClose, onCreated };
};

describe("API key dialogs", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    resetDemoKeys();
  });

  it("validates names and guards a pending create from duplicate submits", async () => {
    vi.useFakeTimers();
    const { onCreated } = renderCreateDialog();
    const input = screen.getByLabelText("Name");
    const submit = screen.getByRole("button", { name: "Create secret key" });

    expect(submit).toBeDisabled();
    fireEvent.change(input, { target: { value: "  Integration test  " } });
    expect(submit).not.toBeDisabled();
    fireEvent.click(submit);
    expect(submit).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    fireEvent.submit(input.closest("form")!);

    await flushDemoOperation();
    expect(onCreated).toHaveBeenCalledTimes(1);
    expect($demoKeys.get().filter((key) => key.name === "Integration test")).toHaveLength(1);
  });

  it("keeps the secret out of masked markup, supports copy, and expires reveals", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    renderCreateDialog();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Copy test" } });
    fireEvent.click(screen.getByRole("button", { name: "Create secret key" }));
    await flushDemoOperation();

    const copy = screen.getByRole("button", { name: "Copy secret key" });
    const code = () => document.querySelector(".secret-value")!;
    expect(code().tagName).toBe("CODE");
    fireEvent.click(copy);
    await act(async () => {
      await Promise.resolve();
    });
    const secret = writeText.mock.calls[0][0] as string;
    expect(secret).toMatch(/^mk_demo_/);
    expect(code()).not.toHaveTextContent(secret);
    expect(JSON.stringify($demoKeys.get())).not.toContain(secret);
    expect(window.location.href).not.toContain(secret);
    expect(screen.getByRole("status")).toHaveTextContent("Copied to clipboard");

    fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    expect(code()).toHaveTextContent(secret);
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(code()).not.toHaveTextContent(secret);
    fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    expect(code()).toHaveTextContent(secret);
    act(() => vi.advanceTimersByTime(59_999));
    expect(code()).toHaveTextContent(secret);
    fireEvent.click(copy);
    await act(async () => {
      await Promise.resolve();
    });
    act(() => vi.advanceTimersByTime(1));
    expect(code()).not.toHaveTextContent(secret);

    fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    fireEvent(document, new Event("visibilitychange"));
    expect(code()).not.toHaveTextContent(secret);
  });

  it("clears secret state and timers when saved, pagehide fires, or it unmounts", async () => {
    vi.useFakeTimers();
    const { onClose } = renderCreateDialog();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Cleanup test" } });
    fireEvent.click(screen.getByRole("button", { name: "Create secret key" }));
    await flushDemoOperation();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    fireEvent.click(screen.getByRole("button", { name: "Copy secret key" }));
    await act(async () => {
      await Promise.resolve();
    });
    const secret = writeText.mock.calls[0][0] as string;
    fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    expect(document.body).toHaveTextContent(secret);
    fireEvent(window, new Event("pagehide"));
    expect(document.body).not.toHaveTextContent(secret);
    act(() => vi.advanceTimersByTime(60_000));
    expect(document.body).not.toHaveTextContent(secret);

    cleanup();
    resetDemoKeys();
    const saved = renderCreateDialog();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Saved test" } });
    fireEvent.click(screen.getByRole("button", { name: "Create secret key" }));
    await flushDemoOperation();
    fireEvent.click(screen.getByRole("button", { name: "I've saved it" }));
    expect(saved.onClose).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("abandons a pending create on pagehide and allows a fresh create after restore", async () => {
    vi.useFakeTimers();
    const { onCreated } = renderCreateDialog();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Interrupted create" } });
    fireEvent.click(screen.getByRole("button", { name: "Create secret key" }));
    fireEvent(window, new Event("pagehide"));
    await flushDemoOperation();
    await flushDemoOperation();
    expect(onCreated).not.toHaveBeenCalled();
    expect($demoKeys.get().find((key) => key.name === "Interrupted create")?.status).toBe(
      "revoked",
    );
    expect(document.body).not.toHaveTextContent("mk_demo_");

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Restored create" } });
    fireEvent.click(screen.getByRole("button", { name: "Create secret key" }));
    await flushDemoOperation();
    expect(onCreated).toHaveBeenCalledTimes(1);
    expect($demoKeys.get().find((key) => key.name === "Restored create")?.status).toBe("active");
  });

  it("keeps the create dialog open when discard fails and revokes on success", async () => {
    vi.useFakeTimers();
    const { onClose } = renderCreateDialog();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Discard test" } });
    fireEvent.click(screen.getByRole("button", { name: "Create secret key" }));
    await flushDemoOperation();
    const createdId = $demoKeys.get()[0].id;
    $demoKeys.set(
      $demoKeys.get().map((key) => (key.id === createdId ? { ...key, status: "revoked" } : key)),
    );
    fireEvent.click(screen.getByRole("button", { name: "Discard key" }));
    await flushDemoOperation();
    expect(screen.getByRole("alert")).toHaveTextContent("We couldn't revoke this key. Try again.");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("discards a created key and removes its secret from the dialog and store", async () => {
    vi.useFakeTimers();
    const { onClose } = renderCreateDialog();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Discard success" } });
    fireEvent.click(screen.getByRole("button", { name: "Create secret key" }));
    await flushDemoOperation();
    fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    const secret = screen.getByRole("textbox", { name: "Secret key" }).textContent!;
    fireEvent.click(screen.getByRole("button", { name: "Discard key" }));
    await flushDemoOperation();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(document.body).not.toHaveTextContent(secret);
    expect($demoKeys.get()[0].status).toBe("revoked");
    expect(JSON.stringify($demoKeys.get())).not.toContain(secret);
  });

  it("shows a manual-copy message when the clipboard rejects", async () => {
    vi.useFakeTimers();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    renderCreateDialog();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Manual copy" } });
    fireEvent.click(screen.getByRole("button", { name: "Create secret key" }));
    await flushDemoOperation();
    fireEvent.click(screen.getByRole("button", { name: "Copy secret key" }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/select it and copy it manually/i);
  });

  it("handles revoke success and failure without duplicate operations", async () => {
    vi.useFakeTimers();
    const entry = $demoKeys.get().find((key) => key.status === "active")!;
    const onClose = vi.fn();
    render(<RevokeKeyDialog entry={entry} onClose={onClose} />);
    const revoke = screen.getByRole("button", { name: "Revoke key" });
    fireEvent.click(revoke);
    expect(revoke).toBeDisabled();
    fireEvent.click(revoke);
    await flushDemoOperation();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect($demoKeys.get().find((key) => key.id === entry.id)?.status).toBe("revoked");

    cleanup();
    resetDemoKeys();
    const revoked = $demoKeys.get().find((key) => key.status === "revoked")!;
    const failureClose = vi.fn();
    render(<RevokeKeyDialog entry={revoked} onClose={failureClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Revoke key" }));
    await flushDemoOperation();
    expect(screen.getByRole("alert")).toHaveTextContent("We couldn't revoke this key. Try again.");
    expect(failureClose).not.toHaveBeenCalled();
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
    const dialog = screen.getByRole("dialog");
    fireEvent(dialog, new Event("cancel", { bubbles: true, cancelable: true }));
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

  it("renders full safe prefixes, dims revoked rows, and explains unused keys", () => {
    render(<ApiKeysPage />);
    expect(screen.getAllByRole("columnheader").map((header) => header.textContent?.trim())).toEqual(
      ["Name", "Key", "Status", "Last used", "Actions"],
    );
    expect(screen.getByText("mk_demo_prod")).toBeVisible();
    expect(screen.getByText("Previous deployment").closest("tr")).toHaveClass("revoked-row");
    expect(screen.getByText("Never used")).toBeVisible();
    expect(screen.getByText("Consider removing this key.")).toBeVisible();
    expect(screen.getByTitle("Active key capacity")).toHaveTextContent("4 / 5 keys");
  });

  it("disables creation at the active-key limit", async () => {
    await createDemoKey("At the limit");
    render(<ApiKeysPage />);
    expect(screen.getByRole("button", { name: "Create new secret key" })).toBeDisabled();
    expect(screen.getByTitle("Active key capacity")).toHaveTextContent("5 / 5 keys");
    expect(screen.getByText("Revoke a key before creating another.")).toBeVisible();
  });
});
