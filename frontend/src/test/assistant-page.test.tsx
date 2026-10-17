import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const assistantChat = vi.fn();

vi.mock("@/lib/api", () => ({
  assistantChat: (...args: unknown[]) => assistantChat(...args),
}));

vi.mock("@/components/layout/AppTopBar", () => ({
  AppTopBar: () => <div data-testid="topbar" />,
}));

vi.mock("@/lib/workspace", () => ({
  useWorkspace: () => ({ analysis: null }),
}));

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...mod,
    Link: ({
      to,
      children,
      className,
    }: {
      to: string;
      children: ReactNode;
      className?: string;
    }) => (
      <a href={to} className={className}>
        {children}
      </a>
    ),
  };
});

describe("Assistant page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls assistantChat and renders the backend answer", async () => {
    assistantChat.mockResolvedValue({
      mode: "demo",
      demo_label: "[deterministic-demo]",
      answer: "UNIQUE_ASSISTANT_ANSWER_42",
      uncertainty: [],
      evidence: [],
      tools_used: ["get_component_status"],
      proposal_id: null,
      proposal_status: null,
      proposal_created: false,
      graph_path: ["classify_request"],
      limitations: [],
    });

    const { AssistantPage } = await import("@/routes/assistant");
    render(<AssistantPage />);
    fireEvent.click(screen.getByRole("button", { name: /Ask assistant/i }));

    await waitFor(() => {
      expect(assistantChat).toHaveBeenCalledTimes(1);
      expect(screen.getByText("UNIQUE_ASSISTANT_ANSWER_42")).toBeInTheDocument();
    });
    expect(screen.queryByText(/executed successfully/i)).not.toBeInTheDocument();
  });

  it("shows a governance link for a created pending proposal", async () => {
    const proposalId = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    assistantChat.mockResolvedValue({
      mode: "demo",
      demo_label: "[deterministic-demo]",
      answer: "Created pending HITL proposal.",
      uncertainty: [],
      evidence: [],
      tools_used: [],
      proposal_id: proposalId,
      proposal_status: "pending",
      proposal_created: true,
      graph_path: ["create_proposal_if_requested"],
      limitations: [],
    });

    const { AssistantPage } = await import("@/routes/assistant");
    render(<AssistantPage />);
    fireEvent.click(screen.getByRole("button", { name: /Ask assistant/i }));

    await waitFor(() => {
      expect(screen.getByRole("link", { name: proposalId })).toHaveAttribute(
        "href",
        "/governance",
      );
    });
  });

  it("fills the question from a prompt chip", async () => {
    assistantChat.mockResolvedValue({
      mode: "demo",
      demo_label: "[deterministic-demo]",
      answer: "ok",
      uncertainty: [],
      evidence: [],
      tools_used: [],
      proposal_id: null,
      proposal_status: null,
      proposal_created: false,
      graph_path: [],
      limitations: [],
    });

    const { AssistantPage } = await import("@/routes/assistant");
    render(<AssistantPage />);
    fireEvent.click(screen.getByRole("button", { name: "Placement proposal" }));
    fireEvent.click(screen.getByRole("button", { name: /Ask assistant/i }));

    await waitFor(() => {
      expect(assistantChat).toHaveBeenCalledWith(
        expect.objectContaining({
          message: "Please propose a sandbox placement",
          create_proposal: true,
          proposed_action: "simulate_unverified_placement",
        }),
      );
    });
  });
});
