import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRouter,
} from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { routeTree } from "@/routeTree.gen";

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const history = createMemoryHistory({ initialEntries: [path] });
  const router = createRouter({
    routeTree,
    history,
    context: { queryClient },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("EDA shell smoke", () => {
  it("renders primary nav links in the sidebar", async () => {
    renderAt("/");
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    for (const label of [
      "Home",
      "Projects",
      "Schematic",
      "Findings",
      "Components",
      "Datasheets",
      "Evidence Graph",
      "Assistant",
      "Governance",
      "Settings",
    ]) {
      expect(within(nav).getByTitle(label)).toBeInTheDocument();
    }
  });

  it("shows Projects local empty state when no sessions", async () => {
    renderAt("/projects");
    expect(await screen.findByText("No local sessions yet")).toBeInTheDocument();
    expect(screen.getByText(/not cloud project storage/i)).toBeInTheDocument();
  });

  it("shows Schematic upload empty workspace without analysis", async () => {
    renderAt("/schematic");
    expect(
      await screen.findByText(/Drag and drop your KiCad schematic here/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/No analysis loaded/i)).toBeInTheDocument();
  });
});
