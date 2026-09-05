import { Dialog } from "@/components/ui/dialog";
import { FilterSelect } from "@/components/ui/filter-select";
import { PageState, previewSchema } from "@/components/ui/page-state";
import { $demoKeys, createDemoKey, formatDate, revokeDemoKey, type DemoKey } from "@/stores/demo";
import { useStore } from "@nanostores/react";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import {
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  KeyRound,
  LockKeyhole,
  MoveHorizontal,
  Plus,
  Search,
  ShieldAlert,
  Trash2,
  X,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { z } from "zod";

export const keySearchSchema = z.object({
  q: z.string().catch("").optional(),
  status: z.enum(["active", "revoked", "all"]).catch("active").optional(),
  page: z.coerce.number().int().min(1).max(100000).catch(1).optional(),
  preview: previewSchema,
});

const CreateKeyDialog = ({
  onClose,
  onCreated,
  startEmpty,
}: {
  onClose: () => void;
  onCreated: () => void;
  startEmpty: boolean;
}) => {
  const [name, setName] = useState("");
  const [secret, setSecret] = useState("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const create = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      setSecret(createDemoKey(name, startEmpty));
      setError("");
      onCreated();
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "We couldn't create the demo key. Try again.",
      );
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
      setError("");
    } catch {
      setError("Clipboard access isn't available. Select the secret below and copy it manually.");
    }
  };
  return (
    <Dialog title={secret ? "Save your secret key" : "Create new secret key"} onClose={onClose}>
      {secret ? (
        <div className="modal-body">
          <div className="success-heading">
            <Check />
            <span>Demo key created</span>
          </div>
          <p>
            Copy this key now. You won’t be able to see the full secret again after closing this
            dialog.
          </p>
          <label className="field-label" htmlFor="new-secret">
            Secret key
          </label>
          <div className="secret-field">
            <input
              id="new-secret"
              autoFocus
              readOnly
              value={secret}
              onFocus={(event) => event.target.select()}
            />
            <button
              className="icon-button"
              onClick={() => void copy()}
              aria-label={copied ? "Secret copied" : "Copy secret key"}
            >
              {copied ? <Check /> : <Copy />}
            </button>
          </div>
          <p className="field-help">This is a demo key. It cannot access the Mathew AI API.</p>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="modal-actions">
            <span className="copy-feedback" role="status">
              {copied ? "Copied to clipboard" : ""}
            </span>
            <button className="button button-primary" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      ) : (
        <form className="modal-body" onSubmit={create}>
          <p>Give your key a name so you can recognize where it’s used.</p>
          <label className="field-label" htmlFor="key-name">
            Name
          </label>
          <input
            id="key-name"
            autoFocus
            className="text-input"
            placeholder="e.g. Production server"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={80}
            autoComplete="off"
            aria-describedby="key-name-help"
          />
          <p id="key-name-help" className="field-help">
            Up to 80 characters. You can create separate keys for each application.
          </p>
          <div className="inline-notice">
            <LockKeyhole />
            <span>This demo creates a sample secret with no API access.</span>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="modal-actions">
            <button type="button" className="button button-secondary" onClick={onClose}>
              Cancel
            </button>
            <button className="button button-primary" type="submit" disabled={!name.trim()}>
              Create secret key
            </button>
          </div>
        </form>
      )}
    </Dialog>
  );
};

const RevokeKeyDialog = ({ entry, onClose }: { entry: DemoKey; onClose: () => void }) => {
  const [error, setError] = useState("");
  return (
    <Dialog title="Revoke API key?" onClose={onClose}>
      <div className="modal-body">
        <div className="revoke-key">
          <KeyRound />
          <div>
            <strong>{entry.name}</strong>
            <code>{entry.masked}</code>
          </div>
        </div>
        <p>
          Revoking a live key stops applications using it from accessing the API. This action cannot
          be undone.
        </p>
        <div className="inline-notice">
          <ShieldAlert />
          <span>In this demo, only the sample key’s status changes.</span>
        </div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button className="button button-secondary" onClick={onClose}>
            Keep key
          </button>
          <button
            className="button button-danger"
            onClick={() => {
              try {
                revokeDemoKey(entry.id);
                toast.success(`“${entry.name}” revoked`);
                onClose();
              } catch (error) {
                setError(
                  error instanceof Error ? error.message : "Couldn't revoke this key. Try again.",
                );
              }
            }}
          >
            Revoke key
          </button>
        </div>
      </div>
    </Dialog>
  );
};

