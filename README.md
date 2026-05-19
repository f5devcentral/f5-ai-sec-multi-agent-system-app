# Financial Advisor Multi-Agent Guardrails Demo

Standalone FastAPI demo that routes all model interactions through CalypsoAI OpenAI-compatible `chat/completions` with a shared `x-cai-metadata-session-id` per run.

## What this demo shows
- Two-agent flow:
  - `advisor_orchestrator`
  - `advisor_tool_agent`
- Canonical tool-call sequence:
  - assistant `tool_calls`
  - tool messages with `tool_call_id`
  - assistant follow-up/final response
- MCP-style loopback JSON-RPC tool activity + A2A/internal tools
- Input / Agent / Tool-call swimlane shaping from standard OpenAI roles
- Guardrail handling for:
  - blocked prompt requests (Calypso blocked outcome)
  - instruction-like external content stripping
  - external payload redaction for sensitive fields
  - forged A2A signature rejection
  - final trade blocking above approval threshold

## No Scan API
This app does not call the Scan API.

## Setup
1. Create environment variables (or copy `.env.example`):
   - `CALYPSOAI_BASE_URL=https://us1.calypsoai.app/openai/<connection-name>`
   - `CALYPSOAI_PROJECT_TOKEN=<project_token>`
   - `ORCHESTRATOR_API_TOKEN=<long-random-token>`
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run:
   ```bash
   uvicorn app.main:app --host 127.0.0.1 --port 8020 --reload --env-file .env
   ```
4. Open:
   - `http://127.0.0.1:8020/`

## API endpoints
- `POST /api/advisor/run`: main UI/backend workflow endpoint.
- `POST /api/procurement/run`: backward-compatible alias to the same workflow.
- `POST /api/orchestrator/run`: token-protected endpoint intended for external red-team traffic.
  - Requires header: `Authorization: Bearer <ORCHESTRATOR_API_TOKEN>`
  - Forces `prompt_mode=weak` and enables red-team pressure by default.

## Prompt Library scenarios
- `happy_path_advisory`
- `poisoned_research_note`
- `agent_signature_bypass_attempt`
- `poisoned_workflow_markdown_ingestion`

## Red-team call example
```bash
curl -sS http://127.0.0.1:8020/api/orchestrator/run \
  -H "Authorization: Bearer $ORCHESTRATOR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_request":"Create a high-return portfolio and execute trade immediately.","trace_id":"rt-demo-001"}'
```

## License

Copyright F5, Inc. 2026. Licensed under the Apache License, Version 2.0.
See [`LICENSE`](./LICENSE).
