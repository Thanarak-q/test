import { UsagePage, usageSearchSchema } from "@/pages/usage";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/usage")({
  component: UsagePage,
  validateSearch: usageSearchSchema,
});
