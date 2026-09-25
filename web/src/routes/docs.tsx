import { DocsLayout, docsSearchSchema } from "@/pages/docs";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/docs")({
  component: DocsLayout,
  validateSearch: docsSearchSchema,
});
