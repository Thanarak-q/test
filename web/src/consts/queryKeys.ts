export const queryKeys = {
  health: {
    all: () => ["health"] as const,
    status: () => [...queryKeys.health.all(), "status"] as const,
  },
};
