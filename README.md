# CircuitSentinel

CircuitSentinel is a read-only hardware-design investigation workspace. It helps engineers inspect KiCad schematics, review KiCad ERC and netlist connectivity when available, attach datasheet evidence with explicit provenance, and run a narrow recommended-supply check against user-stated operating assumptions.

The system does not edit schematics, invent voltages from net names, auto-match parts from filenames, or certify that a design is electrically safe.

## Problem and goals

Hardware review tools and agent workflows often mix parser facts, inferred electrical meaning, and broad pass/fail language. That makes it hard to know what was measured, what was assumed, and what remains unproven.

CircuitSentinel is built around three goals:

1. **Separate evidence from judgment** — parser output, KiCad ERC/netlist results, datasheet text, and user assumptions remain distinct.
2. **Require explicit operator intent** — datasheet-to-component links, device variant selection, and stated supply voltage are never inferred from filenames, symbols, or net labels.
3. **Keep checks conservative** — a `no_violation_detected` outcome applies only to the single recommended-supply check that ran, not to the whole circuit.

Legacy `/api/actions/*` routes remain permanently fail-closed. Privileged sandbox execution goes through Human-in-the-Loop proposals (`/api/proposals`) with explicit approve. The local MCP HTTP interface still refuses privileged tools.

## Key features

- Upload and analyze `.kicad_sch`, PDF, and common image formats with strict size and MIME validation
- KiCad schematic parsing for symbols, labels, hierarchy, and structural counts
- Optional KiCad CLI stages: ERC, SVG preview, and XML netlist export
- Provenance-preserving Evidence Graph linking components, pins, nets, findings, and user-confirmed datasheets
- Datasheet PDF ingestion with conservative text extraction and voltage-fact normalization
- Explicit datasheet↔component linking (no auto-matching)
- Exact device-variant selection when multiple recommended ranges exist
- Recommended-supply check (`recommended_supply_vs_stated_rail`) against user-stated voltage
- Operator UI with Findings, Components, Datasheet, and Governance tabs
- Local MCP sandbox (`get_component_status`, privileged placement refused at MCP gate)
- HITL proposals: create, review, approve/reject, locked sandbox execution + audit trail
- Legacy `/api/actions/*` remain fail-closed (do not bypass HITL)

## Architecture and technology stack

```
Browser (Vite / TanStack React)
        |  /api, /health (dev proxy)
        v
FastAPI (:8000)
  ├── schematics analyze / files / preview
  ├── datasheet ingest / links / supply checks
  ├── /api/proposals/* → HITL store + locked sandbox executor
  └── /api/actions/* → policy_runtime (permanently fail-closed)

Optional independent MCP (:8001 POST /mcp)
  bearer auth + local privileged-tool fail-closed
```

| Layer | Technology |
|-------|------------|
| API | Python 3.10+, FastAPI, Uvicorn, Pydantic |
| Schematics | Custom `.kicad_sch` parser; optional `kicad-cli` for ERC, SVG, and netlist |
| Datasheets | `pypdf` text extraction and conservative normalization |
| Frontend | React 19, TanStack Start/Router, Vite, Tailwind CSS |
| Sandbox MCP | In-memory MCP server (`app/tools/circuit_mcp.py`) |

Secrets stay on the server. The browser never receives MCP bearer tokens.

## How it works

### Schematic analysis

1. Upload a schematic through the UI or `POST /api/schematics/analyze`.
2. The server validates extension, MIME type, and size, then stores the file under a UUID-backed id.
3. For `.kicad_sch`, the parser extracts confirmed structural findings.
4. When `kicad-cli` is available, ERC, SVG preview, and netlist export run against a temporary copy; the uploaded file is never modified.
5. Results are returned in explicit buckets: `confirmed`, `erc`, `netlist`, `evidence_graph`, `viewer`, `finding_interpretations`, `limitations`, and `validation_errors`.

