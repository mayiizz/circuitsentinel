# CircuitSentinel frontend

## Goal
Build a polished, responsive circuit-analysis workspace from the supplied PRD, rather than a marketing page or debugging panel.

## Experience
- Put the upload-ready schematic viewer and finding review at the center of a full-width dark engineering workspace.
- Add responsive summary, findings, extracted-structure, analysis-limitations, and policy-governance views.
- Support selecting KiCad, PDF, and common image files up to 20 MB; preview PDFs and images locally, and show honest unavailable states where no analysis or rendering service is connected.
- Keep actual ERC evidence, AI interpretations, and policy outcomes distinct. Never fabricate a circuit, finding, analysis metric, or governance result.

## Technical approach
- Replace the `/` template with a single interactive React workspace, using the existing Button, Tabs, semantic design tokens, and lucide-react icons.
- Set app-specific route metadata and replace inherited template branding.
- Keep this frontend-only: no new backend, package, or claimed KiCad/ArmorIQ integration where none exists in this project.
- Validate upload limits, core interactions, responsive rendering, and project build signals.
