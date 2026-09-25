import { useListPublicModels } from "@/api/generated/public/public";
import { useSearch } from "@tanstack/react-router";

const copy = {
  en: {
    label: "Models",
    model: "Model",
    context: "Context window (tokens)",
    output: "Max output (tokens)",
    loading: "Loading models…",
    error: "Couldn’t load the model list. Refresh to try again.",
  },
  th: {
    label: "โมเดล",
    model: "โมเดล",
    context: "Context window (โทเคน)",
    output: "Output สูงสุด (โทเคน)",
    loading: "กำลังโหลดรายการโมเดล…",
    error: "โหลดรายการโมเดลไม่สำเร็จ ลองรีเฟรชหน้าอีกครั้ง",
  },
};

const number = new Intl.NumberFormat("en-US");

// The enabled models, live from GET /v1/public/models: turning a model on or
// off in /admin/models shows here without a docs change.
export const ModelsTable = () => {
  const locale = useSearch({ from: "/docs" }).locale ?? "en";
  const text = copy[locale];
  const { data, isPending, isError } = useListPublicModels();

  if (isPending) return <p className="muted">{text.loading}</p>;
  if (isError) return <p className="muted">{text.error}</p>;
  return (
    <div className="table-scroll" role="region" tabIndex={0} aria-label={text.label}>
      <table className="data-table docs-table">
        <thead>
          <tr>
            <th scope="col">{text.model}</th>
            <th scope="col">{text.context}</th>
            <th scope="col">{text.output}</th>
          </tr>
        </thead>
        <tbody>
          {data.map((model) => (
            <tr key={model.name}>
              <td>
                <code>{model.name}</code>
              </td>
              <td>{number.format(model.context_window)}</td>
              <td>{number.format(model.max_output_tokens)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
