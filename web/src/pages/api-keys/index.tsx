import {
  createApiKey,
  deleteApiKey,
  getListApiKeysQueryKey,
  revokeApiKey,
  useListApiKeys,
} from "@/api/generated/api-keys/api-keys";
import type { KeySummaryResponse } from "@/api/generated/model";
import { isApiError } from "@/api/mutator";
import { Dialog } from "@/components/ui/dialog";
import { FilterSelect } from "@/components/ui/filter-select";
import { PageState, previewSchema, type PreviewState } from "@/components/ui/page-state";
import { formatDate } from "@/utils/format";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import {
  ArrowUpRight,
  Ban,
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
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { z } from "zod";

export const keySearchSchema = z.object({
  q: z.string().catch("").optional(),
  status: z.enum(["active", "revoked", "all"]).catch("all").optional(),
  page: z.coerce.number().int().min(1).max(100000).catch(1).optional(),
  preview: previewSchema,
});

const SECRET_REVEAL_MS = 60_000;
const MASK = "••••••••••••••••";
// Mirrors the server's limit only to disable the button early; the server
// enforces it (409) whatever this says.
const MAX_ACTIVE_KEYS = 5;
const PAGE_SIZE = 10;

type KeyAction = "revoke" | "delete";

const getNameError = (value: string) => {
  const length = value.trim().length;
  return length < 1 || length > 100 ? "Enter a key name between 1 and 100 characters." : "";
};

const useRefreshKeys = () => {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: getListApiKeysQueryKey() });
};

export const CreateKeyDialog = ({ onClose }: { onClose: () => void }) => {
  const refreshKeys = useRefreshKeys();
  const [name, setName] = useState("");
  // The full key lives here, in component state, and nowhere else: never in a
  // store, the query cache, the URL, or browser storage.
  const [secret, setSecret] = useState("");
  const [keyPrefix, setKeyPrefix] = useState("");
  const [createdKeyId, setCreatedKeyId] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const mounted = useRef(false);
  const interrupted = useRef(false);
  const revealTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearRevealTimer = useCallback(() => {
    if (revealTimer.current !== null) {
      clearTimeout(revealTimer.current);
      revealTimer.current = null;
    }
  }, []);
  const clearSecret = useCallback(() => {
    clearRevealTimer();
    setSecret("");
    setKeyPrefix("");
    setCreatedKeyId("");
    setRevealed(false);
    setCopied(false);
    setError("");
  }, [clearRevealTimer]);
  useEffect(() => {
    mounted.current = true;
    interrupted.current = false;
    const maskSecret = () => {
      clearRevealTimer();
      setRevealed(false);
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") maskSecret();
    };
    const handlePageHide = () => {
      interrupted.current = true;
      clearSecret();
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("pagehide", handlePageHide);
    return () => {
      mounted.current = false;
      interrupted.current = true;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("pagehide", handlePageHide);
      clearRevealTimer();
    };
  }, [clearRevealTimer, clearSecret]);
  const closeAfterSaving = () => {
    clearSecret();
    onClose();
  };
  const reveal = () => {
    if (!secret) return;
    clearRevealTimer();
    setRevealed(true);
    revealTimer.current = setTimeout(() => {
      setRevealed(false);
      revealTimer.current = null;
    }, SECRET_REVEAL_MS);
  };
  const hide = () => {
    clearRevealTimer();
    setRevealed(false);
  };
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    const nameError = getNameError(name);
    if (nameError) {
      setError(nameError);
      return;
    }
    interrupted.current = false;
    setPending(true);
    setError("");
    try {
      const created = await createApiKey({ name: name.trim() });
      void refreshKeys();
      if (!mounted.current || interrupted.current) {
        // Nobody will ever see this secret, so the key must not survive.
        try {
          await deleteApiKey({ id: created.id });
          void refreshKeys();
        } catch {
          // The page is going away; there is no dialog state to recover.
        }
        return;
      }
      setSecret(created.key);
      setKeyPrefix(created.key_prefix);
      setCreatedKeyId(created.id);
      setRevealed(false);
      setCopied(false);
    } catch (error) {
      if (mounted.current && !interrupted.current) {
        setError(isApiError(error) ? error.message : "We couldn't create the key. Try again.");
      }
    } finally {
      if (mounted.current) setPending(false);
    }
  };
  const copy = async () => {
    if (!secret || pending) return;
    setCopied(false);
    try {
      await navigator.clipboard.writeText(secret);
      if (!mounted.current || interrupted.current) return;
      setCopied(true);
      setError("");
    } catch {
      if (mounted.current && !interrupted.current) {
        setError(
          "Clipboard access isn't available. Reveal the secret, then select it and copy it manually.",
        );
      }
    }
  };
  const discard = async () => {
    if (!createdKeyId || pending) return;
    setPending(true);
    setError("");
    try {
      await deleteApiKey({ id: createdKeyId });
      void refreshKeys();
      if (!mounted.current) return;
      clearSecret();
      onClose();
    } catch {
      if (mounted.current && !interrupted.current)
        setError("We couldn't discard this key. Try again.");
    } finally {
      if (mounted.current) setPending(false);
    }
  };
  const nameError = getNameError(name);
  return (
    <Dialog
      title={secret ? "Save your secret key" : "Create new secret key"}
      onClose={onClose}
      dismissible={false}
    >
      {secret ? (
        <div className="modal-body">
          <div className="success-heading">
            <Check />
            <span>Key created</span>
          </div>
          <p>
            Copy this key now. You won’t be able to see the full secret again after closing this
            dialog.
          </p>
          <label className="field-label" htmlFor="new-secret">
            Secret key
          </label>
          <div className="secret-field">
            <code
              id="new-secret"
              className={revealed ? "secret-value" : "secret-value masked"}
              aria-label={revealed ? "Secret key" : "Secret key is masked"}
              role="textbox"
              aria-readonly="true"
              tabIndex={revealed ? 0 : -1}
            >
              {revealed ? secret : `${keyPrefix}_${MASK}`}
            </code>
            <button
              type="button"
              className="button button-secondary secret-toggle"
              onClick={revealed ? hide : reveal}
              disabled={pending}
              autoFocus
            >
              {revealed ? "Hide" : "Reveal"}
            </button>
            <button
              type="button"
              className="icon-button"
              onClick={() => void copy()}
              aria-label={copied ? "Secret copied" : "Copy secret key"}
              disabled={pending}
            >
              {copied ? <Check /> : <Copy />}
            </button>
          </div>
          <p className="field-help">
            Clipboard contents and screenshots can expose secrets; store this key securely.
          </p>
          <p className="field-help">Reveal lasts 60 seconds and masks the key automatically.</p>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="modal-actions">
            <span className="copy-feedback" role="status">
              {copied ? "Copied to clipboard" : ""}
            </span>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void discard()}
              disabled={pending}
              aria-busy={pending}
            >
              Discard key
            </button>
            <button
              type="button"
              className="button button-primary"
              onClick={closeAfterSaving}
              disabled={pending}
            >
              I've saved it
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
            maxLength={100}
            autoComplete="off"
            aria-describedby="key-name-help"
            aria-invalid={Boolean(error && nameError)}
          />
          <p id="key-name-help" className="field-help">
            Up to 100 characters. You can create separate keys for each application.
          </p>
          <div className="inline-notice">
            <LockKeyhole />
            <span>The full key is shown once, right after it is created.</span>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="modal-actions">
            <button
              type="button"
              className="button button-secondary"
              onClick={onClose}
              disabled={pending}
            >
              Cancel
            </button>
            <button
              className="button button-primary"
              type="submit"
              disabled={Boolean(nameError) || pending}
              aria-busy={pending}
            >
              Create secret key
            </button>
          </div>
        </form>
      )}
    </Dialog>
  );
};

