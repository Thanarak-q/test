import { Link, Outlet } from "@tanstack/react-router";
import { BookOpen, ChartNoAxesCombined, KeyRound, Menu, X } from "lucide-react";
import { useEffect, useRef } from "react";

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
    <Link to="/docs" className="nav-item" onClick={onNavigate}>
      <BookOpen />
      Docs
    </Link>
  </nav>
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
          {/* TODO(session): show the signed-in user from the main application. */}
          <div className="account">
            <span className="avatar" aria-hidden="true">
              <KeyRound />
            </span>
            <div>
              Your account<span>Personal account</span>
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
      </dialog>
    </div>
  );
};
