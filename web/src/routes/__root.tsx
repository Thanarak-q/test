import { Outlet, createRootRoute } from "@tanstack/react-router";
import type { FC } from "react";

const RootLayout: FC = () => (
  <div className="min-h-dvh bg-background text-foreground">
    <Outlet />
  </div>
);

export const Route = createRootRoute({ component: RootLayout });