const ACTION_COPY: Record<
  KeyAction,
  { verb: string; done: string; body: string; pending: string }
> = {
  revoke: {
    verb: "Revoke",
    done: "revoked",
    body: "Applications using this key will stop being able to call the API. This cannot be undone.",
    pending: "The key is not revoked yet. Try again.",
  },
  delete: {
    verb: "Delete",
    done: "deleted",
    body: "The key is removed from this list. Its past usage stays in your usage report. This cannot be undone.",
    pending: "The key is not deleted yet. Try again.",
  },
};

export const KeyActionDialog = ({
  action,
  entry,
  onClose,
}: {
  action: KeyAction;
  entry: KeySummaryResponse;
  onClose: () => void;
}) => {
  const refreshKeys = useRefreshKeys();
  const copy = ACTION_COPY[action];
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const run = async () => {
    if (pending) return;
    setPending(true);
    setError("");
    try {
      await (action === "revoke" ? revokeApiKey : deleteApiKey)({ id: entry.id });
      void refreshKeys();
      if (!mounted.current) return;
      toast.success(`“${entry.name}” ${copy.done}`);
      onClose();
    } catch (error) {
      void refreshKeys();
      if (!mounted.current) return;
      // A 500 here means the status changed but the auth cache may still hold
      // the key for up to a minute. Never report that as success.
      setError(
        isApiError(error, "identity_api_key_revocation_pending")
          ? copy.pending
          : isApiError(error, "identity_api_key_not_found")
            ? "This key no longer exists. Close this dialog and check the list."
            : `We couldn't ${action} this key. Try again.`,
      );
    } finally {
      if (mounted.current) setPending(false);
    }
  };
  return (
    <Dialog title={`${copy.verb} “${entry.name}”?`} onClose={onClose}>
      <div className="modal-body">
        <div className="revoke-key">
          <KeyRound />
          <div>
            <strong>{entry.name}</strong>
            <code>{entry.key_prefix}</code>
          </div>
        </div>
        <p>{copy.body}</p>
        {action === "revoke" && (
          <div className="inline-notice">
            <ShieldAlert />
            <span>Requests already in flight may complete for up to a minute.</span>
          </div>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={onClose}
            disabled={pending}
          >
            Keep key
          </button>
          <button
            type="button"
            className="button button-danger"
            onClick={() => void run()}
            disabled={pending}
            aria-busy={pending}
          >
            {copy.verb} “{entry.name}”
          </button>
        </div>
      </div>
    </Dialog>
  );
};

export const ApiKeysPage = () => {
  const keysQuery = useListApiKeys();
  const search = useSearch({ from: "/api-keys" });
  const navigate = useNavigate({ from: "/api-keys" });
  const [creating, setCreating] = useState(false);
  const [acting, setActing] = useState<{ action: KeyAction; entry: KeySummaryResponse } | null>(
    null,
  );
  const query = search.q ?? "";
  const status = search.status ?? "all";
  const state: PreviewState = ["error", "loading", "session"].includes(search.preview ?? "")
    ? search.preview
    : keysQuery.isPending
      ? "loading"
      : keysQuery.isError
        ? isApiError(keysQuery.error) && keysQuery.error.status === 401
          ? "session"
          : "error"
        : "normal";
  const blocked = state !== "normal";
  const keys = keysQuery.data ?? [];
  const visibleKeys = search.preview === "empty" ? [] : keys;
  const activeCount = keys.filter((key) => key.status === "active").length;
  const atLimit = activeCount >= MAX_ACTIVE_KEYS;
  const createDisabled = blocked || atLimit;
  const filtered = visibleKeys.filter(
    (key) =>
      (status === "all" || key.status === status) &&
      `${key.name} ${key.key_prefix}`.toLowerCase().includes(query.trim().toLowerCase()),
  );
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const page = Math.min(search.page ?? 1, totalPages);
  const rows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
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
            disabled={createDisabled}
            aria-describedby={atLimit ? "key-limit-help" : undefined}
            title={atLimit ? "Revoke a key before creating another" : undefined}
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
          <span className="key-capacity" title="Active key capacity">
            {activeCount} / {MAX_ACTIVE_KEYS} keys
          </span>
          {atLimit && (
            <span id="key-limit-help" className="key-limit-help">
              Revoke a key before creating another.
            </span>
          )}
        </div>
        {blocked ? (
          <PageState
            state={state}
            onRetry={() => {
              void navigate({ search: (prev) => ({ ...prev, preview: undefined }) });
              void keysQuery.refetch();
            }}
          />
        ) : rows.length ? (
          <>
            <p id="key-scroll-hint" className="table-scroll-hint">
              <MoveHorizontal />
              Scroll horizontally for status and key actions.
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
                    <th scope="col">Key</th>
                    <th scope="col">Status</th>
                    <th scope="col">Last used</th>
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((key) => (
                    <tr
                      key={key.id}
                      className={key.status === "revoked" ? "revoked-row" : undefined}
                    >
                      <td>
                        <span className="key-name" title={key.name}>
                          {key.name}
                        </span>
                      </td>
                      <td>
                        <code className="key-prefix">{key.key_prefix}</code>
                      </td>
                      <td>
                        <span className={`status-badge ${key.status}`}>
                          <span />
                          {key.status === "active" ? "Active" : "Revoked"}
                        </span>
                      </td>
                      <td className="muted nowrap">
                        {key.never_used || !key.last_used_at ? (
                          <span className="never-used-cell">
                            <span className="never-used-badge">Never used</span>
                          </span>
                        ) : (
                          formatDate(key.last_used_at)
                        )}
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
                          {key.status === "active" ? (
                            <button
                              className="icon-button destructive"
                              onClick={() => setActing({ action: "revoke", entry: key })}
                              aria-label={`Revoke ${key.name}`}
                              title="Revoke key"
                            >
                              <Ban />
                            </button>
                          ) : (
                            <button
                              className="icon-button destructive"
                              onClick={() => setActing({ action: "delete", entry: key })}
                              aria-label={`Delete ${key.name}`}
                              title="Delete key"
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
                Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)}{" "}
                of {filtered.length} keys
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
              <button
                className="button button-primary"
                onClick={() => setCreating(true)}
                disabled={atLimit}
                aria-describedby={atLimit ? "key-limit-help" : undefined}
              >
                <Plus />
                Create new secret key
              </button>
            )}
            {atLimit && !query && !visibleKeys.length && (
              <p className="empty-state-help">Revoke a key before creating another.</p>
            )}
          </div>
        )}
      </section>
      {creating && <CreateKeyDialog onClose={() => setCreating(false)} />}
      {acting && (
        <KeyActionDialog
          action={acting.action}
          entry={acting.entry}
          onClose={() => setActing(null)}
        />
      )}
    </>
  );
};