| Format | Confirmed content |
|--------|-------------------|
| `.kicad_sch` | Symbols, labels, wire/junction counts, hierarchy; optional ERC, SVG, netlist |
| `.pdf` | Page count and extractable text (not electrical connectivity) |
| `.png`, `.jpg`, `.jpeg`, `.webp` | Format, dimensions, and color mode |

If a KiCad CLI stage is unavailable or fails, the corresponding report sets `ran: false` with a `failure_reason`. Missing ERC is never treated as a clean pass.

### Evidence Graph

Analysis builds a graph of nodes and edges with required provenance:

| Provenance | Source |
|------------|--------|
| `parser` | Schematic parser |
| `kicad_erc` | KiCad ERC |
| `kicad_netlist` | KiCad netlist connectivity |
| `user_confirmed` | Operator-confirmed datasheet links |

Node kinds include component, pin, finding, net, and datasheet document. Edges record relationships such as `has_pin`, `connected_to`, `mentions_component`, and `user_confirmed_datasheet`. The graph stores evidence relationships; it does not invent electrical conclusions.

### Datasheet ingestion

`POST /api/datasheets/ingest` accepts a PDF, extracts page text with `pypdf`, and normalizes a limited set of voltage facts when section or table context is clear. Unresolved candidates are retained. Filename is never treated as a part match. Scanned pages without extractable text are not OCR’d.

### Explicit component linking

`POST /api/datasheets/links` requires the operator to select a component reference and confirm the datasheet link. Links are never auto-matched. Duplicate links return HTTP 409 with `status: duplicate`. Confirmed links can appear in the Evidence Graph with `user_confirmed` provenance.

### Variant selection

When a datasheet yields multiple `variant:` recommended ranges (for example LM358 vs LM358B), the operator must choose an exact `device_variant`. Matching is exact: `LM358` is not `LM358B`. Variant is never inferred from reference designator, symbol name, or filename.

### Recommended-supply checks

`POST /api/checks/recommended_supply` compares a user-stated operating supply (`stated_supply.value_v`) to linked facts tagged `recommended_operating`.

| Field | Meaning |
|-------|---------|
| Check id | `recommended_supply_vs_stated_rail` |
| Outcomes | `no_violation_detected`, `potential_violation`, `inconclusive`, `error` |

**`no_violation_detected` does not certify that the whole circuit is safe or correct.** It means only that the stated supply fell within the selected variant’s recommended-operating bounds for this single check. Absolute-maximum ratings are never used as operating limits. Net names are never treated as voltage measurements.

## Sandbox MCP and governed actions

### MCP server (independent)

| Item | Detail |
|------|--------|
| App | `app.tools.circuit_mcp:app` |
| Endpoint | `POST /mcp` (JSON-RPC 2.0 over SSE) |
| Auth | `Authorization: Bearer <CIRCUITSENTINEL_MCP_TOKEN>` |
| Tools | `get_component_status` (executable), `simulate_unverified_placement` (listed but refused) |

The MCP server implements tools in memory. Bearer auth identifies the caller; privileged mutations fail closed at the MCP trust boundary. `notifications/initialized` (JSON-RPC notification without `id`) returns HTTP 202 with an empty body.

### Human-in-the-Loop proposals

Protected sandbox tools run only after explicit approval:

1. `POST /api/proposals` creates a pending proposal (server-minted ID, content hash). **Does not execute.**
2. `POST /api/proposals/{id}/approve` accepts a decision note only (no replacement params), verifies hash/expiry/status under `fcntl.flock`, then runs the in-memory sandbox via an internal registry.
3. `POST /api/proposals/{id}/reject` closes a pending proposal without execution.

Execution mutates the **in-memory MCP sandbox only** — not KiCad schematic files. Audit events append to `uploads/hitl_audit/events.jsonl` (application-level append-only; not cryptographically tamper-evident). POSIX file locks are required for transitions; Windows builds raise a clear unsupported error.

The dashboard API has **no authentication**. Actor labels default to `local-operator` (override with `CIRCUITSENTINEL_HITL_ACTOR`) and are **audit labels only**, not credentials.

