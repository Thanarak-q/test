import {
  disableModel,
  enableModel,
  getListModelsQueryKey,
  useListModels,
} from "@/api/generated/admin/admin";
import type { AdminModelResponse } from "@/api/generated/model";
import { isApiError } from "@/api/mutator";
import { Dialog } from "@/components/ui/dialog";
import { PageState, type PreviewState } from "@/components/ui/page-state";
import { formatNumber } from "@/utils/format";
import { useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

// Not in the sidebar: the web cannot tell who is an admin until the main
// application's session is wired in (docs/HANDOFF.md §1.1). The API decides —
// a non-admin gets 403 here, and manage_model checks the role again.

type Action = "enable" | "disable";

export const ModelActionDialog = ({
  action,
  model,
  onClose,
}: {
  action: Action;
  model: AdminModelResponse;
  onClose: () => void;
}) => {
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const verb = action === "enable" ? "Enable" : "Disable";
  const run = async () => {
    if (pending) return;
    setPending(true);
    setError("");
    try {
      await (action === "enable" ? enableModel : disableModel)({ id: model.id });
      void queryClient.invalidateQueries({ queryKey: getListModelsQueryKey() });
      if (!mounted.current) return;
      toast.success(`“${model.name}” ${action}d`);
      onClose();
    } catch (error) {
      void queryClient.invalidateQueries({ queryKey: getListModelsQueryKey() });
      if (!mounted.current) return;
      // A 500 here means the change is saved but the model cache was not
      // cleared: the old status can hold for up to five minutes. Never
      // report that as done.
      setError(
        isApiError(error, "llm_model_change_pending")
          ? "The change is saved but not in effect yet. Try again."
          : isApiError(error, "identity_forbidden")
            ? "Only admins can change models."
            : `We couldn't ${action} this model. Try again.`,
      );
    } finally {
      if (mounted.current) setPending(false);
    }
  };
  return (
    <Dialog title={`${verb} “${model.name}”?`} onClose={onClose}>
      <div className="modal-body">
        <p>
          {action === "disable"
            ? "Every API key stops being able to use this model. Requests that name it get 403 until it is enabled again."
            : "Every API key can use this model again."}
        </p>
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
            type="button"
            className={action === "disable" ? "button button-danger" : "button button-primary"}
            onClick={() => void run()}
            disabled={pending}
            aria-busy={pending}
          >
            {verb} “{model.name}”
          </button>
        </div>
      </div>
    </Dialog>
  );
};

export const AdminModelsPage = () => {
  const modelsQuery = useListModels();
  const [acting, setActing] = useState<{ action: Action; model: AdminModelResponse } | null>(null);
  const forbidden = isApiError(modelsQuery.error) && modelsQuery.error.status === 403;
  const state: PreviewState = modelsQuery.isPending
    ? "loading"
    : modelsQuery.isError && !forbidden
      ? isApiError(modelsQuery.error) && modelsQuery.error.status === 401
        ? "session"
        : "error"
      : "normal";
  return (
    <>
      <title>Models · Mathew API</title>
      <header className="page-header">
        <h1>Models</h1>
      </header>
      <section className="keys-content" aria-label="Model whitelist">
        {forbidden ? (
          <div className="empty-state" role="alert">
            <div className="state-icon">
              <ShieldAlert />
            </div>
            <h2>Admins only</h2>
            <p>Only admins can see and change which models API keys may use.</p>
          </div>
        ) : state !== "normal" ? (
          <PageState state={state} onRetry={() => void modelsQuery.refetch()} />
        ) : (
          <div className="table-scroll" role="region" aria-label="Models table" tabIndex={0}>
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  <th scope="col" className="number-cell">
                    Context window
                  </th>
                  <th scope="col" className="number-cell">
                    Max output
                  </th>
                  <th scope="col">Status</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {(modelsQuery.data ?? []).map((model) => (
                  <tr
                    key={model.id}
                    className={model.status === "disabled" ? "revoked-row" : undefined}
                  >
                    <td>
                      <code className="key-prefix">{model.name}</code>
                    </td>
                    <td className="number-cell">{formatNumber(model.context_window)}</td>
                    <td className="number-cell">{formatNumber(model.max_output_tokens)}</td>
                    <td>
                      <span
                        className={`status-badge ${model.status === "enabled" ? "active" : "revoked"}`}
                      >
                        <span />
                        {model.status === "enabled" ? "Enabled" : "Disabled"}
                      </span>
                    </td>
                    <td>
                      <div className="row-actions">
                        <button
                          className={
                            model.status === "enabled"
                              ? "button button-secondary"
                              : "button button-primary"
                          }
                          onClick={() =>
                            setActing({
                              action: model.status === "enabled" ? "disable" : "enable",
                              model,
                            })
                          }
                        >
                          {model.status === "enabled" ? "Disable" : "Enable"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {acting && (
        <ModelActionDialog
          action={acting.action}
          model={acting.model}
          onClose={() => setActing(null)}
        />
      )}
    </>
  );
};
