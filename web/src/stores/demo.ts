import { atom } from "nanostores";

// These are local demonstration models, not hand-written API response types.
export type DemoKey = {
  id: string;
  name: string;
  keyPrefix: string;
  status: "active" | "revoked";
  createdAt: string;
  lastUsed: string | null;
  neverUsed: boolean;
  recommendRevoke: boolean;
};

export const DEMO_MAX_ACTIVE_KEYS = 5;
const DEMO_KEY_PREFIX_LENGTH = "mk_demo_".length + 8;

export const getDemoKeyPrefix = (secret: string) => secret.slice(0, DEMO_KEY_PREFIX_LENGTH);

const initialKeys: DemoKey[] = [
  {
    id: "production",
    name: "Production server",
    keyPrefix: "mk_demo_prod",
    status: "active",
    createdAt: "2026-08-12T03:00:00Z",
    lastUsed: "2026-09-05T03:42:00Z",
    neverUsed: false,
    recommendRevoke: false,
  },
  {
    id: "development",
    name: "Development",
    keyPrefix: "mk_demo_dev",
    status: "active",
    createdAt: "2026-08-20T08:00:00Z",
    lastUsed: "2026-09-05T02:15:00Z",
    neverUsed: false,
    recommendRevoke: false,
  },
  {
    id: "staging",
    name: "Staging environment",
    keyPrefix: "mk_demo_stage",
    status: "active",
    createdAt: "2026-08-28T04:00:00Z",
    lastUsed: "2026-09-04T09:30:00Z",
    neverUsed: false,
    recommendRevoke: false,
  },
  {
    id: "local",
    name: "Local testing",
    keyPrefix: "mk_demo_local",
    status: "active",
    createdAt: "2026-09-03T01:00:00Z",
    lastUsed: null,
    neverUsed: true,
    recommendRevoke: true,
  },
  {
    id: "legacy",
    name: "Previous deployment",
    keyPrefix: "mk_demo_legacy",
    status: "revoked",
    createdAt: "2026-07-18T03:00:00Z",
    lastUsed: "2026-08-29T07:00:00Z",
    neverUsed: false,
    recommendRevoke: false,
  },
];

const sortKeys = (keys: DemoKey[]) =>
  [...keys].sort(
    (left, right) =>
      right.createdAt.localeCompare(left.createdAt) || right.id.localeCompare(left.id),
  );

const initialSortedKeys = sortKeys(initialKeys);

export const $demoKeys = atom<DemoKey[]>(initialSortedKeys);
export const $demoHasUsage = atom(true);
export const resetDemoKeys = () => {
  $demoKeys.set(initialSortedKeys);
  $demoHasUsage.set(true);
};

const waitForDemoOperation = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

export const getDemoActiveKeyCount = () =>
  $demoKeys.get().filter((entry) => entry.status === "active").length;

export const createDemoKey = async (name: string, startEmpty = false) => {
  const trimmed = name.trim();
  if (!trimmed || trimmed.length > 100)
    throw new Error("Enter a key name between 1 and 100 characters.");
  await waitForDemoOperation();
  if (getDemoActiveKeyCount() >= DEMO_MAX_ACTIVE_KEYS)
    throw new Error("You can have up to 5 active API keys. Revoke one before creating another.");
  const id = crypto.randomUUID();
  let secret = `mk_demo_${crypto.randomUUID().replaceAll("-", "")}`;
  let keyPrefix = getDemoKeyPrefix(secret);
  while ($demoKeys.get().some((key) => key.keyPrefix === keyPrefix)) {
    secret = `mk_demo_${crypto.randomUUID().replaceAll("-", "")}`;
    keyPrefix = getDemoKeyPrefix(secret);
  }
  const currentKeys = startEmpty ? [] : $demoKeys.get();
  $demoKeys.set(
    sortKeys([
      {
        id,
        name: trimmed,
        keyPrefix,
        status: "active",
        createdAt: new Date().toISOString(),
        lastUsed: null,
        neverUsed: true,
        recommendRevoke: false,
      },
      ...currentKeys,
    ]),
  );
  if (startEmpty) $demoHasUsage.set(false);
  // The full demo secret is returned once and never retained in the store.
  return secret;
};

export const revokeDemoKey = async (id: string) => {
  await waitForDemoOperation();
  const key = $demoKeys.get().find((entry) => entry.id === id);
  if (!key || key.status === "revoked")
    throw new Error("This key is no longer active. Close this dialog and check the list.");
  $demoKeys.set(
    $demoKeys.get().map((entry) => (entry.id === id ? { ...entry, status: "revoked" } : entry)),
  );
};

export const formatDate = (date: string) =>
  new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "Asia/Bangkok",
  }).format(new Date(date));

export const formatNumber = (value: number) => new Intl.NumberFormat("en-US").format(value);

// Historical, synthetic usage stays fixed when a demo key is revoked.
// Local aggregation below is fixture generation, not a duplicate API calculation.
export const getDemoUsage = (days: number, keyId: string) => {
  const weights: Record<string, number> = {
    production: 1,
    development: 0.24,
    staging: 0.08,
    legacy: 0.02,
  };
  const series = Array.from({ length: days }, (_, index) => {
    const date = new Date(Date.UTC(2026, 8, 6 - days + index));
    const dayIndex = Math.floor(date.getTime() / 86_400_000);
    const base = 290 + ((dayIndex * 137 + date.getUTCDate() * 83) % 810);
    const perKey = Object.entries(weights).map(([id, weight]) => {
      const key = initialKeys.find((entry) => entry.id === id)!;
      const day = date.toISOString().slice(0, 10);
      const hadActivity =
        day >= key.createdAt.slice(0, 10) &&
        key.lastUsed !== null &&
        day <= key.lastUsed.slice(0, 10);
      const requests = hadActivity ? Math.round(base * weight) : 0;
      return { id, requests, tokens: requests * (880 + (dayIndex % 5) * 71) };
    });
    const rows = keyId === "all" ? perKey : perKey.filter((row) => row.id === keyId);
    return {
      date: date.toISOString(),
      requests: rows.reduce((sum, row) => sum + row.requests, 0),
      tokens: rows.reduce((sum, row) => sum + row.tokens, 0),
      perKey,
    };
  });
  return {
    series,
    requests: series.reduce((sum, day) => sum + day.requests, 0),
    tokens: series.reduce((sum, day) => sum + day.tokens, 0),
    breakdown: Object.keys(weights)
      .filter((id) => keyId === "all" || keyId === id)
      .map((id) => ({
        id,
        requests: series.reduce(
          (sum, day) => sum + (day.perKey.find((row) => row.id === id)?.requests ?? 0),
          0,
        ),
        tokens: series.reduce(
          (sum, day) => sum + (day.perKey.find((row) => row.id === id)?.tokens ?? 0),
          0,
        ),
      }))
      .filter((row) => row.requests > 0),
  };
};
