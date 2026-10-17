import {
  ApiError,
  type ActionProposal,
  type ActionResponse,
  type AnalysisResponse,
  type CircuitAnalysisReport,
  type CircuitAnalyzeRequest,
  type ComponentInventoryItem,
  type CreateProposalRequest,
  type DatasheetComponentLinkRequest,
  type DatasheetComponentLinkResponse,
  type DatasheetIngestReport,
  type AssistantChatRequest,
  type AssistantChatResponse,
  type DecisionRequest,
  type EngineeringCheckRequest,
  type ReconcileRequest,
  type EngineeringCheckResponse,
  type GauntletReport,
  type PlacementRequest,
  type ProposalListResponse,
  type ProposalStatus,
  type RailEntry,
  type RailMap,
} from "@/lib/types";

const API_BASE = (import.meta.env["VITE_API_BASE_URL"] as string | undefined)?.replace(/\/$/, "") ?? "";

function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

/** Prefix relative viewer URLs when `VITE_API_BASE_URL` points at another host. */
export function assetUrl(path: string | null | undefined): string {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  return apiUrl(path.startsWith("/") ? path : `/${path}`);
}

export async function healthCheck(): Promise<{ status: string; service: string }> {
  const response = await fetch(apiUrl("/health"));
  const data = (await parseJson(response)) as { status?: string; service?: string; detail?: string };
  if (!response.ok) {
    throw new ApiError(detailFrom(data, `Health check failed (${response.status}).`), response.status, data);
  }
  return {
    status: data.status ?? "unknown",
    service: data.service ?? "circuitsentinel",
  };
}

function detailFrom(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  return fallback;
}

async function parseJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ApiError(`Server returned ${response.status} without JSON.`, response.status, null);
  }
}

export async function analyzeSchematic(file: File): Promise<AnalysisResponse> {
  const form = new FormData();
  form.append("file", file, file.name);

  const response = await fetch(apiUrl("/api/schematics/analyze"), {
    method: "POST",
    body: form,
  });

  const data = (await parseJson(response)) as AnalysisResponse;

  if (!response.ok && data.status !== "error") {
    const detail =
      (Array.isArray(data.validation_errors) && data.validation_errors.join("; ")) ||
      detailFrom(data, `Request failed (${response.status}).`);
    throw new ApiError(detail, response.status, data);
  }

  return data;
}

export async function getComponentStatus(): Promise<ActionResponse> {
  const response = await fetch(apiUrl("/api/actions/get_component_status"), {
    method: "POST",
  });
  const data = (await parseJson(response)) as ActionResponse;

  if (!response.ok && !data.decision) {
    throw new ApiError(detailFrom(data, `Request failed (${response.status}).`), response.status, data);
  }

  return data;
}

export async function simulateUnverifiedPlacement(
  body: PlacementRequest = {
    reference: "TEST-COMPONENT",
    x_mm: 10,
    y_mm: 20,
  },
): Promise<ActionResponse> {
  const response = await fetch(apiUrl("/api/actions/simulate_unverified_placement"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await parseJson(response)) as ActionResponse;

  if (!response.ok && !data.decision) {
    throw new ApiError(detailFrom(data, `Request failed (${response.status}).`), response.status, data);
  }

  return data;
}

export async function listProposals(status?: ProposalStatus): Promise<ProposalListResponse> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const response = await fetch(apiUrl(`/api/proposals${query}`));
  const data = (await parseJson(response)) as ProposalListResponse & { detail?: string };
  if (!response.ok) {
    throw new ApiError(detailFrom(data, `List proposals failed (${response.status}).`), response.status, data);
  }
  return data;
}

export async function getProposal(proposalId: string): Promise<ActionProposal> {
  const response = await fetch(apiUrl(`/api/proposals/${encodeURIComponent(proposalId)}`));
  const data = (await parseJson(response)) as ActionProposal & { detail?: string };
  if (!response.ok) {
    throw new ApiError(detailFrom(data, `Get proposal failed (${response.status}).`), response.status, data);
  }
  return data;
}

export async function createProposal(body: CreateProposalRequest): Promise<ActionProposal> {
  const response = await fetch(apiUrl("/api/proposals"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await parseJson(response)) as ActionProposal & { detail?: string };
  if (!response.ok) {
    throw new ApiError(detailFrom(data, `Create proposal failed (${response.status}).`), response.status, data);
  }
  return data;
}

export async function createDemoProposal(
  kind: "read_status" | "sandbox_placement" = "read_status",
): Promise<ActionProposal> {
  const response = await fetch(apiUrl("/api/proposals/demo"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  });
  const data = (await parseJson(response)) as ActionProposal & { detail?: string };
  if (!response.ok) {
    throw new ApiError(detailFrom(data, `Demo proposal failed (${response.status}).`), response.status, data);
  }
  return data;
}

/** Approve by proposal ID only — never send replacement action parameters. */
export async function approveProposal(
  proposalId: string,
  body: DecisionRequest = {},
): Promise<ActionProposal> {
  const response = await fetch(apiUrl(`/api/proposals/${encodeURIComponent(proposalId)}/approve`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision_note: body.decision_note ?? null }),
  });
  const data = (await parseJson(response)) as ActionProposal & { detail?: string; code?: string };
  if (!response.ok) {
    throw new ApiError(detailFrom(data, `Approve failed (${response.status}).`), response.status, data);
  }
  return data;
}

