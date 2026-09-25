import { BrandMark } from "@/components/ui/mascot";
import { BookIcon, ChartIcon, KeyIcon } from "@/components/ui/nav-icons";
import { Link, Outlet } from "@tanstack/react-router";
import { Menu, X } from "lucide-react";
import { useEffect, useRef } from "react";

const Navigation = ({ onNavigate }: { onNavigate?: () => void }) => (
  <nav className="navigation" aria-label="Main navigation">
    <Link
      to="/api-keys"
      activeOptions={{ includeSearch: false }}
      className="nav-item"
      onClick={onNavigate}
    >
      <KeyIcon />
      API Keys
    </Link>
    <Link
      to="/usage"
      activeOptions={{ includeSearch: false }}
      className="nav-item"
      onClick={onNavigate}
    >
      <ChartIcon />
      Usage
    </Link>
    <Link to="/docs" className="nav-item" onClick={onNavigate}>
      <BookIcon />
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
          <BrandMark />
          <span>Mathew API</span>
        </div>
        <div className="workspace-label">Your workspace</div>
        <Navigation />
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
          <BrandMark size={22} />
          <span>Mathew API</span>
        </div>
        <main id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
      <dialog ref={drawer} className="navigation-drawer" aria-label="Navigation">
        <div className="drawer-header">
          <span className="brand">
            <BrandMark />
            Mathew API
          </span>
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
