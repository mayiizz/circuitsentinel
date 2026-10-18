type Tone = "good" | "caution" | "danger" | "info" | "neutral";

const TONE: Record<Tone, string> = {
  good: "border-good/40 bg-good/10 text-good",
  caution: "border-caution/40 bg-caution/10 text-caution",
  danger: "border-danger/40 bg-danger/10 text-danger",
  info: "border-info/40 bg-info/10 text-info",
  neutral: "border-line bg-workspace text-muted-foreground",
};

export function StatusBadge({ label, tone = "neutral" }: { label: string; tone?: Tone }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide transition-colors ${TONE[tone]}`}
    >
      {label}
    </span>
  );
}
