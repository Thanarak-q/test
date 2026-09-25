import type { Sample } from "@/content/docs/samples";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { CodeBlock } from "./CodeBlock";

export const LANGUAGES = ["curl", "python", "javascript"] as const;
export type Language = (typeof LANGUAGES)[number];

const LABELS: Record<Language, string> = {
  curl: "curl",
  python: "Python",
  javascript: "JavaScript",
};

// The chosen language lives in the URL (?lang=), per AGENTS.md: shareable,
// and nothing is written to browser storage.
export const CodeTabs = ({ sample }: { sample: Sample }) => {
  const search = useSearch({ from: "/docs" });
  const navigate = useNavigate({ from: "/docs" });
  const available = LANGUAGES.filter((language) => sample.code[language] !== undefined);
  const selected =
    search.lang && available.includes(search.lang) ? search.lang : (available[0] ?? "curl");
  return (
    <div className="docs-tabs">
      <div className="metric-tabs" role="group" aria-label="Example language">
        {available.map((language) => (
          <button
            key={language}
            type="button"
            aria-pressed={selected === language}
            onClick={() =>
              void navigate({
                // Stay on the current page. Without `to`, navigating from
                // "/docs" goes to /docs itself, which redirects to the quickstart.
                to: "/docs/$",
                params: (prev) => prev,
                search: (prev) => ({ ...prev, lang: language }),
                replace: true,
                resetScroll: false,
              })
            }
          >
            {LABELS[language]}
          </button>
        ))}
      </div>
      <CodeBlock code={sample.code[selected] ?? ""} label={LABELS[selected]} />
    </div>
  );
};
