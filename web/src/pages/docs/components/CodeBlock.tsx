import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ToBeConfirmed } from "./Badge";

const COPIED_MS = 2_000;

export const CodeBlock = ({
  code,
  label,
  unconfirmed = false,
}: {
  code: string;
  label: string;
  unconfirmed?: boolean;
}) => {
  const [status, setStatus] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setStatus("Copied to clipboard");
    } catch {
      setStatus("Copy failed. Select the code and copy it manually.");
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setStatus(""), COPIED_MS);
  };
  return (
    <figure className="docs-code">
      <figcaption>
        <span>{label}</span>
        {unconfirmed && <ToBeConfirmed />}
        <button
          type="button"
          className="icon-button"
          aria-label={`Copy ${label} code`}
          onClick={() => void copy()}
        >
          {status === "Copied to clipboard" ? <Check /> : <Copy />}
        </button>
        <span className="sr-only" role="status" aria-live="polite">
          {status}
        </span>
      </figcaption>
      <pre>
        <code>{code}</code>
      </pre>
    </figure>
  );
};
