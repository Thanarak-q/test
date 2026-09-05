import {
  $demoHasUsage,
  $demoKeys,
  createDemoKey,
  getDemoUsage,
  resetDemoKeys,
  revokeDemoKey,
} from "../demo";

afterEach(resetDemoKeys);

it("creates a demo key without retaining its secret and revokes only that key", () => {
  const previous = $demoKeys.get();
  const secret = createDemoKey("  Integration test  ");
  const created = $demoKeys.get()[0];
  expect(created.name).toBe("Integration test");
  expect(secret).toMatch(/^mk_demo_/);
  expect(JSON.stringify($demoKeys.get())).not.toContain(secret);
  expect(created.masked).toContain(secret.slice(-4));
  revokeDemoKey(created.id);
  expect($demoKeys.get()[0].status).toBe("revoked");
  expect($demoKeys.get().slice(1)).toEqual(previous);
  expect(() => revokeDemoKey(created.id)).toThrow("no longer active");
});

it("rejects invalid names without changing the key list", () => {
  const previous = $demoKeys.get();
  expect(() => createDemoKey("   ")).toThrow();
  expect(() => createDemoKey("x".repeat(81))).toThrow();
  expect($demoKeys.get()).toEqual(previous);
});

it("keeps a first-key demo empty of previous keys and usage", () => {
  createDemoKey("First key", true);
  expect($demoKeys.get()).toHaveLength(1);
  expect($demoHasUsage.get()).toBe(false);
});

it("keeps report totals consistent across filters and retains historical usage after revocation", () => {
  const all = getDemoUsage(7, "all");
  const production = getDemoUsage(7, "production");
  expect(production.requests).toBe(all.breakdown.find((row) => row.id === "production")?.requests);
  expect(all.requests).toBe(all.series.reduce((sum, day) => sum + day.requests, 0));
  expect(all.tokens).toBe(all.breakdown.reduce((sum, row) => sum + row.tokens, 0));
  expect(getDemoUsage(30, "all").requests).toBeGreaterThan(all.requests);
  expect(getDemoUsage(30, "all").series.slice(-7)).toEqual(all.series);
  expect(getDemoUsage(7, "unknown").requests).toBe(0);
  revokeDemoKey("production");
  expect(getDemoUsage(7, "production")).toEqual(production);
});
