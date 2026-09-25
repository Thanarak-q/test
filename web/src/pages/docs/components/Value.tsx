import { isPlaceholder } from "@/content/docs/placeholders";
import { docsValues } from "@/content/docs/values";

// `path` is a dotted path into values.ts ("limits.tokens.capacity",
// "models[0].name"), so page content names a value without spelling it out.
export const readValue = (path: string): unknown => {
  const value = path
    .replace(/\[(\d+)\]/g, ".$1")
    .split(".")
    .reduce<unknown>(
      (node, key) =>
        node !== null && typeof node === "object"
          ? (node as Record<string, unknown>)[key]
          : undefined,
      docsValues,
    );
  if (value === undefined) throw new Error(`docs: no value at "${path}" in values.ts`);
  return value;
};

const format = (value: unknown) =>
  typeof value === "number" ? new Intl.NumberFormat("en-US").format(value) : String(value);

export const Value = ({
  path,
  unit,
  code = false,
}: {
  path: string;
  unit?: string;
  code?: boolean;
}) => {
  const value = readValue(path);
  // The release build refuses to ship placeholders, so this only shows in development.
  if (isPlaceholder(value, path)) return <>—</>;
  if (Array.isArray(value))
    return (
      <>
        {value.map((item, index) => (
          <span key={String(item)}>
            {index > 0 && ", "}
            <code>{String(item)}</code>
          </span>
        ))}
      </>
    );
  const text = format(value);
  return (
    <>
      {code ? <code>{text}</code> : text}
      {unit && ` ${unit}`}
    </>
  );
};
