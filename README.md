# CircuitSentinel

Hackathon prototype for Flow State 2026. A policy-governed AI hardware-design agent with an in-memory MCP sandbox, an operator dashboard, and read-only schematic upload/analysis. It does not fabricate boards or deploy anything.

ArmorIQ enforces allow/deny through the real SDK flow (`capture_plan` → `get_intent_token` → `invoke`). The browser never talks to MCP and never receives API keys or bearer tokens.

## Requirements

- Python 3.10 or newer
- ArmorIQ account/API key
- Local MCP server plus a public HTTPS tunnel (for ArmorIQ registration)
- Optional: KiCad (`kicad-cli` on PATH) for future ERC runs — not required for upload/analysis

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with:

- `ARMORIQ_API_KEY` — ArmorIQ API key (or use `armoriq login`)
- `CIRCUITSENTINEL_MCP_TOKEN` — bearer token for `POST /mcp`
- `CIRCUITSENTINEL_MAX_UPLOAD_MB` — optional upload limit (default `20`)

Do not commit `.env`. Uploaded files land in `uploads/` (gitignored).

Confirm `armoriq.yaml` lists the `circuit` MCP (public tunnel URL ending in `/mcp`), bearer auth via `$CIRCUITSENTINEL_MCP_TOKEN`, and:

```yaml
policy:
  allow:
    - circuit.get_component_status
  deny:
    - circuit.simulate_unverified_placement
```

Then:

```bash
set -a && source .env && set +a
armoriq validate
armoriq register
```

## Run the stack

Use three terminals from the project root with the venv active.

**1. Sandbox MCP (port 8001)**

```bash
set -a && source .env && set +a
uvicorn app.tools.circuit_mcp:app --host 127.0.0.1 --port 8001
```

**2. Public tunnel** (URL must match `armoriq.yaml`)

```bash
cloudflared tunnel --url http://localhost:8001
```

If the tunnel URL changes, update `mcp_servers[0].url` and run `armoriq validate` + `armoriq register` again.

**3. API (port 8000)**

```bash
set -a && source .env && set +a
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**4. Frontend (Vite / TanStack)**

```bash
cd frontend
bun install   # or: npm install
bun run dev   # or: npm run dev
```

Open the Vite URL shown in the terminal (often [http://127.0.0.1:5173/](http://127.0.0.1:5173/) or [http://127.0.0.1:8080/](http://127.0.0.1:8080/)). The frontend proxies `/api` and `/health` to the FastAPI process on port 8000.

API-only root: [http://127.0.0.1:8000/](http://127.0.0.1:8000/) returns a short JSON pointer to the UI.

### Governed actions (ArmorIQ)

In the workspace **Governance** tab:

- **Run read action** (`circuit.get_component_status`) should show **ALLOWED** with sandbox component data.
- **Attempt placement** (`circuit.simulate_unverified_placement`) should show **BLOCKED** via `PolicyBlockedException`.

### Schematic analysis (read-only, not ArmorIQ)

Use **Open schematic** / drop a file, then **Analyze schematic**. Supported formats:

| Format | Extensions | What we confirm |
|--------|------------|-----------------|
| KiCad schematic | `.kicad_sch` | Symbols (reference/value/lib_id), labels, wire/junction counts, sheet hierarchy |
| PDF | `.pdf` | Page count and extractable text |
| Image | `.png`, `.jpg`, `.jpeg`, `.webp` | Format, dimensions, color mode |

Server checks: extension allowlist, MIME allowlist, size ≤ `CIRCUITSENTINEL_MAX_UPLOAD_MB` (default 20 MB). Filenames are replaced with UUIDs under `uploads/`. Files are served only via `GET /api/schematics/files/{file_id}` (32-hex UUID). Arbitrary filesystem paths are rejected.

## Schematic viewer

After analysis, the workspace shows a **split pane**: viewer on the left, findings on the right.

| Format | Rendering on this stack |
|--------|-------------------------|
| Image | Original file in the viewer (zoom / pan / fit) |
| PDF | Original PDF embedded in the browser |
| KiCad `.kicad_sch` | SVG via `kicad-cli sch export svg` when KiCad is installed; otherwise a clear **unavailable** fallback (no fake circuit drawing) |

Optional dependency for KiCad previews and **real ERC**:

```bash
# macOS: install KiCad, then confirm (PATH or app bundle):
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli version
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli sch erc --help
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli sch export svg --help
```

Or set `CIRCUITSENTINEL_KICAD_CLI` to that executable in `.env`.

Generated SVG previews (if any) live under `uploads/previews/` and are exposed only as `GET /api/schematics/files/{file_id}/preview`.

ERC runs on a **temporary copy** of the uploaded `.kicad_sch` (original is never modified). Findings are KiCad-reported facts (`rule_id`, severity, reference, pin, coordinates). If CLI is missing or ERC fails, `erc.ran` stays `false` with an explicit `failure_reason` — never treated as a clean pass.

KiCad SVG export uses a temporary working copy; the uploaded `.kicad_sch` is never modified. Highlight markers appear only when the SVG advertises millimetre `width`/`height` matching its `viewBox` (same units as ERC/`(at …)`). Otherwise the UI shows reference and coordinates without inventing a pin location.

## Analysis workflow

1. Choose or drop a schematic in the frontend (or `POST /api/schematics/analyze` with multipart field `file`).
2. The API stores the bytes, builds viewer metadata, and runs format-specific inspection.
3. The response separates honesty buckets:
   - **confirmed** — parser / text findings only
   - **erc** — KiCad ERC findings when `kicad-cli sch erc` actually ran (`ran`, `error_count`, `warning_count`, structured `findings`); otherwise an explicit failure reason
   - **visual** — image/PDF metadata with an explicit non-connectivity disclaimer
   - **unverified_suggestions** — empty in this milestone
   - **viewer** — `render_status` (`ready` / `unavailable` / `error`) and safe file URLs
4. Uploaded source files are never modified.

### Current limitations

- Visual inspection and PDF text do **not** establish electrical connectivity.
- ERC runs automatically for `.kicad_sch` when `kicad-cli` is available. CircuitSentinel does **not** auto-fix the schematic or claim the design is safe.
- Without KiCad CLI, `.kicad_sch` files can still be parsed, but the viewer shows an unavailable fallback instead of inventing a diagram.
- No OCR / vision model claims netlists from images or scanned PDFs.
- Design-changing operations remain behind ArmorIQ; analysis and viewing are intentionally separate.

Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health).

## Security tests (CLI)

```bash
set -a && source .env && set +a
python test_armoriq_policy.py
```

Expected: read-only pass, unverified placement blocked, `ALL SECURITY TESTS PASSED.`

## Unit / protocol tests

```bash
pytest
```

These cover Pydantic models, the MCP JSON-RPC SSE protocol, and schematic upload/analysis. They do not call ArmorIQ.

## Project layout

| Path | Role |
|------|------|
| `app/main.py` | Health + governed actions + schematic analyze/file API (CORS for Vite) |
| `app/policy_runtime.py` | Server-side ArmorIQ invoke helper |
| `app/schematics/` | Upload validation, storage, parsers, optional KiCad SVG render |
| `frontend/` | React / TanStack investigation workspace (proxies `/api` in dev) |
| `app/tools/circuit_mcp.py` | In-memory MCP on `POST /mcp` |
| `uploads/` | Local schematic uploads + previews (gitignored) |
| `armoriq.yaml` | Registered MCP + policy |
| `test_armoriq_policy.py` | End-to-end ArmorIQ allow/deny check |
| `tests/fixtures/schematics/` | Sample files for pytest |
