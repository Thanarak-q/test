import { describe, expect, it } from "vitest";
import { cn } from "../cn";

describe("cn", () => {
  it("keeps the last of two conflicting tailwind utilities", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
  });

  it("drops falsy conditional classes", () => {
    const isHidden = false;

    expect(cn("flex", isHidden && "hidden", undefined, "gap-2")).toBe("flex gap-2");
  });
});
