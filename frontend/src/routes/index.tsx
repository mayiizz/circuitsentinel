import { ArrowRight, CircuitBoard, FileText, Network, Shield } from "lucide-react";
import { Link, createFileRoute } from "@tanstack/react-router";

import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "CircuitSentinel — AI Circuit Engineering Intelligence" },
      {
        name: "description",
        content:
          "Schematic analysis, datasheet intelligence, evidence tracing, and least-privilege governed AI actions.",
      },
    ],
  }),
  component: HomePage,
});

const FEATURES = [
  {
    title: "Schematic Analysis",
    body: "Parse KiCad schematics, run ERC when available, and inspect structure without inventing connectivity.",
    icon: CircuitBoard,
    to: "/schematic" as const,
  },
  {
    title: "Datasheet Intelligence",
    body: "Ingest PDF text, confirm explicit component links, and run conservative recommended-supply checks.",
    icon: FileText,
    to: "/datasheets" as const,
  },
  {
    title: "Evidence Graph",
    body: "Explore provenance-tagged relationships between components, findings, nets, and datasheets.",
    icon: Network,
    to: "/evidence" as const,
  },
  {
    title: "Governed AI Agents",
    body: "Least-privilege crew roles and fail-closed sandbox actions — never fabricated policy outcomes.",
    icon: Shield,
    to: "/governance" as const,
  },
];

function HomePage() {
  return (
    <div className="flex-1 overflow-auto">
      <section className="relative overflow-hidden border-b border-line px-6 py-16 md:px-10 md:py-20">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_#168BFF28,_transparent_55%),radial-gradient(ellipse_at_bottom_left,_#16C8F414,_transparent_50%)]" />
        <div className="pointer-events-none absolute inset-0 cad-grid opacity-30" />
        <div className="relative mx-auto grid max-w-6xl gap-10 lg:grid-cols-[1.15fr_0.85fr] lg:items-center">
          <div className="cs-fade-up">
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-brand">
              CircuitSentinel
            </p>
            <h1 className="mt-4 max-w-xl text-4xl font-semibold tracking-tight text-foreground md:text-5xl lg:text-[3.35rem] lg:leading-[1.05]">
              Investigate circuits with{" "}
              <span className="text-brand">evidence, not invention</span>
            </h1>
            <p className="mt-5 max-w-xl text-sm leading-6 text-muted-foreground md:text-base">
              Analyze schematics, ground datasheet facts, trace provenance, and exercise
              least-privilege agents — without inventing voltages, auto-matching parts, or faking
              authorization decisions.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild size="lg">
                <Link to="/schematic">
                  Start Analyzing <ArrowRight size={16} />
                </Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <Link to="/projects">Open Projects</Link>
              </Button>
              <Button asChild size="lg" variant="ghost">
                <Link to="/assistant">Ask Assistant</Link>
              </Button>
            </div>
          </div>

          <div className="cs-fade-up cs-fade-up-delay-1 relative mx-auto aspect-square w-full max-w-md">
            <div className="absolute inset-0 rounded-2xl bg-[radial-gradient(circle_at_center,_#16C8F422,_transparent_65%)]" />
            <div className="relative flex h-full flex-col overflow-hidden rounded-2xl border border-line bg-panel/80 shadow-[0_0_80px_#16C8F422]">
              <div className="relative min-h-0 flex-1">
                <img
                  src="/hero-schematic.jpg"
                  alt="Op-amp comparator schematic under investigation"
                  className="absolute inset-0 size-full object-cover object-center"
                />
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-panel via-panel/20 to-transparent" />
              </div>
              <div className="relative border-t border-line bg-panel/95 px-5 py-4 backdrop-blur-sm">
                <p className="text-sm font-medium text-foreground">Read-only investigation</p>
                <p className="mt-1 font-mono text-[11px] tracking-wide text-muted-foreground">
                  Schematic · ERC · Evidence · Governance
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto grid max-w-6xl gap-4 px-6 py-10 md:grid-cols-2 md:px-10 lg:grid-cols-4">
        {FEATURES.map(({ title, body, icon: Icon, to }, index) => (
          <Link
            key={title}
            to={to}
            className={`cs-panel cs-panel-interactive cs-fade-up group block p-4 ${
              index === 1
                ? "cs-fade-up-delay-1"
                : index === 2
                  ? "cs-fade-up-delay-2"
                  : index === 3
                    ? "cs-fade-up-delay-3"
                    : ""
            }`}
          >
            <Icon size={18} className="text-brand transition-transform group-hover:scale-110" />
            <h2 className="mt-3 text-sm font-semibold">{title}</h2>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">{body}</p>
            <p className="mt-4 text-[11px] font-medium text-brand/80 group-hover:text-brand">
              Open →
            </p>
          </Link>
        ))}
      </section>
    </div>
  );
}
