// Every value marked TBD is a placeholder. Search for TBD before release.
//
// The single source for every number, name and URL shown in the docs: page
// content reads from here and never spells a value out itself.
// TODO(limits-endpoint): `limits` and `models` should come from the API so the
// docs cannot drift from what the server enforces.
export const TBD = "TBD" as const;

export const docsValues = {
  baseUrl: "https://api.example.invalid/v1", // TBD: production URL
  providerName: TBD, // TBD: who receives prompts
  providerPolicyUrl: TBD, // TBD: provider retention policy
  keyPrefix: "mthw01",
  maxKeysPerUser: 5,
  revokeWindowSeconds: 60,
  retentionDays: { audit: 90, usage: 60 },
  limits: {
    preAuth: { capacity: 0, refillPerSecond: 0 }, // TBD
    requests: { capacity: 0, refillPerSecond: 0 }, // TBD
    tokens: { capacity: 0, refillPerSecond: 0 }, // TBD
    maxInputTokens: 0, // TBD
    maxOutputTokens: 0, // TBD
  },
  models: [
    { name: "model-a", purpose: "chat", contextWindow: 0 }, // TBD
    { name: "embed-a", purpose: "embedding", contextWindow: 0 }, // TBD
  ],
  unsupportedParams: ["stream", "tools", "functions", "n > 1"],
} as const;

export type DocsValues = typeof docsValues;
