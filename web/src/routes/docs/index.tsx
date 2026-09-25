import { DEFAULT_DOC } from "@/pages/docs/nav";
import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/docs/")({
  beforeLoad: ({ search }) => {
    throw redirect({ to: "/docs/$", params: { _splat: DEFAULT_DOC }, search, replace: true });
  },
});
