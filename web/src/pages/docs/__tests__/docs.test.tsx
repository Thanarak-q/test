import { docsValues } from "@/content/docs/values";
import { routeTree } from "@/routeTree.gen";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { docsNav } from "../nav";

const allPages = docsNav.flatMap((group) => group.pages);

beforeAll(() => {
  // The dashboard layout listens for the desktop breakpoint.
  window.matchMedia ??= ((query: string) => ({
    matches: true,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
});

afterEach(cleanup);

const open = async (path: string) => {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  render(<RouterProvider router={router} />);
  await act(async () => {
    await router.load();
  });
  return router;
};

const article = () => screen.getByRole("article");

describe("docs", () => {
  it.each(allPages.map((page) => [page.slug, page]))("renders /docs/%s", async (_, page) => {
    await open(`/docs/${page.slug}`);

    expect(await screen.findByRole("heading", { level: 1, name: page.title })).toBeVisible();
    // Every page is reachable from the docs sidebar.
    const nav = screen.getByRole("navigation", { name: "Documentation" });
    expect(within(nav).getByRole("link", { name: page.title })).toBeVisible();
    expect(within(article()).queryAllByText("Preview").length > 0).toBe(Boolean(page.preview));
  });

  it("redirects /docs to the quickstart", async () => {
    const router = await open("/docs");

    expect(await screen.findByRole("heading", { level: 1, name: "Quickstart" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/docs/quickstart");
  });

  it("is linked from the dashboard sidebar", async () => {
    await open("/docs/faq");

    const main = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(main).getByRole("link", { name: "Docs" })).toHaveAttribute("href", "/docs");
  });

  it("shows placeholders as “To be confirmed”, never as raw values", async () => {
    await open("/docs/models");
    await screen.findByRole("heading", { level: 1, name: "Models" });

    const table = within(article()).getByRole("table");
    expect(within(table).getAllByText("To be confirmed")).toHaveLength(docsValues.models.length);
    expect(article()).not.toHaveTextContent(/\bTBD\b/);
  });

  it("copies code and announces it in a live region", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    await open("/docs/authentication");
    await screen.findByRole("heading", { level: 1, name: "Authentication" });

    fireEvent.click(screen.getByRole("button", { name: "Copy Header code" }));
    await act(async () => {
      await Promise.resolve();
    });

    expect(writeText).toHaveBeenCalledWith(
      `Authorization: Bearer ${docsValues.keyPrefix}_YOUR_KEY_ID_YOUR_SECRET`,
    );
    const statuses = screen.getAllByRole("status");
    expect(statuses.some((node) => node.textContent === "Copied to clipboard")).toBe(true);
  });

  it("keeps the example language in the URL", async () => {
    const router = await open("/docs/quickstart");
    await screen.findByRole("heading", { level: 1, name: "Quickstart" });

    fireEvent.click(screen.getByRole("button", { name: "Python" }));
    await act(async () => {
      await router.load();
    });

    expect(router.state.location.search).toMatchObject({ lang: "python" });
    expect(screen.getByRole("button", { name: "Python" })).toHaveAttribute("aria-pressed", "true");
    expect(article()).toHaveTextContent("from openai import OpenAI");
  });
});
