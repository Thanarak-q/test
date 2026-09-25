import { Link, Outlet, useParams } from "@tanstack/react-router";
import type { MDXComponents } from "mdx/types";
import { createElement, lazy, Suspense, type ComponentProps } from "react";
import { z } from "zod";
import { PreviewBadge, ToBeConfirmed } from "./components/Badge";
import { CodeBlock } from "./components/CodeBlock";
import { CodeTabs, LANGUAGES } from "./components/CodeTabs";
import { Value } from "./components/Value";
import { docsNav, findDoc } from "./nav";

export const docsSearchSchema = z.object({
  lang: z.enum(LANGUAGES).optional().catch(undefined),
});

// In-app links in MDX go through the router; everything else is a plain,
// external link.
const DocLink = ({ href = "", children, ...rest }: ComponentProps<"a">) =>
  href.startsWith("/") ? (
    <Link to={href}>{children}</Link>
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
  PreviewBadge,
  ToBeConfirmed,
  Value,
};

// Created once per page, at module load: a component built during render
// would remount (and refetch its chunk) on every render.
const pageContent = new Map(
  docsNav.flatMap((group) => group.pages).map((page) => [page.slug, lazy(page.load)]),
);

export const DocsLayout = () => (
  <>
    <title>Docs · Mathew AI</title>
    <div className="docs">
      <nav className="docs-nav" aria-label="Documentation">
        {docsNav.map((group) => (
          <div key={group.group} className="docs-nav-group">
            <span className="workspace-label">{group.group}</span>
            {group.pages.map((page) => (
              <Link
                key={page.slug}
                to="/docs/$"
                params={{ _splat: page.slug }}
                search={(prev) => prev}
                className="nav-item"
              >
                {page.title}
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

export const DocsPage = () => {
  const { _splat: slug = "" } = useParams({ from: "/docs/$" });
  const entry = findDoc(slug);
  const Content = pageContent.get(slug);
  if (!entry || !Content)
    return (
      <div className="empty-state">
        <h1>Page not found</h1>
        <p>This page isn’t part of the documentation.</p>
        <Link to="/docs/$" params={{ _splat: "quickstart" }} className="button button-primary">
          Go to Quickstart
        </Link>
      </div>
    );
  return (
    <article className="docs-article">
      <title>{`${entry.title} · Docs · Mathew AI`}</title>
      <header className="docs-header">
        <h1>{entry.title}</h1>
        {entry.preview && <PreviewBadge />}
      </header>
      {entry.preview && (
        <p className="inline-notice docs-preview-notice">
          This endpoint is still being built. The request and response shapes below are what it will
          accept and return; until this notice is gone they may not work end to end.
        </p>
      )}
      <Suspense fallback={<p className="muted">Loading…</p>}>
        {/* createElement, not <Content />: the component comes from the
            module-level map, so its identity is stable per slug, but the
            static-components lint rule cannot see through Map.get. */}
        {createElement(Content, { components: mdxComponents })}
      </Suspense>
    </article>
  );
};
