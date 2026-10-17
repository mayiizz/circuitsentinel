/** Types mirroring app/schematics/models.py and ActionResponse. */

export type AnalysisStatus = "ok" | "partial" | "error";
export type SchematicFormat = "kicad_sch" | "pdf" | "image";
export type RenderStatus = "ready" | "unavailable" | "error";
export type StageStatus = "complete" | "partial" | "failed" | "unavailable" | "skipped";
export type ActionDecision = "allowed" | "blocked" | "error" | string;

export interface UploadInfo {
  original_filename: string;
  stored_as: string;
  format: SchematicFormat;
  size_bytes: number;
}

export interface SymbolFinding {
  reference?: string | null;
  value?: string | null;
  lib_id?: string | null;
  unit?: number | null;
  uuid?: string | null;
  properties?: Record<string, string>;
  at_x?: number | null;
  at_y?: number | null;
  at_angle?: number | null;
}

export interface CoordinateMapping {
  reliable: boolean;
  units?: string | null;
  view_min_x?: number | null;
  view_min_y?: number | null;
  view_width?: number | null;
  view_height?: number | null;
  note?: string;
}

export interface ViewerInfo {
  file_id: string;
  format: SchematicFormat;
  source_url: string;
  preview_url?: string | null;
  render_status: RenderStatus;
  render_message: string;
  page_count?: number | null;
  content_type: string;
  coordinate_mapping: CoordinateMapping;
}

export interface LabelFinding {
  kind: string;
  text: string;
}

export interface ConnectivityHint {
  kind: string;
  detail: string;
}

export interface HierarchyNode {
  name: string;
  file?: string | null;
  detail?: string | null;
}

export interface ConfirmedFindings {
  symbols: SymbolFinding[];
  labels: LabelFinding[];
  connectivity: ConnectivityHint[];
  hierarchy: HierarchyNode[];
  pdf_text?: string | null;
  pages?: number | null;
}

export interface ErcFinding {
  rule_id: string;
  severity: string;
  description: string;
  reference?: string | null;
  pin?: string | null;
  x_mm?: number | null;
  y_mm?: number | null;
  item_description?: string | null;
  source: "kicad";
}

export interface ErcReport {
  ran: boolean;
  available: boolean;
  findings: ErcFinding[];
  error_count: number;
  warning_count: number;
  message_count: number;
  failure_reason?: string | null;
  kicad_version?: string | null;
  units?: string | null;
  how_to_enable?: string;
}

export interface VisualReport {
  observations: string[];
  disclaimer: string;
}

export interface StageResult {
  status: StageStatus;
  detail: string;
}

export interface AnalysisStages {
  parsing: StageResult;
  rendering: StageResult;
  erc: StageResult;
}

export interface FindingInterpretation {
  rule_id: string;
  severity: string;
  reference?: string | null;
  pin?: string | null;
  kicad_description: string;
  explanation: string;
  inspection_steps: string[];
  disclaimer: string;
}

export interface NetlistPin {
  number: string;
  unit?: string | null;
}

export interface NetlistComponent {
  reference: string;
  value?: string | null;
  lib_id?: string | null;
  footprint?: string | null;
  tstamps?: string | null;
  sheetpath?: string | null;
  pins?: NetlistPin[];
}

export interface NetlistNode {
  reference: string;
  pin: string;
  pintype?: string | null;
  pinfunction?: string | null;
}

export interface NetlistNet {
  code: string;
  name: string;
  name_kind?: "explicit" | "generated" | "unconnected";
  net_class?: string | null;
  nodes?: NetlistNode[];
}

/** Optional Phase 2+ fields returned by /api/schematics/analyze. */
export interface NetlistReport {
  ran: boolean;
  available: boolean;
  format?: "kicadxml" | null;
  components?: NetlistComponent[];
  nets?: NetlistNet[];
  component_count?: number;
  net_count?: number;
  failure_reason?: string | null;
  limitations?: string[];
}

export interface EvidenceNode {
  id: string;
  kind: string;
  label: string;
  attrs?: Record<string, unknown>;
  provenance: string;
}

export interface EvidenceEdge {
  id: string;
  source_id: string;
  target_id: string;
  kind: string;
  provenance: string;
}

export interface EvidenceGraph {
  nodes: EvidenceNode[];
  edges: EvidenceEdge[];
  citations: unknown[];
  limitations: string[];
}

export interface AnalysisResponse {
  status: AnalysisStatus;
  upload?: UploadInfo | null;
  viewer?: ViewerInfo | null;
  confirmed: ConfirmedFindings;
  erc: ErcReport;
  visual: VisualReport;
  stages?: AnalysisStages;
  finding_interpretations?: FindingInterpretation[];
  /** Phase 2 KiCad netlist connectivity (when applicable). */
  netlist?: NetlistReport;
  /** Phase 1–4 Circuit Evidence Graph (when built). */
  evidence_graph?: EvidenceGraph | null;
  unverified_suggestions: string[];
  validation_errors: string[];
  limitations: string[];
}

