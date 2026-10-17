import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ActionProposal } from "@/lib/types";

const pendingProposal: ActionProposal = {
  id: "a".repeat(32),
  action: "get_component_status",
  params: {},
  prompt: "test",
  status: "pending",
  content_hash: "b".repeat(64),
  created_at: "2026-01-01T00:00:00+00:00",
  expires_at: "2099-01-01T00:00:00+00:00",
  decided_at: null,
  executed_at: null,
  decision_note: null,
  execution_result: null,
  failure_reason: null,
};

const executedProposal: ActionProposal = {
  ...pendingProposal,
  status: "executed",
  executed_at: "2026-01-01T01:00:00+00:00",
  execution_result: {
    sandbox: true,
    kicad_schematic_modified: false,
    tool_result: { reference: "TEST" },
  },
};

const listProposals = vi.fn();
const createProposal = vi.fn();
const createDemoProposal = vi.fn();
const approveProposal = vi.fn();
const rejectProposal = vi.fn();
const reconcileProposal = vi.fn();

vi.mock("@/lib/api", () => ({
  listProposals: (...args: unknown[]) => listProposals(...args),
  createProposal: (...args: unknown[]) => createProposal(...args),
  createDemoProposal: (...args: unknown[]) => createDemoProposal(...args),
  approveProposal: (...args: unknown[]) => approveProposal(...args),
  rejectProposal: (...args: unknown[]) => rejectProposal(...args),
  reconcileProposal: (...args: unknown[]) => reconcileProposal(...args),
}));

vi.mock("@/components/layout/AppTopBar", () => ({
  AppTopBar: () => <div data-testid="topbar" />,
}));

describe("Governance HITL proposals", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listProposals.mockResolvedValue({ proposals: [], count: 0 });
  });

  it("shows empty state then creates and lists a proposal", async () => {
    const { GovernancePage } = await import("@/routes/governance");
    render(<GovernancePage />);

    await waitFor(() => {
      expect(screen.getByText("No proposals")).toBeInTheDocument();
    });

    listProposals.mockResolvedValue({ proposals: [pendingProposal], count: 1 });
    createProposal.mockResolvedValue(pendingProposal);

    fireEvent.click(screen.getByRole("button", { name: "Create proposal" }));

    await waitFor(() => {
      expect(createProposal).toHaveBeenCalled();
      expect(screen.getByText("get_component_status")).toBeInTheDocument();
    });
    expect(screen.queryByText(/armoriq/i)).not.toBeInTheDocument();
  });

  it("approves by id only and shows executed result from API", async () => {
    listProposals.mockResolvedValue({ proposals: [pendingProposal], count: 1 });
    approveProposal.mockResolvedValue(executedProposal);

    const { GovernancePage } = await import("@/routes/governance");
    render(<GovernancePage />);

    await waitFor(() => {
      expect(screen.getByText(pendingProposal.id)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText(pendingProposal.id));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Approve & execute/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /Approve & execute/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Approve$/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /^Approve$/i }));

    await waitFor(() => {
      expect(approveProposal).toHaveBeenCalledWith(pendingProposal.id);
    });
  });

  it("shows API errors without claiming success", async () => {
    const { ApiError } = await import("@/lib/types");
    listProposals.mockRejectedValue(new ApiError("boom", 500, null));
    const { GovernancePage } = await import("@/routes/governance");
    render(<GovernancePage />);
    await waitFor(() => {
      expect(screen.getByText("boom")).toBeInTheDocument();
    });
    expect(screen.queryByText(/executed successfully/i)).not.toBeInTheDocument();
  });
});
