import { Dashboard } from "@/components/layout/dashboard";
import { Mascot } from "@/components/ui/mascot";
import { Link, createRootRoute } from "@tanstack/react-router";

export const Route = createRootRoute({
  component: Dashboard,
  notFoundComponent: () => (
    <div className="empty-state">
      <Mascot size={160} className="mascot-lost" />
      <h1>Page not found</h1>
      <p>Our ranger searched every trail. This page isn't part of your workspace.</p>
      <Link to="/api-keys" className="button button-primary">
        Go to API Keys
      </Link>
    </div>
  ),
});
