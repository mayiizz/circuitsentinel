import {
  Boxes,
  CircuitBoard,
  FileSearch,
  FileText,
  FolderKanban,
  GitBranch,
  Home,
  MessageSquare,
  Network,
  Settings,
  Shield,
} from "lucide-react";
import { Link, useRouterState } from "@tanstack/react-router";

const PRIMARY_NAV = [
  { to: "/", label: "Home", icon: Home },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/schematic", label: "Schematic", icon: CircuitBoard },
  { to: "/findings", label: "Findings", icon: FileSearch },
  { to: "/components", label: "Components", icon: Boxes },
  { to: "/datasheets", label: "Datasheets", icon: FileText },
  { to: "/evidence", label: "Evidence Graph", icon: Network },
] as const;

const OPS_NAV = [
  { to: "/assistant", label: "Assistant", icon: MessageSquare },
  { to: "/governance", label: "Governance", icon: Shield },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

function NavLink({
  to,
  label,
  icon: Icon,
  pathname,
}: {
  to: string;
  label: string;
  icon: typeof Home;
  pathname: string;
}) {
  const active = to === "/" ? pathname === "/" : pathname.startsWith(to);
  return (
    <Link
      to={to}
      className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-xs transition-colors max-md:justify-center max-md:px-2 ${
        active
          ? "cs-nav-active text-foreground"
          : "text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
      }`}
      title={label}
    >
      <Icon size={16} className={active ? "text-brand" : undefined} />
      <span className="max-md:hidden">{label}</span>
    </Link>
  );
}

export function AppSidebar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <aside className="flex w-[220px] shrink-0 flex-col border-r border-line bg-sidebar text-sidebar-foreground max-md:w-16">
      <div className="flex items-center gap-2.5 border-b border-line px-4 py-4 max-md:justify-center max-md:px-2">
        <span className="grid size-9 place-items-center rounded-lg bg-brand text-brand-foreground shadow-[0_0_24px_#16c8f455]">
          <CircuitBoard size={18} strokeWidth={2.2} />
        </span>
        <div className="min-w-0 max-md:hidden">
          <p className="truncate text-sm font-semibold tracking-tight">CircuitSentinel</p>
          <p className="truncate text-[10px] text-muted-foreground">EDA intelligence</p>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-4 overflow-y-auto p-2" aria-label="Primary">
        <div className="flex flex-col gap-0.5">
          {PRIMARY_NAV.map((item) => (
            <NavLink key={item.to} {...item} pathname={pathname} />
          ))}
        </div>
        <div>
          <p className="mb-1 px-3 text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/70 max-md:sr-only">
            Operations
          </p>
          <div className="flex flex-col gap-0.5">
            {OPS_NAV.map((item) => (
              <NavLink key={item.to} {...item} pathname={pathname} />
            ))}
          </div>
        </div>
      </nav>

      <div className="hidden border-t border-line px-4 py-3 text-[10px] leading-4 text-muted-foreground md:block">
        <p className="flex items-center gap-1.5 font-medium text-foreground/80">
          <GitBranch size={12} className="text-brand" /> Least-privilege crew
        </p>
        <p className="mt-1">Schematic analysis, datasheet evidence, and fail-closed governed actions.</p>
      </div>
    </aside>
  );
}
