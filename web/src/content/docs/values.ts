// Every value marked TBD is a placeholder. Search for TBD before release.
//
// The single source for every number, name and URL shown in the docs: page
// content reads from here and never spells a value out itself.
// TODO(limits-endpoint): `limits` and `models` should come from the API so the
// docs cannot drift from what the server enforces.
export const TBD = "TBD" as const;

export const docsValues = {
  baseUrl: "https://api.example.invalid/v1", // TBD: production URL
  providerName: "OpenAI",
  providerPolicyUrl: "https://openai.com/enterprise-privacy/",
  keyPrefix: "mthw01",
  maxKeysPerUser: 5,
  revokeWindowSeconds: 60,
  retentionDays: { audit: 90, usage: 60 },
  limits: {
    // api/app/services/pre_auth_rate_limit.py, docs/DECISIONS.md
    preAuth: { capacity: 60, refillPerSecond: 1 },
    // api/app/constants/perkey_rate_limit.py
    requests: { capacity: 10, refillPerMinute: 20 },
    tokens: { capacity: 20_000, refillPerMinute: 20_000 },
    maxInputTokens: 8_192,
    // POLICY_CAP in api/app/constants/llm.py (a model's own cap may be lower)
    maxOutputTokens: 4_096,
  },
  models: [
    // The llm_models whitelist seeded by the migration.
    { name: "gpt-4o", purpose: "chat", contextWindow: 128_000 },
    { name: "gpt-4.1", purpose: "chat", contextWindow: 1_047_576 },
    { name: "embed-a", purpose: "embedding", contextWindow: 0 }, // TBD
  ],
  unsupportedParams: ["stream", "tools", "functions", "n > 1"],
} as const;

export type DocsValues = typeof docsValues;
