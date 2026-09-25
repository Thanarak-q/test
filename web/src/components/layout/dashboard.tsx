import { resetDemoKeys } from "@/stores/demo";
import { Link, Outlet } from "@tanstack/react-router";
import { ChartNoAxesCombined, KeyRound, Menu, RotateCcw, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

const Navigation = ({ onNavigate }: { onNavigate?: () => void }) => (
  <nav className="navigation" aria-label="Main navigation">
    <Link
      to="/api-keys"
      activeOptions={{ includeSearch: false }}
      className="nav-item"
      onClick={onNavigate}
    >
      <KeyRound />
      API Keys
    </Link>
    <Link
      to="/usage"
      activeOptions={{ includeSearch: false }}
      className="nav-item"
      onClick={onNavigate}
    >
      <ChartNoAxesCombined />
      Usage
    </Link>
  </nav>
);

const DemoNotice = () => (
  <div className="demo-notice">
    <div className="demo-notice-title">
      <span className="demo-dot" />
      Demo workspace
    </div>
    <p>Sample data. Keys created here won’t access the Mathew AI API.</p>
    <button
      className="text-button"
      onClick={() => {
        resetDemoKeys();
        toast.success("Demo keys reset");
      }}
    >
      <RotateCcw />
      Reset demo keys
    </button>
  </div>
);

export const Dashboard = () => {
  const drawer = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const query = window.matchMedia("(min-width: 761px)");
    const closeDrawer = () => {
      if (query.matches) drawer.current?.close();
    };
    query.addEventListener("change", closeDrawer);
    return () => query.removeEventListener("change", closeDrawer);
  }, []);
  return (
    <div className="dashboard">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            m
          </span>
          <span>Mathew AI</span>
          <span className="brand-label">Platform</span>
        </div>
        <div className="workspace-label">Your workspace</div>
        <Navigation />
        <div className="sidebar-bottom">
          <DemoNotice />
          <div className="account">
            <span className="avatar">D</span>
            <div>
              Demo customer<span>Personal account</span>
            </div>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <div className="mobile-header">
          <button
            className="icon-button"
            aria-label="Open navigation"
            onClick={() => drawer.current?.showModal()}
          >
            <Menu />
          </button>
          <span>Mathew AI</span>
          <span className="demo-badge">Demo</span>
        </div>
        <main id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
      <dialog ref={drawer} className="navigation-drawer" aria-label="Navigation">
        <div className="drawer-header">
          <span className="brand">Mathew AI</span>
          <button
            className="icon-button"
            aria-label="Close navigation"
            onClick={() => drawer.current?.close()}
          >
            <X />
          </button>
        </div>
        <Navigation onNavigate={() => drawer.current?.close()} />
        <div className="sidebar-bottom">
          <DemoNotice />
        </div>
      </dialog>
    </div>
  );
};
