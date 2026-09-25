/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { docsValues } from "../values";

// values.ts is the only place a value may appear. Page content refers to
// values by path (<Value path="…" />) or through samples.ts. Read from disk:
// an import would hand back compiled MDX, not what the author wrote.
const root = path.resolve(import.meta.dirname, "..");
const pages = Object.fromEntries(
  readdirSync(root, { recursive: true, encoding: "utf8" })
    .filter((file) => file.endsWith(".mdx"))
    .map((file) => [file, readFileSync(path.join(root, file), "utf8")]),
);

const leaves = (value: unknown): (string | number)[] =>
  Array.isArray(value)
    ? value.flatMap(leaves)
    : value !== null && typeof value === "object"
      ? Object.values(value).flatMap(leaves)
      : typeof value === "string" || typeof value === "number"
        ? [value]
        : [];

// Words that are both a value and ordinary English in prose. "OpenAI" is the
// provider, and also the name of the SDKs the migration guide talks about.
const PROSE = new Set(["chat", "embedding", "TBD", "stream", "tools", "functions", "OpenAI"]);
const values = [...new Set(leaves(docsValues))].filter(
  (value) => !(typeof value === "string" && PROSE.has(value)) && value !== 0,
);

it("finds the docs pages", () => {
  expect(Object.keys(pages).length).toBeGreaterThan(10);
});

it.each(Object.entries(pages))("%s spells out no value from values.ts", (_, text) => {
  for (const value of values) {
    const pattern =
      typeof value === "number"
        ? new RegExp(`(?<![\\w.\\[-])${value}(?![\\w.%])`)
        : new RegExp(value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    expect(text, `literal ${JSON.stringify(value)}`).not.toMatch(pattern);
  }
});
