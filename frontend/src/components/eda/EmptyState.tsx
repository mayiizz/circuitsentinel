import type { ReactNode } from "react";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed border-line bg-panel/50 px-5 py-10">
      <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
      <p className="max-w-lg text-xs leading-5 text-muted-foreground">{description}</p>
      {action}
    </div>
  );
}
