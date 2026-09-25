import { AdminModelsPage } from "@/pages/admin-models";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/admin/models")({
  component: AdminModelsPage,
});