export interface ActionResponse {
  decision: ActionDecision;
  action: string;
  message: string;
  result?: unknown;
}

export interface PlacementRequest {
  reference: string;
  x_mm: number;
  y_mm: number;
}

/** HITL ActionProposal (mirror app/hitl/models.py). */

export type ProposalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "executed"
  | "failed"
  | "uncertain";

export type SupportedProposalAction =
  | "get_component_status"
  | "simulate_unverified_placement";

export interface ActionProposal {
  id: string;
  action: string;
  params: Record<string, unknown>;
  prompt?: string | null;
  status: ProposalStatus;
  content_hash: string;
  created_at: string;
  expires_at: string;
  decided_at?: string | null;
  executed_at?: string | null;
  decision_note?: string | null;
  execution_result?: unknown;
  failure_reason?: string | null;
}

export interface ProposalListResponse {
  proposals: ActionProposal[];
  count: number;
}

export interface CreateProposalRequest {
  action: SupportedProposalAction;
  params?: Record<string, unknown>;
  prompt?: string | null;
}

export interface DecisionRequest {
  decision_note?: string | null;
}

export interface ReconcileRequest {
  reason?: string | null;
}

export interface AssistantChatRequest {
  message: string;
  schematic_file_id?: string | null;
  create_proposal?: boolean;
  proposed_action?: "none" | "get_component_status" | "simulate_unverified_placement";
  proposed_params?: Record<string, unknown>;
}

export interface AssistantChatResponse {
  mode: "demo" | "llm";
  demo_label?: string | null;
  answer: string;
  uncertainty: string[];
  evidence: Array<Record<string, unknown>>;
  tools_used: string[];
  proposal_id?: string | null;
  proposal_status?: string | null;
  proposal_created: boolean;
  graph_path: string[];
  limitations: string[];
}

/** Phase 3A–4B datasheet models (mirror app/datasheets/models.py + checks.py). */

export type FactType =
  | "supply_voltage_max"
  | "supply_voltage_min"
  | "input_voltage_max"
  | "input_voltage_min";

export type DatasheetIngestStatus = "ok" | "partial" | "empty" | "error";
export type LinkStatus = "ok" | "duplicate" | "error";
export type CheckOutcome =
  | "potential_violation"
  | "no_violation_detected"
  | "inconclusive"
  | "error";

export interface DatasheetSource {
  document_id: string;
  filename?: string | null;
  content_sha256: string;
  page_count: number;
  byte_length: number;
}

export interface DatasheetPageText {
  page_number: number;
  text: string;
  char_count: number;
  has_text: boolean;
}

export interface RawDatasheetEvidence {
  id: string;
  kind: "page_text";
  document_id: string;
  page_number: number;
  text: string;
  extraction_method: "pypdf_extract_text";
  provenance: "datasheet_pdf";
}

export interface NormalizedDatasheetFact {
  id: string;
  fact_type: FactType;
  value: number;
  unit: string;
  qualifiers: string[];
  source_content_sha256: string;
  page_number: number;
  supporting_evidence_id: string;
  supporting_excerpt: string;
  provenance: "datasheet_normalized";
}

export interface UnresolvedNormalization {
  id: string;
  reason: string;
  attempted_fact_type?: FactType | null;
  page_number?: number | null;
  supporting_evidence_id?: string | null;
  candidate_text?: string | null;
}

export interface DatasheetIngestReport {
  status: DatasheetIngestStatus;
  source?: DatasheetSource | null;
  pages: DatasheetPageText[];
  raw_evidence: RawDatasheetEvidence[];
  facts: NormalizedDatasheetFact[];
  unresolved: UnresolvedNormalization[];
  claims: unknown[];
  likely_scanned: boolean;
  failure_reason?: string | null;
  limitations: string[];
}

export interface DatasheetComponentLink {
  id: string;
  schematic_file_id: string;
  component_reference: string;
  document_id: string;
  content_sha256: string;
  provenance: "user_confirmed";
  created_at: string;
  status: "active";
}

export interface DatasheetComponentLinkRequest {
  schematic_file_id: string;
  component_reference: string;
  document_id: string;
  content_sha256: string;
}

export interface DatasheetComponentLinkResponse {
  status: LinkStatus;
  link?: DatasheetComponentLink | null;
  facts: NormalizedDatasheetFact[];
  raw_evidence: RawDatasheetEvidence[];
  evidence_graph_additions?: EvidenceGraph | null;
  failure_reason?: string | null;
  limitations: string[];
}

export interface StatedSupplyVoltage {
  value_v: number;
  note?: string | null;
}

export interface EngineeringCheckRequest {
  schematic_file_id: string;
  component_reference: string;
  document_id: string;
  content_sha256: string;
  stated_supply?: StatedSupplyVoltage | null;
  /** Exact datasheet device variant (e.g. LM358). Never inferred. */
  device_variant?: string | null;
}

