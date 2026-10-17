import type { ReactNode } from "react";

import { AppSidebar } from "@/components/layout/AppSidebar";
import { WorkspaceProvider } from "@/lib/workspace";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <WorkspaceProvider>
      <div className="flex min-h-screen bg-workspace text-foreground">
        <AppSidebar />
        <div className="flex min-w-0 flex-1 flex-col">{children}</div>
      </div>
    </WorkspaceProvider>
  );
}
