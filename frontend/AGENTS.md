<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

- CircuitSentinel’s React workspace talks to the FastAPI backend via relative `/api/*` routes (Vite proxies them to `http://127.0.0.1:8000` in local dev).
- Never invent ERC findings, hardcode metrics, or claim a circuit is safe. Bind summary metrics and findings to the analyze API response.
- Keep KiCad-reported facts visually separate from AI / unverified suggestions.
- Secrets and MCP bearer tokens stay on the server; the browser never calls MCP directly.
