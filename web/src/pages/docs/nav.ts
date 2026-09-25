import type { MDXContent } from "mdx/types";

export const LOCALES = ["en", "th"] as const;
export type Locale = (typeof LOCALES)[number];
type Localized<T> = Record<Locale, T>;

export type DocEntry = {
  slug: string;
  title: Localized<string>;
  load: Localized<() => Promise<{ default: MDXContent }>>;
};

export const docsNav: { group: Localized<string>; pages: DocEntry[] }[] = [
  {
    group: { en: "Getting started", th: "เริ่มต้นใช้งาน" },
    pages: [
      {
        slug: "quickstart",
        title: { en: "Quickstart", th: "เริ่มต้นอย่างรวดเร็ว" },
        load: {
          en: () => import("@/content/docs/quickstart.mdx"),
          th: () => import("@/content/docs/th/quickstart.mdx"),
        },
      },
      {
        slug: "authentication",
        title: { en: "Authentication", th: "การยืนยันตัวตน" },
        load: {
          en: () => import("@/content/docs/authentication.mdx"),
          th: () => import("@/content/docs/th/authentication.mdx"),
        },
      },
    ],
  },
  {
    group: { en: "Guides", th: "คู่มือ" },
    pages: [
      {
        slug: "models",
        title: { en: "Models", th: "โมเดล" },
        load: {
          en: () => import("@/content/docs/models.mdx"),
          th: () => import("@/content/docs/th/models.mdx"),
        },
      },
      {
        slug: "rate-limits",
        title: { en: "Rate limits", th: "Rate limits" },
        load: {
          en: () => import("@/content/docs/rate-limits.mdx"),
          th: () => import("@/content/docs/th/rate-limits.mdx"),
        },
      },
      {
        slug: "migrate-from-openai",
        title: { en: "Migrate from OpenAI", th: "ย้ายมาจาก OpenAI" },
        load: {
          en: () => import("@/content/docs/migrate-from-openai.mdx"),
          th: () => import("@/content/docs/th/migrate-from-openai.mdx"),
        },
      },
    ],
  },
  {
    group: { en: "Reference", th: "อ้างอิง" },
    pages: [
      {
        slug: "reference/chat",
        title: { en: "Chat completions", th: "Chat completions" },
        load: {
          en: () => import("@/content/docs/reference/chat.mdx"),
          th: () => import("@/content/docs/th/reference/chat.mdx"),
        },
      },
      {
        slug: "reference/embeddings",
        title: { en: "Embeddings", th: "Embeddings" },
        load: {
          en: () => import("@/content/docs/reference/embeddings.mdx"),
          th: () => import("@/content/docs/th/reference/embeddings.mdx"),
        },
      },
      {
        slug: "reference/models",
        title: { en: "List models", th: "รายการโมเดล" },
        load: {
          en: () => import("@/content/docs/reference/models.mdx"),
          th: () => import("@/content/docs/th/reference/models.mdx"),
        },
      },
      {
        slug: "errors",
        title: { en: "Errors", th: "Errors" },
        load: {
          en: () => import("@/content/docs/errors.mdx"),
          th: () => import("@/content/docs/th/errors.mdx"),
        },
      },
    ],
  },
  {
    group: { en: "Policies", th: "นโยบาย" },
    pages: [
      {
        slug: "data-and-privacy",
        title: { en: "Data & privacy", th: "ข้อมูลและความเป็นส่วนตัว" },
        load: {
          en: () => import("@/content/docs/data-and-privacy.mdx"),
          th: () => import("@/content/docs/th/data-and-privacy.mdx"),
        },
      },
      {
        slug: "security",
        title: { en: "Security", th: "ความปลอดภัย" },
        load: {
          en: () => import("@/content/docs/security.mdx"),
          th: () => import("@/content/docs/th/security.mdx"),
        },
      },
    ],
  },
  {
    group: { en: "Help", th: "ช่วยเหลือ" },
    pages: [
      {
        slug: "faq",
        title: { en: "FAQ", th: "คำถามที่พบบ่อย" },
        load: {
          en: () => import("@/content/docs/faq.mdx"),
          th: () => import("@/content/docs/th/faq.mdx"),
        },
      },
      {
        slug: "changelog",
        title: { en: "Changelog", th: "บันทึกการเปลี่ยนแปลง" },
        load: {
          en: () => import("@/content/docs/changelog.mdx"),
          th: () => import("@/content/docs/th/changelog.mdx"),
        },
      },
    ],
  },
];

export const DEFAULT_DOC = "quickstart";

export const findDoc = (slug: string) =>
  docsNav.flatMap((group) => group.pages).find((page) => page.slug === slug);
