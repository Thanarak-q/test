import { defineConfig } from "orval";

// FastAPI serves the schema at /openapi.json — start the API before `bun run gen:api`.
export default defineConfig({
  matthew: {
    input: "http://localhost:8000/openapi.json",
    output: {
      target: "./src/api/generated/endpoints.ts",
      schemas: "./src/api/generated/model",
      client: "react-query",
      mode: "tags-split",
      override: {
        mutator: { path: "./src/api/mutator.ts", name: "customInstance" },
      },
    },
  },
});
