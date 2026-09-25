import { useListApiKeys } from "@/api/generated/api-keys/api-keys";
import { useGetUsage } from "@/api/generated/dashboard/dashboard";
import type { DailyUsageResponse } from "@/api/generated/model";
import { isApiError } from "@/api/mutator";
import { FilterSelect } from "@/components/ui/filter-select";
import { PageState, previewSchema, type PreviewState } from "@/components/ui/page-state";
import { formatDate, formatNumber } from "@/utils/format";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { ChartNoAxesColumnIncreasing, ChevronDown, Download, Info, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";

export const usageSearchSchema = z.object({
  days: z.enum(["7", "30"]).catch("7").optional(),
  key: z.string().catch("all").optional(),
  metric: z.enum(["requests", "tokens"]).catch("requests").optional(),
  preview: previewSchema,
});

const compact = (value: number) =>
  new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);

const UsageChart = ({
  series,
  metric,
}: {
  series: DailyUsageResponse[];
  metric: "requests" | "tokens";
}) => {
  const highest = Math.max(...series.map((day) => day[metric]), 1);
  const top = Math.ceil(highest / 4) * 4;
  const title = metric === "requests" ? "requests" : "tokens";
  return (
    <div className="usage-chart">
      <div className="chart-plot">
        <div className="chart-grid" aria-hidden="true">
          {[1, 0.75, 0.5, 0.25, 0].map((fraction) => (
            <div key={fraction}>
              <span>{compact(top * fraction)}</span>
            </div>
          ))}
        </div>
        <div
          className="chart-bars"
          role="list"
          aria-label={`Daily ${title}. Exact values are also available in the daily data table.`}
        >
          {series.map((day) => (
            <div className="chart-bar-slot" key={day.date} role="listitem">
              <div
                className="chart-bar"
                style={{ height: `${(day[metric] / top) * 100}%` }}
                tabIndex={0}
                aria-label={`${formatDate(day.date)}: ${formatNumber(day[metric])} ${title}`}
              >
                <span className="chart-tooltip">
                  {formatDate(day.date)}
                  <strong>
                    {formatNumber(day[metric])} {title}
                  </strong>
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="chart-dates">
        <span>{formatDate(series[0].date)}</span>
        <span>{formatDate(series[Math.floor(series.length / 2)].date)}</span>
        <span>{formatDate(series[series.length - 1].date)}</span>
      </div>
    </div>
  );
};

const SOURCE_LABELS = { api: "API keys", web: "Mathew AI app" } as const;

export const UsagePage = () => {
  const search = useSearch({ from: "/usage" });
  const navigate = useNavigate({ from: "/usage" });
  const days = search.days ?? "7";
  const keyId = search.key ?? "all";
  const metric = search.metric ?? "requests";
  // The API resolves "last N days" against Asia/Bangkok's today; the browser
  // never works out dates itself.
  const usageQuery = useGetUsage({
    days: Number(days),
    key_id: keyId === "all" ? undefined : keyId,
  });
  const keysQuery = useListApiKeys();
  const keys = keysQuery.data ?? [];
  const report = usageQuery.data;
  const state: PreviewState = ["loading", "error", "session"].includes(search.preview ?? "")
    ? search.preview
    : usageQuery.isPending
      ? "loading"
      : usageQuery.isError
        ? isApiError(usageQuery.error) && usageQuery.error.status === 401
          ? "session"
          : "error"
        : "normal";
  const blocked = state !== "normal" || !report;
  const empty = search.preview === "empty" || !report || report.totals.requests === 0;
  const download = () => {
    if (!report) return;
    const rows = [
      "Date,Requests,Tokens",
      ...report.daily.map((day) => `${day.date},${day.requests},${day.tokens}`),
    ];
    const url = URL.createObjectURL(
      new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8;" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `mathew-ai-usage-${report.from}-to-${report.to}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast.success("Usage exported");
  };
  return (
    <>
      <title>Usage · Mathew AI</title>
      <header className="page-header usage-header">
        <h1>Usage</h1>
        <div className="header-actions">
          <FilterSelect
            className="key-filter"
            label="Filter usage by API key"
            value={keyId}
            onValueChange={(value) =>
              void navigate({ search: (prev) => ({ ...prev, key: value }) })
            }
            options={[
              { value: "all", label: "All API keys" },
              ...(!keys.some((key) => key.id === keyId) && keyId !== "all"
                ? [{ value: keyId, label: "Unknown key" }]
                : []),
              ...keys.map((key) => ({
                value: key.id,
                label: `${key.name}${key.status === "revoked" ? " (revoked)" : ""}`,
              })),
            ]}
          />
          <FilterSelect
            className="range-filter"
            label="Usage date range"
            value={days}
            onValueChange={(value) =>
              void navigate({
                search: (prev) => ({ ...prev, days: value }),
              })
            }
            options={[
              { value: "7", label: "Last 7 days" },
              { value: "30", label: "Last 30 days" },
            ]}
          />
          <button
            className="icon-button"
            aria-label="Refresh usage"
            title="Refresh usage"
            onClick={() => {
              void navigate({ search: (prev) => ({ ...prev, preview: undefined }) });
              void usageQuery.refetch();
            }}
          >
            <RefreshCw />
          </button>
          <button
            className="icon-button"
            aria-label="Export usage as CSV"
            title="Export CSV"
            onClick={download}
            disabled={blocked}
          >
            <Download />
          </button>
        </div>
      </header>
      {report?.clamped && (
        <div className="usage-notice">
          <Info />
          <span>Usage is kept for 60 days. The range shown starts at the oldest data kept.</span>
        </div>
      )}
      {blocked ? (
        <PageState
          state={state === "normal" ? "loading" : state}
          onRetry={() => {
            void navigate({ search: (prev) => ({ ...prev, preview: undefined }) });
            void usageQuery.refetch();
          }}
        />
      ) : (
        <>
          <section className="usage-overview" aria-label="Usage overview">
            <div className="chart-panel">
              <div className="chart-heading">
                <div className="metric-tabs" aria-label="Chart metric">
                  {(["requests", "tokens"] as const).map((value) => (
                    <button
                      key={value}
                      aria-pressed={metric === value}
                      onClick={() =>
                        void navigate({ search: (prev) => ({ ...prev, metric: value }) })
                      }
                    >
                      {value === "requests" ? "Requests" : "Tokens"}
                    </button>
                  ))}
                </div>
                <span className="group-label">
                  Daily totals<span>1d</span>
                </span>
              </div>
              <div className="chart-total">
                {formatNumber(empty ? 0 : report.totals[metric])}
                <span>{metric === "requests" ? "total requests" : "total tokens"}</span>
              </div>
              {empty ? (
                <div className="empty-state chart-empty">
                  <div className="state-icon">
                    <ChartNoAxesColumnIncreasing />
                  </div>
                  <h2>No usage data</h2>
                  <p>There’s no activity for this key in the selected period.</p>
                  <button
                    className="button button-secondary"
                    onClick={() => void navigate({ search: { days, metric } })}
                  >
                    Reset filters
                  </button>
                </div>
              ) : (
                <UsageChart series={report.daily} metric={metric} />
              )}
            </div>
            <aside className="usage-summary" aria-label="Usage summary">
              <div className="summary-heading">Period summary</div>
              <div className="summary-stat">
                <span>Tokens remaining</span>
                <strong>{formatNumber(report.quota.remaining)}</strong>
                <span className="stat-detail">
                  {formatNumber(report.quota.used)} of {formatNumber(report.quota.limit)} used,
                  shared between API keys and the Mathew AI app
                </span>
              </div>
              {report.by_source.map((row) => (
                <div className="summary-stat" key={row.source}>
                  <span>{SOURCE_LABELS[row.source]}</span>
                  <strong>{formatNumber(row.tokens)} tokens</strong>
                  <span className="stat-detail">{formatNumber(row.requests)} requests</span>
                </div>
              ))}
              <div className="summary-period">
                <span>Reporting period</span>
                <p>
                  {formatDate(report.from)}
                  <br />
                  {" to "}
                  {formatDate(report.to)}
                </p>
                <span>Dates shown in {report.timezone}</span>
              </div>
            </aside>
          </section>
          <section className="usage-breakdown" aria-labelledby="breakdown-title">
            <div className="section-heading">
              <h2 id="breakdown-title">Usage by API key</h2>
              <span>Selected period</span>
            </div>
            {empty ? (
              <p className="breakdown-empty">No API key activity in this period.</p>
            ) : (
              <div
                className="table-scroll"
                role="region"
                aria-label="Usage by API key table"
                tabIndex={0}
              >
                <table className="data-table usage-table">
                  <thead>
                    <tr>
                      <th scope="col">API key</th>
                      <th scope="col">Status</th>
                      <th scope="col" className="number-cell">
                        Requests
                      </th>
                      <th scope="col" className="number-cell">
                        Tokens
                      </th>
                      <th scope="col" className="share-cell">
                        Request share
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.by_key.map((row) => (
                      <tr key={row.key_id}>
                        <td>
                          <button
                            className="key-link"
                            onClick={() =>
                              void navigate({ search: (prev) => ({ ...prev, key: row.key_id }) })
                            }
                          >
                            {row.name}
                          </button>
                        </td>
                        <td>
                          <span
                            className={`status-badge ${row.status === "active" ? "active" : "revoked"}`}
                          >
                            <span />
                            {row.status === "active"
                              ? "Active"
                              : row.status === "revoked"
                                ? "Revoked"
                                : "Deleted"}
                          </span>
                        </td>
                        <td className="number-cell">{formatNumber(row.requests)}</td>
                        <td className="number-cell">{formatNumber(row.tokens)}</td>
                        <td className="share-cell">
                          <div className="share-value">
                            <div className="share-track" aria-hidden="true">
                              <span style={{ width: `${row.request_share_pct}%` }} />
                            </div>
                            <span>{row.request_share_pct.toFixed(1)}%</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          {!empty && (
            <details className="daily-data">
              <summary>
                Daily usage data
                <ChevronDown />
              </summary>
              <div
                className="table-scroll"
                role="region"
                aria-label="Daily usage data"
                tabIndex={0}
              >
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">Date</th>
                      <th scope="col" className="number-cell">
                        Requests
                      </th>
                      <th scope="col" className="number-cell">
                        Tokens
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.daily.map((day) => (
                      <tr key={day.date}>
                        <td>{formatDate(day.date)}</td>
                        <td className="number-cell">{formatNumber(day.requests)}</td>
                        <td className="number-cell">{formatNumber(day.tokens)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </>
      )}
    </>
  );
};
