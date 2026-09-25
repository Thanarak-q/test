import { defineConfig } from "orval";

// FastAPI serves the schema at /openapi.json — start the API before `bun run gen:api`.
export default defineConfig({
  matthew: {
    input: "http://localhost:8000/openapi.json",
    output: {
      target: "./src/api/generated/endpoints.ts",
      schemas: "./src/api/generated/model",
      client: "react-query",
      httpClient: "axios",
      mode: "tags-split",
      override: {
        mutator: { path: "./src/api/mutator.ts", name: "customInstance" },
        operations: {
          // Every key route is POST so no key id travels in a URL, but listing
          // is a read: generate it as a query so it caches and refetches.
          listApiKeys: { query: { useQuery: true, useMutation: false } },
          listModels: { query: { useQuery: true, useMutation: false } },
        },
      },
    },
  },
});