export const ApiKeysPage = () => {
  const keys = useStore($demoKeys);
  const search = useSearch({ from: "/api-keys" });
  const navigate = useNavigate({ from: "/api-keys" });
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<DemoKey | null>(null);
  const query = search.q ?? "";
  const status = search.status ?? "active";
  const blocked = ["error", "loading", "session"].includes(search.preview ?? "");
  const visibleKeys = search.preview === "empty" ? [] : keys;
  const filtered = visibleKeys.filter(
    (key) =>
      (status === "all" || key.status === status) &&
      `${key.name} ${key.masked}`.toLowerCase().includes(query.trim().toLowerCase()),
  );
  const totalPages = Math.max(1, Math.ceil(filtered.length / 10));
  const page = Math.min(search.page ?? 1, totalPages);
  const rows = filtered.slice((page - 1) * 10, page * 10);
  const clearFilters = () =>
    void navigate({
      search: (prev) => ({ ...prev, q: undefined, status: "all", page: undefined }),
    });
  return (
    <>
      <title>API Keys · Mathew AI</title>
      <header className="page-header">
        <h1>API keys</h1>
        <div className="header-actions">
          <Link to="/usage" className="button button-secondary">
            <span>View usage</span>
            <ArrowUpRight />
          </Link>
          <button
            className="button button-primary"
            onClick={() => setCreating(true)}
            disabled={blocked}
          >
            <Plus />
            <span>Create new secret key</span>
          </button>
        </div>
      </header>
      <section className="keys-content" aria-label="API key management">
        <div className="filter-bar">
          <div className="search-field">
            <Search />
            <input
              aria-label="Search API keys"
              placeholder="Search keys…"
              value={query}
              onChange={(event) =>
                void navigate({
                  search: (prev) => ({
                    ...prev,
                    q: event.target.value || undefined,
                    page: undefined,
                  }),
                  replace: true,
                })
              }
            />
            {query && (
              <button
                className="icon-button"
                aria-label="Clear search"
                onClick={() =>
                  void navigate({
                    search: (prev) => ({ ...prev, q: undefined, page: undefined }),
                    replace: true,
                  })
                }
              >
                <X />
              </button>
            )}
          </div>
          <FilterSelect
            label="Filter by key status"
            value={status}
            options={[
              { value: "active", label: "Active keys" },
              { value: "revoked", label: "Revoked keys" },
              { value: "all", label: "All keys" },
            ]}
            onValueChange={(value) =>
              void navigate({
                search: (prev) => ({
                  ...prev,
                  status: value,
                  page: undefined,
                }),
              })
            }
          />
          <span className="result-count" role="status">
            {blocked ? "" : `${filtered.length} ${filtered.length === 1 ? "key" : "keys"}`}
          </span>
        </div>
        {blocked ? (
          <PageState
            state={search.preview}
            onRetry={() => void navigate({ search: (prev) => ({ ...prev, preview: undefined }) })}
          />
        ) : rows.length ? (
          <>
            <p id="key-scroll-hint" className="table-scroll-hint">
              <MoveHorizontal />
              Scroll horizontally for status, dates, and key actions.
            </p>
            <div
              className="table-scroll"
              role="region"
              aria-label="API keys table"
              aria-describedby="key-scroll-hint"
              tabIndex={0}
            >
              <table className="data-table keys-table">
                <thead>
                  <tr>
                    <th scope="col">Name</th>
                    <th scope="col">Secret key</th>
                    <th scope="col">Status</th>
                    <th scope="col">Created</th>
                    <th scope="col">Last used</th>
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((key) => (
                    <tr key={key.id}>
                      <td>
                        <span className="key-name" title={key.name}>
                          {key.name}
                        </span>
                      </td>
                      <td>
                        <code className="masked-key">{key.masked}</code>
                      </td>
                      <td>
                        <span className={`status-badge ${key.status}`}>
                          <span />
                          {key.status === "active" ? "Active" : "Revoked"}
                        </span>
                      </td>
                      <td className="muted nowrap">{formatDate(key.createdAt)}</td>
                      <td className="muted nowrap">
                        {key.lastUsed ? formatDate(key.lastUsed) : "Never"}
                      </td>
                      <td>
                        <div className="row-actions">
                          <Link
                            to="/usage"
                            search={{ key: key.id }}
                            className="icon-button"
                            aria-label={`View usage for ${key.name}`}
                            title="View usage"
                          >
                            <ArrowUpRight />
                          </Link>
                          {key.status === "active" && (
                            <button
                              className="icon-button destructive"
                              onClick={() => setRevoking(key)}
                              aria-label={`Revoke ${key.name}`}
                              title="Revoke key"
                            >
                              <Trash2 />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="table-footer">
              <span>
                Showing {(page - 1) * 10 + 1}–{Math.min(page * 10, filtered.length)} of{" "}
                {filtered.length} keys
              </span>
              <div className="pagination">
                <button
                  className="icon-button"
                  aria-label="Previous page"
                  disabled={page === 1}
                  onClick={() => void navigate({ search: (prev) => ({ ...prev, page: page - 1 }) })}
                >
                  <ChevronLeft />
                </button>
                <span>
                  Page {page} of {totalPages}
                </span>
                <button
                  className="icon-button"
                  aria-label="Next page"
                  disabled={page === totalPages}
                  onClick={() => void navigate({ search: (prev) => ({ ...prev, page: page + 1 }) })}
                >
                  <ChevronRight />
                </button>
              </div>
            </div>
            <p className="key-footnote">
              <LockKeyhole />
              Keep your secret keys private. Never share them or include them in browser code.
            </p>
          </>
        ) : (
          <div className="empty-state">
            <div className="state-icon">
              {query || visibleKeys.length ? <Search /> : <LockKeyhole />}
            </div>
            <h2>
              {query || visibleKeys.length
                ? "No keys match your filters"
                : "Create your first API key"}
            </h2>
            <p>
              {query || visibleKeys.length
                ? "Try a different name or include all key statuses."
                : "Create a key to get started with the Mathew AI API."}
            </p>
            {query || visibleKeys.length ? (
              <button className="button button-secondary" onClick={clearFilters}>
                Clear filters
              </button>
            ) : (
              <button className="button button-primary" onClick={() => setCreating(true)}>
                <Plus />
                Create new secret key
              </button>
            )}
          </div>
        )}
      </section>
      {creating && (
        <CreateKeyDialog
          startEmpty={search.preview === "empty"}
          onClose={() => setCreating(false)}
          onCreated={() => void navigate({ search: { status: "active" } })}
        />
      )}
      {revoking && <RevokeKeyDialog entry={revoking} onClose={() => setRevoking(null)} />}
    </>
  );
};