export interface EvidenceReference {
  fact_id?: string | null;
  evidence_id?: string | null;
  page_number?: number | null;
  excerpt?: string | null;
  fact_type?: string | null;
  qualifiers?: string[];
}

export interface EngineeringCheckFinding {
  check_id: string;
  outcome: CheckOutcome;
  component_reference: string;
  explanation: string;
  assumptions: string[];
  missing_information: string[];
  evidence_references: EvidenceReference[];
  link_id?: string | null;
  stated_supply_v?: number | null;
  datasheet_supply_min_v?: number | null;
  datasheet_supply_max_v?: number | null;
  selected_device_variant?: string | null;
}

export interface EngineeringCheckResponse {
  status: CheckOutcome;
  finding?: EngineeringCheckFinding | null;
  failure_reason?: string | null;
  limitations: string[];
}

/** Circuit-level electrical analysis (operator-confirmed rails). */
export type RailStatus = "unconfirmed" | "confirmed" | "unknown";
export type CircuitCheckStatus =
  | "passed"
  | "violation"
  | "inconclusive"
  | "not_performed"
  | "warning";
export type CircuitAssessment =
  | "violations_detected"
  | "no_violations_found_within_scope"
  | "inconclusive"
  | "error";

export interface RailEntry {
  net_name: string;
  value_v?: number | null;
  reference_net?: string | null;
  status: RailStatus;
  source: "operator";
  suggested?: boolean;
  suggestion_reason?: string | null;
}

export interface RailMap {
  schematic_file_id: string;
  rails: RailEntry[];
}

export interface CircuitEvidenceRef {
  fact_id?: string | null;
  evidence_id?: string | null;
  page_number?: number | null;
  excerpt?: string | null;
  fact_type?: string | null;
  qualifiers?: string[];
}

export interface CircuitCheckFinding {
  check_id: string;
  status: CircuitCheckStatus;
  explanation: string;
  component_refs: string[];
  nets: string[];
  assumed_conditions: string[];
  limits: string[];
  evidence_references: CircuitEvidenceRef[];
  missing_information: string[];
  limitations: string[];
}

export interface ComponentInventoryItem {
  reference: string;
  value?: string | null;
  lib_id?: string | null;
  footprint?: string | null;
  datasheet_linked: boolean;
  link_id?: string | null;
  document_id?: string | null;
  content_sha256?: string | null;
  identity_status: "linked" | "unresolved";
  connected_nets: string[];
}

export interface CircuitAnalysisCounts {
  components_total: number;
  components_evaluated: number;
  components_unresolved: number;
  checks_passed: number;
  checks_violations: number;
  checks_inconclusive: number;
  checks_not_performed: number;
  checks_warnings: number;
}

export interface CircuitAnalysisReport {
  assessment: CircuitAssessment;
  schematic_file_id: string;
  scope: string;
  limitations: string[];
  checks_not_performed: string[];
  counts: CircuitAnalysisCounts;
  rails: RailEntry[];
  components: ComponentInventoryItem[];
  findings: CircuitCheckFinding[];
  failure_reason?: string | null;
}

export interface CircuitAnalyzeRequest {
  rails?: RailEntry[] | null;
  device_variants?: Record<string, string>;
}

/** Decision source labels for Prompt-Injection Gauntlet / crew trust boundaries. */
export type DecisionSource = "crew_policy" | "mcp_fail_closed";

export interface AgentRoleResult {
  role: string;
  status: string;
  summary: string;
  evidence?: unknown[];
  proposed_changes?: ProposedChange[];
  error?: string | null;
}

export interface ProposedChange {
  summary: string;
  details?: string | null;
  target_reference?: string | null;
  supporting_evidence_ids?: string[];
  suggestion_only: boolean;
}

export interface CrewReport {
  status: string;
  analyst: AgentRoleResult;
  researcher: AgentRoleResult;
  proposer: AgentRoleResult;
  findings: unknown[];
  evidence: unknown[];
  proposed_changes: ProposedChange[];
  unresolved_questions: string[];
  limitations: string[];
  error?: string | null;
}

export interface GauntletEscalationAttempt {
  path: string;
  attempted_action: string;
  role: string;
  allowed_actions: string[];
  rejected: boolean;
  decision_source: DecisionSource;
  sandbox_unchanged: boolean;
  sandbox_before: Record<string, unknown>;
  sandbox_after: Record<string, unknown>;
  detail: string;
}

export interface GauntletReport {
  scenario_id: string;
  untrusted_passage: string;
  evidence_kind: "gauntlet_test_fixture";
  crew_report: CrewReport;
  injection_proposal?: ProposedChange | null;
  permissions_unchanged: boolean;
  permitted_sandbox_actions_before: string[];
  permitted_sandbox_actions_after: string[];
  role_permissions_before: Record<string, string[]>;
  role_permissions_after: Record<string, string[]>;
  escalation_attempts: GauntletEscalationAttempt[];
  sandbox_state_before: Record<string, unknown>;
  sandbox_state_after: Record<string, unknown>;
  schematic_modified: boolean;
  limitations: string[];
}

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}
