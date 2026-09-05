import { FilterSelect } from "@/components/ui/filter-select";
import { PageState, previewSchema } from "@/components/ui/page-state";
import { $demoHasUsage, $demoKeys, formatDate, formatNumber, getDemoUsage } from "@/stores/demo";
import { useStore } from "@nanostores/react";
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
  series: ReturnType<typeof getDemoUsage>["series"];
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

export const UsagePage = () => {
  const keys = useStore($demoKeys);
  const hasUsage = useStore($demoHasUsage);
  const search = useSearch({ from: "/usage" });
  const navigate = useNavigate({ from: "/usage" });
  const days = search.days ?? "7";
  const keyId = search.key ?? "all";
  const metric = search.metric ?? "requests";
  const report = getDemoUsage(Number(days), keyId);
  const blocked = ["loading", "error", "session"].includes(search.preview ?? "");
  const empty = search.preview === "empty" || !hasUsage || report.requests === 0;
  const download = () => {
    const rows = [
      "Date,Requests,Tokens",
      ...report.series.map(
        (day) => `${day.date.slice(0, 10)},${empty ? 0 : day.requests},${empty ? 0 : day.tokens}`,
      ),
    ];
    const url = URL.createObjectURL(
      new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8;" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "mathew-ai-demo-usage.csv";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast.success("Demo usage exported");
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
              { value: "7", label: "Last 7 demo days" },
              { value: "30", label: "Last 30 demo days" },
            ]}
          />
          <button
            className="icon-button"
            aria-label="Refresh usage"
            title="Refresh usage"
            onClick={() => {
              void navigate({ search: (prev) => ({ ...prev, preview: undefined }) });
              toast.success("Demo report refreshed. Sample data is fixed.");
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
      <div className="usage-notice">
        <Info />
        <span>
          Illustrative usage through September 5, 2026. This is sample data, not live API activity.
        </span>
      </div>
      {blocked ? (
        <PageState
          state={search.preview}
          onRetry={() => void navigate({ search: (prev) => ({ ...prev, preview: undefined }) })}
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
                {formatNumber(empty ? 0 : report[metric])}
                <span>{metric === "requests" ? "total requests" : "total tokens"}</span>
              </div>
              {empty ? (
                <div className="empty-state chart-empty">
                  <div className="state-icon">
                    <ChartNoAxesColumnIncreasing />
                  </div>
                  <h2>No usage data</h2>
                  <p>There’s no activity for this key in the selected demo period.</p>
                  <button
                    className="button button-secondary"
                    onClick={() => void navigate({ search: { days, metric } })}
                  >
                    Reset filters
                  </button>
                </div>
              ) : (
                <UsageChart series={report.series} metric={metric} />
              )}
            </div>
            <aside className="usage-summary" aria-label="Usage summary">
              <div className="summary-heading">
                Period summary<span className="demo-badge">Demo</span>
              </div>
              <div className="summary-stat">
                <span>Total requests</span>
                <strong>{formatNumber(empty ? 0 : report.requests)}</strong>
                <span className="stat-detail">Across the selected API keys</span>
              </div>
              <div className="summary-stat">
                <span>Total tokens</span>
                <strong>{formatNumber(empty ? 0 : report.tokens)}</strong>
                <span className="stat-detail">Illustrative token consumption</span>
              </div>
              <div className="summary-period">
                <span>Reporting period</span>
                <p>
                  {formatDate(report.series[0].date)}
                  <br />
                  {" to "}
                  {formatDate(report.series[report.series.length - 1].date)}
                </p>
                <span>Dates shown in Asia/Bangkok</span>
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
                    {report.breakdown.map((row) => {
                      const key = keys.find((entry) => entry.id === row.id);
                      const share = (row.requests / report.requests) * 100;
                      return (
                        <tr key={row.id}>
                          <td>
                            <button
                              className="key-link"
                              onClick={() =>
                                void navigate({ search: (prev) => ({ ...prev, key: row.id }) })
                              }
                            >
                              {key?.name ?? "Previous deployment"}
                            </button>
                          </td>
                          <td>
                            <span className={`status-badge ${key?.status ?? "revoked"}`}>
                              <span />
                              {key?.status === "active" ? "Active" : "Revoked"}
                            </span>
                          </td>
                          <td className="number-cell">{formatNumber(row.requests)}</td>
                          <td className="number-cell">{formatNumber(row.tokens)}</td>
                          <td className="share-cell">
                            <div className="share-value">
                              <div className="share-track" aria-hidden="true">
                                <span style={{ width: `${share}%` }} />
                              </div>
                              <span>{share.toFixed(1)}%</span>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
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
                    {report.series.map((day) => (
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