Until real auth exists, `POST /api/proposals/{id}/approve`, `/reject`, and `/reconcile` **refuse non-loopback peers** (immediate TCP client host only; `X-Forwarded-For` is ignored). Loopback protection does **not** stop malicious local processes or browser-based attacks on the same machine. Do not expose the API on non-loopback interfaces to untrusted networks.

If approval claims a proposal (`approved`) but the process dies before `executed`/`failed`, call `POST /api/proposals/{id}/reconcile` to mark `uncertain`. That path never re-executes the tool.

**LangGraph assistant** (`POST /api/assistant/chat`): default `CIRCUITSENTINEL_AGENT_MODE=demo` is deterministic and needs no credentials. Optional `llm` mode uses **Groq** (`GROQ_API_KEY`, default model `qwen/qwen3.8-27b`) and fails clearly when the key is missing. The assistant may call allowlisted read-only tools and create pending HITL proposals; it cannot approve, reject, reconcile, or execute.

### Legacy dashboard governed routes

`POST /api/actions/*` still calls `app/policy_runtime.invoke_governed_tool`, which is permanently **fail-closed** (`blocked`). These routes never execute tools and must not be used as an approval bypass.

## Prerequisites

- Python 3.10 or newer
- Node.js with npm or bun (frontend)
- Optional: KiCad (`kicad-cli`) for ERC, SVG preview, and netlist export

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Frontend dependencies:

```bash
cd frontend
npm install   # or: bun install
```

Uploaded schematics and datasheet artifacts are stored under `uploads/` (gitignored).

## Environment configuration

Copy `.env.example` to `.env` and set local values. Do not commit `.env` or live secrets.

| Variable | Purpose |
|----------|---------|
| `CIRCUITSENTINEL_MCP_TOKEN` | Bearer token required by `POST /mcp` |
| `CIRCUITSENTINEL_MAX_UPLOAD_MB` | Upload size limit in megabytes (default `20`) |
| `CIRCUITSENTINEL_KICAD_CLI` | Optional absolute path to `kicad-cli` |
| `CIRCUITSENTINEL_HITL_ACTOR` | Optional audit actor label for HITL decisions (default `local-operator`) |

## Running the application

Use separate terminals from the project root with the virtual environment active.

### Backend (port 8000)

```bash
set -a && source .env && set +a
# Optional on macOS if kicad-cli is not on PATH:
# export CIRCUITSENTINEL_KICAD_CLI=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Health: `http://127.0.0.1:8000/health`
- API root: `http://127.0.0.1:8000/`

### Frontend

```bash
cd frontend
npm run dev   # or: bun run dev
```

Open the URL printed by Vite. The Vite config proxies `/api` and `/health` to `http://127.0.0.1:8000`.

### MCP server (optional, port 8001)

```bash
set -a && source .env && set +a
uvicorn app.tools.circuit_mcp:app --host 127.0.0.1 --port 8001
```

## API endpoint reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Process liveness |
| `GET` | `/` | Short JSON pointer to the UI |
| `POST` | `/api/schematics/analyze` | Multipart schematic upload and analysis |
| `GET` | `/api/schematics/files/{file_id}` | Uploaded schematic bytes |
| `GET` | `/api/schematics/files/{file_id}/preview` | SVG preview when available |
| `POST` | `/api/datasheets/ingest` | PDF datasheet ingest and normalize |
| `POST` | `/api/datasheets/links` | Explicit datasheet↔component link |
| `POST` | `/api/checks/recommended_supply` | Recommended-supply vs stated rail |
| `POST` | `/api/actions/get_component_status` | Legacy fail-closed path (always blocked) |
| `POST` | `/api/actions/simulate_unverified_placement` | Legacy fail-closed path (always blocked) |
| `POST` | `/api/proposals` | Create pending HITL proposal (no execute) |
| `GET` | `/api/proposals` | List proposals (`?status=` optional) |
| `GET` | `/api/proposals/{id}` | Get proposal |
| `POST` | `/api/proposals/demo` | Deterministic demo proposal (not an LLM) |
| `POST` | `/api/proposals/{id}/approve` | Approve by ID + execute (loopback-only) |
| `POST` | `/api/proposals/{id}/reject` | Reject pending (loopback-only; never executes) |
| `POST` | `/api/proposals/{id}/reconcile` | `approved` → `uncertain` after interrupt (no re-exec) |
| `POST` | `/api/assistant/chat` | LangGraph assistant (demo default; proposal create optional) |

