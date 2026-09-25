import type { MDXContent } from "mdx/types";

export type DocEntry = {
  slug: string;
  title: string;
  // Documents an endpoint that does not return this shape end to end yet
  // (the chat pipeline is still being built).
  preview?: boolean;
  load: () => Promise<{ default: MDXContent }>;
};

export const docsNav: { group: string; pages: DocEntry[] }[] = [
  {
    group: "Getting started",
    pages: [
      {
        slug: "quickstart",
        title: "Quickstart",
        preview: true,
        load: () => import("@/content/docs/quickstart.mdx"),
      },
      {
        slug: "authentication",
        title: "Authentication",
        load: () => import("@/content/docs/authentication.mdx"),
      },
    ],
  },
  {
    group: "Guides",
    pages: [
      { slug: "models", title: "Models", load: () => import("@/content/docs/models.mdx") },
      {
        slug: "rate-limits",
        title: "Rate limits",
        load: () => import("@/content/docs/rate-limits.mdx"),
      },
      {
        slug: "migrate-from-openai",
        title: "Migrate from OpenAI",
        preview: true,
        load: () => import("@/content/docs/migrate-from-openai.mdx"),
      },
    ],
  },
  {
    group: "Reference",
    pages: [
      {
        slug: "reference/chat",
        title: "Chat completions",
        preview: true,
        load: () => import("@/content/docs/reference/chat.mdx"),
      },
      {
        slug: "reference/embeddings",
        title: "Embeddings",
        preview: true,
        load: () => import("@/content/docs/reference/embeddings.mdx"),
      },
      {
        slug: "reference/models",
        title: "List models",
        preview: true,
        load: () => import("@/content/docs/reference/models.mdx"),
      },
      { slug: "errors", title: "Errors", load: () => import("@/content/docs/errors.mdx") },
    ],
  },
  {
    group: "Policies",
    pages: [
      {
        slug: "data-and-privacy",
        title: "Data & privacy",
        load: () => import("@/content/docs/data-and-privacy.mdx"),
      },
      { slug: "security", title: "Security", load: () => import("@/content/docs/security.mdx") },
    ],
  },
  {
    group: "Help",
    pages: [
      { slug: "faq", title: "FAQ", load: () => import("@/content/docs/faq.mdx") },
      {
        slug: "changelog",
        title: "Changelog",
        load: () => import("@/content/docs/changelog.mdx"),
      },
    ],
  },
];

export const DEFAULT_DOC = "quickstart";

export const findDoc = (slug: string) =>
  docsNav.flatMap((group) => group.pages).find((page) => page.slug === slug);
