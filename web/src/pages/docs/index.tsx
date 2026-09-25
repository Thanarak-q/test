import { Link, Outlet, useParams, useSearch } from "@tanstack/react-router";
import type { MDXComponents } from "mdx/types";
import { createElement, lazy, Suspense, type ComponentProps } from "react";
import { z } from "zod";
import { CodeBlock } from "./components/CodeBlock";
import { CodeTabs, LANGUAGES } from "./components/CodeTabs";
import { Value } from "./components/Value";
import { docsNav, findDoc, LOCALES, type Locale } from "./nav";

export const docsSearchSchema = z.object({
  lang: z.enum(LANGUAGES).optional().catch(undefined),
  locale: z.enum(LOCALES).optional().catch(undefined),
});

const useLocale = (): Locale => useSearch({ from: "/docs" }).locale ?? "en";

const LOCALE_LABELS: Record<Locale, string> = { en: "EN", th: "ไทย" };

const copy = {
  en: {
    docs: "Docs",
    notFound: "Page not found",
    notFoundHelp: "This page isn’t part of the documentation.",
    goQuickstart: "Go to Quickstart",
    loading: "Loading…",
    language: "Language",
  },
  th: {
    docs: "เอกสาร",
    notFound: "ไม่พบหน้านี้",
    notFoundHelp: "หน้านี้ไม่ได้อยู่ในเอกสาร",
    goQuickstart: "ไปที่เริ่มต้นอย่างรวดเร็ว",
    loading: "กำลังโหลด…",
    language: "ภาษา",
  },
} satisfies Record<Locale, Record<string, string>>;

const LocaleSwitch = () => {
  const locale = useLocale();
  return (
    <div className="locale-switch" role="group" aria-label={copy[locale].language}>
      {LOCALES.map((option) => (
        <Link
          key={option}
          to="."
          search={(prev) => ({ ...prev, locale: option === "en" ? undefined : option })}
          aria-current={option === locale ? "true" : undefined}
          lang={option}
        >
          {LOCALE_LABELS[option]}
        </Link>
      ))}
    </div>
  );
};

// In-app links in MDX go through the router; everything else is a plain,
// external link.
const DocLink = ({ href = "", children, ...rest }: ComponentProps<"a">) =>
  href.startsWith("/") ? (
    <Link to={href} search={(prev) => prev}>
      {children}
    </Link>
  ) : (
    <a href={href} target="_blank" rel="noreferrer noopener" {...rest}>
      {children}
    </a>
  );

const mdxComponents: MDXComponents = {
  a: DocLink,
  table: (props) => (
    <div className="table-scroll" role="region" tabIndex={0} aria-label="Table">
      <table className="data-table docs-table" {...props} />
    </div>
  ),
  CodeBlock,
  CodeTabs,
  Value,
};

// Created once per page and locale, at module load: a component built during
// render would remount (and refetch its chunk) on every render.
const pageContent = new Map(
  docsNav
    .flatMap((group) => group.pages)
    .flatMap((page) =>
      LOCALES.map((locale) => [`${locale}:${page.slug}`, lazy(page.load[locale])]),
    ),
);

export const DocsLayout = () => {
  const locale = useLocale();
  return (
    <>
      <title>{`${copy[locale].docs} · Mathew API`}</title>
      <div className="docs" lang={locale}>
        <nav className="docs-nav" aria-label="Documentation">
          <LocaleSwitch />
          {docsNav.map((group) => (
            <div key={group.group.en} className="docs-nav-group">
              <span className="workspace-label">{group.group[locale]}</span>
              {group.pages.map((page) => (
                <Link
                  key={page.slug}
                  to="/docs/$"
                  params={{ _splat: page.slug }}
                  search={(prev) => prev}
                  className="nav-item"
                >
                  {page.title[locale]}
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="docs-content">
          <Outlet />
        </div>
      </div>
    </>
  );
};

export const DocsPage = () => {
  const { _splat: slug = "" } = useParams({ from: "/docs/$" });
  const locale = useLocale();
  const entry = findDoc(slug);
  const Content = pageContent.get(`${locale}:${slug}`);
  if (!entry || !Content)
    return (
      <div className="empty-state">
        <h1>{copy[locale].notFound}</h1>
        <p>{copy[locale].notFoundHelp}</p>
        <Link
          to="/docs/$"
          params={{ _splat: "quickstart" }}
          search={(prev) => prev}
          className="button button-primary"
        >
          {copy[locale].goQuickstart}
        </Link>
      </div>
    );
  return (
    <article className="docs-article">
      <title>{`${entry.title[locale]} · ${copy[locale].docs} · Mathew API`}</title>
      <header className="docs-header">
        <h1>{entry.title[locale]}</h1>
      </header>
      <Suspense fallback={<p className="muted">{copy[locale].loading}</p>}>
        {/* createElement, not <Content />: the component comes from the
            module-level map, so its identity is stable per slug, but the
            static-components lint rule cannot see through Map.get. */}
        {createElement(Content, { components: mdxComponents })}
      </Suspense>
    </article>
  );
};
