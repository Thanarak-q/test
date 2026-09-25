import {
  $demoHasUsage,
  $demoKeys,
  createDemoKey,
  DEMO_MAX_ACTIVE_KEYS,
  getDemoKeyPrefix,
  getDemoUsage,
  resetDemoKeys,
  revokeDemoKey,
} from "../demo";

afterEach(resetDemoKeys);

it("creates unique safe prefixes without retaining secrets and revokes only that key", async () => {
  const previous = $demoKeys.get();
  const secret = await createDemoKey("  Integration test  ");
  const created = $demoKeys.get()[0];
  expect(created.name).toBe("Integration test");
  expect(secret).toMatch(/^mk_demo_/);
  expect(JSON.stringify($demoKeys.get())).not.toContain(secret);
  expect(created.keyPrefix).toBe(getDemoKeyPrefix(secret));
  expect(created.keyPrefix).not.toBe(secret.slice(-4));
  await revokeDemoKey(created.id);
  expect($demoKeys.get()[0].status).toBe("revoked");
  expect($demoKeys.get().slice(1)).toEqual(previous);
  const secondSecret = await createDemoKey("Second key");
  expect($demoKeys.get()[0].keyPrefix).toBe(getDemoKeyPrefix(secondSecret));
  expect($demoKeys.get()[0].keyPrefix).not.toBe(created.keyPrefix);
  await expect(revokeDemoKey(created.id)).rejects.toThrow("no longer active");
});

it("rejects invalid names without changing the key list", async () => {
  const previous = $demoKeys.get();
  await expect(createDemoKey("   ")).rejects.toThrow();
  await expect(createDemoKey("x".repeat(101))).rejects.toThrow();
  expect($demoKeys.get()).toEqual(previous);
});

it("keeps a first-key demo empty of previous keys and usage", async () => {
  await createDemoKey("First key", true);
  expect($demoKeys.get()).toHaveLength(1);
  expect($demoHasUsage.get()).toBe(false);
});

it("orders keys newest first and enforces the active key limit", async () => {
  expect($demoKeys.get().map((key) => key.id)).toEqual([
    "local",
    "staging",
    "development",
    "production",
    "legacy",
  ]);
  const secret = await createDemoKey("Fifth key");
  expect($demoKeys.get().filter((key) => key.status === "active")).toHaveLength(
    DEMO_MAX_ACTIVE_KEYS,
  );
  await expect(createDemoKey("Sixth key")).rejects.toThrow("up to 5 active API keys");
  expect($demoKeys.get()[0]).toMatchObject({
    keyPrefix: getDemoKeyPrefix(secret),
    neverUsed: true,
    recommendRevoke: false,
  });
});

it("keeps report totals consistent across filters and retains historical usage after revocation", async () => {
  const all = getDemoUsage(7, "all");
  const production = getDemoUsage(7, "production");
  expect(production.requests).toBe(all.breakdown.find((row) => row.id === "production")?.requests);
  expect(all.requests).toBe(all.series.reduce((sum, day) => sum + day.requests, 0));
  expect(all.tokens).toBe(all.breakdown.reduce((sum, row) => sum + row.tokens, 0));
  expect(getDemoUsage(30, "all").requests).toBeGreaterThan(all.requests);
  expect(getDemoUsage(30, "all").series.slice(-7)).toEqual(all.series);
  expect(getDemoUsage(7, "unknown").requests).toBe(0);
  await revokeDemoKey("production");
  expect(getDemoUsage(7, "production")).toEqual(production);
});
