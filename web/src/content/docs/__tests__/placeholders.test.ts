import { isPlaceholder, listPlaceholders } from "../placeholders";
import { docsValues, TBD } from "../values";

// Runs in two modes:
//   bun run test                  development: lists what is left, passes
//   vitest run --mode production  release (the `build` script): any placeholder fails
const release = import.meta.env.MODE === "production";
const remaining = listPlaceholders(docsValues);

it("lists every placeholder left in values.ts", () => {
  if (remaining.length) {
    console.info(
      `docs placeholders still to confirm (${remaining.length}):\n  ${remaining.join("\n  ")}`,
    );
  }
  if (release) expect(remaining).toEqual([]);
});

it("detects each kind of placeholder", () => {
  expect(listPlaceholders({ a: TBD, limits: { x: 0 }, models: [{ contextWindow: 0 }] })).toEqual([
    "a",
    "limits.x",
    "models[0].contextWindow",
  ]);
  expect(isPlaceholder("https://api.example.invalid/v1")).toBe(true);
  expect(isPlaceholder("https://api.example.com/v1")).toBe(false);
  // A real zero outside limits is not a placeholder, and real limits are not.
  expect(listPlaceholders({ retries: 0, limits: { capacity: 20 } })).toEqual([]);
});
