import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
  meta,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 max-w-2xl">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
        {description ? (
          <p className="mt-1.5 text-xs leading-5 text-muted-foreground">{description}</p>
        ) : null}
        {meta ? <div className="mt-2">{meta}</div> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
