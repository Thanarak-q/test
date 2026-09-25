import { Dashboard } from "@/components/layout/dashboard";
import { Link, createRootRoute } from "@tanstack/react-router";

export const Route = createRootRoute({
  component: Dashboard,
  notFoundComponent: () => (
    <div className="empty-state">
      <h1>Page not found</h1>
      <p>This page isn't part of your workspace.</p>
      <Link to="/api-keys" className="button button-primary">
        Go to API Keys
      </Link>
    </div>
  ),
});
