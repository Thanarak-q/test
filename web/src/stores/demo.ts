import { atom } from "nanostores";

// These are local demonstration models, not hand-written API response types.
export type DemoKey = {
  id: string;
  name: string;
  masked: string;
  status: "active" | "revoked";
  createdAt: string;
  lastUsed: string | null;
};

const initialKeys: DemoKey[] = [
  {
    id: "production",
    name: "Production server",
    masked: "mk_demo_••••••••r7K2",
    status: "active",
    createdAt: "2026-08-12T03:00:00Z",
    lastUsed: "2026-09-05T03:42:00Z",
  },
  {
    id: "development",
    name: "Development",
    masked: "mk_demo_••••••••w9P4",
    status: "active",
    createdAt: "2026-08-20T08:00:00Z",
    lastUsed: "2026-09-05T02:15:00Z",
  },
  {
    id: "staging",
    name: "Staging environment",
    masked: "mk_demo_••••••••n2F8",
    status: "active",
    createdAt: "2026-08-28T04:00:00Z",
    lastUsed: "2026-09-04T09:30:00Z",
  },
  {
    id: "local",
    name: "Local testing",
    masked: "mk_demo_••••••••b5M1",
    status: "active",
    createdAt: "2026-09-03T01:00:00Z",
    lastUsed: null,
  },
  {
    id: "legacy",
    name: "Previous deployment",
    masked: "mk_demo_••••••••q3H6",
    status: "revoked",
    createdAt: "2026-07-18T03:00:00Z",
    lastUsed: "2026-08-29T07:00:00Z",
  },
];

export const $demoKeys = atom<DemoKey[]>(initialKeys);
export const $demoHasUsage = atom(true);
export const resetDemoKeys = () => {
  $demoKeys.set(initialKeys);
  $demoHasUsage.set(true);
};

export const createDemoKey = (name: string, startEmpty = false) => {
  const trimmed = name.trim();
  if (!trimmed || trimmed.length > 80)
    throw new Error("Enter a key name between 1 and 80 characters.");
  const id = crypto.randomUUID();
  const secret = `mk_demo_${crypto.randomUUID().replaceAll("-", "")}`;
  $demoKeys.set([
    {
      id,
      name: trimmed,
      masked: `mk_demo_••••••••${secret.slice(-4)}`,
      status: "active",
      createdAt: new Date().toISOString(),
      lastUsed: null,
    },
    ...(startEmpty ? [] : $demoKeys.get()),
  ]);
  if (startEmpty) $demoHasUsage.set(false);
  // The full demo secret is returned once and never retained in the store.
  return secret;
};

export const revokeDemoKey = (id: string) => {
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