MCP (separate process): `POST http://127.0.0.1:8001/mcp` with bearer authentication.

### Local startup

```bash
# Backend (loopback)
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000

# Frontend
cd frontend && npm install && npm run dev
# open http://127.0.0.1:8080 (or the Vite port printed)
```

Agent → proposal → human approval:

1. Open `/assistant`, ask a question (optionally create a proposal).
2. Confirm the proposal appears as `pending` on `/governance` and no sandbox mutation occurred for state-changing actions.
3. Approve on Governance (loopback only). Execution uses the stored HITL registry (sandbox simulation only for placement).
4. Legacy `/api/actions/*` remains blocked.

## Testing

```bash
# Backend unit and integration tests
pytest

# Frontend
cd frontend
npm test
npm run build
```

The backend suite covers schematic analyze/viewer/ERC stages, datasheet ingest/normalize/link, recommended-supply checks (including variant selection), Evidence Graph construction, MCP protocol behavior, fail-closed governed actions, and workflow fixtures.

## Project structure

| Path | Role |
|------|------|
| `app/main.py` | FastAPI routes for schematics, datasheets, checks, HITL, legacy actions |
| `app/hitl/` | Proposals, hashing, locked store, registry executor, audit |
| `app/schematics/` | Upload, validation, parse, ERC, render, netlist, interpretation |
| `app/schematics/evidence/` | Evidence Graph models and builder |
| `app/datasheets/` | Ingest, normalize, store, link, recommended-supply check |
| `app/policy_runtime.py` | Permanently fail-closed legacy governed invoke |
| `app/tools/circuit_mcp.py` | In-memory MCP sandbox (+ internal HITL execute helper) |
| `frontend/` | React investigation workspace |
| `tests/` | Pytest suite and fixtures |
| `uploads/` | Local uploads (gitignored) |
| `.env.example` | Documented environment template |

## Engineering assumptions, safety boundaries, and limitations

### Assumptions

- Stated supply voltage is an operator-provided assumption, not a measurement.
- Device variant must be selected explicitly when multiple recommended ranges exist.
- Datasheet links are operator-confirmed; the system does not auto-identify parts from filenames.
- KiCad CLI presence is optional; analysis still returns parser findings when CLI stages are unavailable.

### Safety boundaries

- CircuitSentinel does not modify uploaded schematics.
- Absolute-maximum datasheet ratings are never used as recommended operating limits.
- Circuit net names and pin-to-net links are never treated as voltage measurements.
- `no_violation_detected` applies only to `recommended_supply_vs_stated_rail` for the stated inputs.
- Absence of ERC findings is not a safety certification.
- The product is an investigation aid, not a substitute for simulation, peer review, or hardware validation.

### Technical limitations

- PDF datasheet ingest is text-only (no OCR).
- Ambiguous or incomplete recommended ranges yield `inconclusive`.
- Visual or PDF inspection does not establish electrical connectivity.
- Evidence Graph edges are provenance-tagged relationships, not electrical judgments.
- Legacy `/api/actions/*` remain permanently fail-closed; use `/api/proposals` for sandbox execution.
- HITL approve executes in-memory sandbox tools only — never KiCad schematic file edits.
- HITL does not claim exactly-once execution across crashes; `uncertain` is a non-retryable recovery state.
- Bind the API to `127.0.0.1` for local use; loopback HITL guards are not authentication.
- LangGraph assistant demo mode is labelled; live mode requires credentials and never silently falls back to fake autonomy.
- MCP bearer tokens must remain server-side; do not commit secrets.
