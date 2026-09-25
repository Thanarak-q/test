import { CircleAlert, LockKeyhole, RefreshCw } from "lucide-react";
import { z } from "zod";

import { Mascot } from "@/components/ui/mascot";

export const previewSchema = z
  .enum(["normal", "empty", "loading", "error", "session"])
  .catch("normal")
  .optional();
export type PreviewState = z.infer<typeof previewSchema>;

export const PageState = ({ state, onRetry }: { state: PreviewState; onRetry: () => void }) => {
  if (state === "loading")
    return (
      <div className="loading-state" role="status" aria-label="Loading dashboard">
        <span className="sr-only">Loading dashboard…</span>
        {[0, 1, 2, 3, 4].map((index) => (
          <div className="skeleton-row" key={index}>
            <span />
            <span />
            <span />
          </div>
        ))}
      </div>
    );
  const session = state === "session";
  return (
    <div className="empty-state" role="alert">
      <div className="mascot-with-badge">
        <Mascot size={112} />
        <span className="state-badge">{session ? <LockKeyhole /> : <CircleAlert />}</span>
      </div>
      <h2>{session ? "Your session has expired" : "We couldn't load this page"}</h2>
      <p>
        {session
          ? "Your keys haven't changed. Sign in again to continue."
          : "Your data hasn't changed. Try loading the page again."}
      </p>
      <button className="button button-secondary" onClick={onRetry}>
        <RefreshCw />
        Try again
      </button>
    </div>
  );
};
