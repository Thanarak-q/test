import { TBD } from "./values";

// Placeholders are deliberately fake so nobody mistakes them for real values:
// the literal TBD, a zero in a limit or context-window field, or a URL on the
// reserved `.invalid` domain.
const ZERO_IS_PLACEHOLDER = /(^|\.)limits\.|contextWindow$/;
const INVALID_HOST = /^https?:\/\/[^/]*\.invalid(\/|:|$)/;

export const isPlaceholder = (value: unknown, path = "limits.") =>
  value === TBD ||
  (value === 0 && ZERO_IS_PLACEHOLDER.test(path)) ||
  (typeof value === "string" && INVALID_HOST.test(value));

/** Dotted paths of every placeholder left in `values`, e.g. `models[0].contextWindow`. */
export const listPlaceholders = (values: unknown, path = ""): string[] => {
  if (Array.isArray(values))
    return values.flatMap((item, index) => listPlaceholders(item, `${path}[${index}]`));
  if (values !== null && typeof values === "object")
    return Object.entries(values).flatMap(([key, value]) =>
      listPlaceholders(value, path ? `${path}.${key}` : key),
    );
  return isPlaceholder(values, path) ? [path] : [];
};