export async function rejectProposal(
  proposalId: string,
  body: DecisionRequest = {},
): Promise<ActionProposal> {
  const response = await fetch(apiUrl(`/api/proposals/${encodeURIComponent(proposalId)}/reject`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision_note: body.decision_note ?? null }),
  });
  const data = (await parseJson(response)) as ActionProposal & { detail?: string };
  if (!response.ok) {
    throw new ApiError(detailFrom(data, `Reject failed (${response.status}).`), response.status, data);
  }
  return data;
}

/** Mark interrupted approved proposals uncertain — never re-executes. */
export async function reconcileProposal(
  proposalId: string,
  body: ReconcileRequest = {},
): Promise<ActionProposal> {
  const response = await fetch(
    apiUrl(`/api/proposals/${encodeURIComponent(proposalId)}/reconcile`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: body.reason ?? null }),
    },
  );
  const data = (await parseJson(response)) as ActionProposal & { detail?: string };
  if (!response.ok) {
    throw new ApiError(
      detailFrom(data, `Reconcile failed (${response.status}).`),
      response.status,
      data,
    );
  }
  return data;
}

export async function assistantChat(body: AssistantChatRequest): Promise<AssistantChatResponse> {
  const response = await fetch(apiUrl("/api/assistant/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await parseJson(response)) as AssistantChatResponse & { detail?: string };
  if (!response.ok) {
    throw new ApiError(
      detailFrom(data, `Assistant failed (${response.status}).`),
      response.status,
      data,
    );
  }
  return data;
}

export async function ingestDatasheet(file: File): Promise<DatasheetIngestReport> {
  const form = new FormData();
  form.append("file", file, file.name);

  const response = await fetch(apiUrl("/api/datasheets/ingest"), {
    method: "POST",
    body: form,
  });
  const data = (await parseJson(response)) as DatasheetIngestReport;

  // Validation errors are HTTP 4xx with a DatasheetIngestReport body.
  if (!response.ok) {
    throw new ApiError(
      data.failure_reason || detailFrom(data, `Datasheet ingest failed (${response.status}).`),
      response.status,
      data,
    );
  }

  return data;
}

export async function createDatasheetLink(
  body: DatasheetComponentLinkRequest,
): Promise<DatasheetComponentLinkResponse> {
  const response = await fetch(apiUrl("/api/datasheets/links"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await parseJson(response)) as DatasheetComponentLinkResponse;

  // 409 duplicate still returns a usable link payload; surface it to the caller.
  if (response.status === 409 && data.status === "duplicate") {
    return data;
  }

  if (!response.ok) {
    throw new ApiError(
      data.failure_reason || detailFrom(data, `Datasheet link failed (${response.status}).`),
      response.status,
      data,
    );
  }

  return data;
}

export async function runRecommendedSupplyCheck(
  body: EngineeringCheckRequest,
): Promise<EngineeringCheckResponse> {
  const response = await fetch(apiUrl("/api/checks/recommended_supply"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await parseJson(response)) as EngineeringCheckResponse;

  if (!response.ok) {
    throw new ApiError(
      data.failure_reason || detailFrom(data, `Supply check failed (${response.status}).`),
      response.status,
      data,
    );
  }

  return data;
}

export async function getCircuitRails(fileId: string): Promise<RailMap> {
  const response = await fetch(apiUrl(`/api/circuit/${fileId}/rails`));
  const data = (await parseJson(response)) as RailMap & { detail?: string };
  if (!response.ok) {
    throw new ApiError(detailFrom(data, `Load rails failed (${response.status}).`), response.status, data);
  }
  return data;
}

export async function putCircuitRails(fileId: string, rails: RailEntry[]): Promise<RailMap> {
  const response = await fetch(apiUrl(`/api/circuit/${fileId}/rails`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rails }),
  });
  const data = (await parseJson(response)) as RailMap & { detail?: string };
  if (!response.ok) {
    throw new ApiError(detailFrom(data, `Save rails failed (${response.status}).`), response.status, data);
  }
  return data;
}

export async function getCircuitComponents(fileId: string): Promise<ComponentInventoryItem[]> {
  const response = await fetch(apiUrl(`/api/circuit/${fileId}/components`));
  const data = (await parseJson(response)) as ComponentInventoryItem[] | { detail?: string };
  if (!response.ok) {
    throw new ApiError(
      detailFrom(data, `Load components failed (${response.status}).`),
      response.status,
      data,
    );
  }
  return data as ComponentInventoryItem[];
}

export async function runCircuitAnalysis(
  fileId: string,
  body?: CircuitAnalyzeRequest,
): Promise<CircuitAnalysisReport> {
  const response = await fetch(apiUrl(`/api/circuit/${fileId}/analyze`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  const data = (await parseJson(response)) as CircuitAnalysisReport & { detail?: string };
  if (!response.ok) {
    throw new ApiError(
      data.failure_reason || detailFrom(data, `Circuit analysis failed (${response.status}).`),
      response.status,
      data,
    );
  }
  return data;
}

/** Run the deterministic Prompt-Injection Gauntlet on the server (local only). */
export async function runPromptInjectionGauntlet(): Promise<GauntletReport> {
  const response = await fetch(apiUrl("/api/agents/gauntlet"), {
    method: "POST",
  });
  const data = (await parseJson(response)) as GauntletReport & { detail?: string };

  if (!response.ok) {
    throw new ApiError(
      detailFrom(data, `Gauntlet failed (${response.status}).`),
      response.status,
      data,
    );
  }

  return data;
}
