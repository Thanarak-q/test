import type { FC } from "react";
import { useHealth } from "./hooks/useHealth";

export const HomePage: FC = () => {
  const { data, isPending, isError } = useHealth();

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-2 p-8">
      <h1 className="text-2xl font-semibold">matthew</h1>
      <p className="text-sm text-muted-foreground">
        API: {isPending ? "…" : isError ? "unreachable" : data?.status}
      </p>
    </main>
  );
};
