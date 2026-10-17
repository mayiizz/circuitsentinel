import { StatusBadge } from "@/components/eda/StatusBadge";

export type GovernanceEvent = {
  id: string;
  action: string;
  decision: string;
  message: string;
  timestamp: string;
};

export function GovernanceEventRow({ event }: { event: GovernanceEvent }) {
  const tone =
    event.decision === "allowed"
      ? "good"
      : event.decision === "blocked"
        ? "danger"
        : event.decision === "error"
          ? "caution"
          : "neutral";

  return (
    <article className="rounded-lg border border-line bg-panel-raised px-3 py-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-[11px]">{event.action}</span>
        <StatusBadge tone={tone} label={event.decision} />
      </div>
      <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{event.message}</p>
      <p className="mt-1 font-mono text-[10px] text-muted-foreground">{event.timestamp}</p>
    </article>
  );
}
