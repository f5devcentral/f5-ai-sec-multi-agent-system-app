# Copyright F5, Inc. 2026
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.models import ProcurementRunRequest, ProcurementRunResponse, ScenarioRunResponse
from app.workflow import ProcurementWorkflowService

app = FastAPI(title=settings.app_name, version="0.1.0")
ui_root = Path(__file__).resolve().parent / "ui"
app.mount("/ui-static", StaticFiles(directory=ui_root / "static"), name="ui-static")


def _sse_encode(event_name: str, payload: dict[str, Any]) -> bytes:
    return f"event: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n".encode("utf-8")


@app.on_event("startup")
async def startup_event() -> None:
    app.state.workflow = ProcurementWorkflowService()


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    return FileResponse(ui_root / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/scenarios")
async def list_demo_scenarios() -> list[dict]:
    workflow: ProcurementWorkflowService = app.state.workflow
    return [scenario.model_dump(mode="json") for scenario in workflow.list_scenarios()]


@app.post("/api/procurement/run", response_model=ProcurementRunResponse)
async def run_procurement(payload: ProcurementRunRequest) -> ProcurementRunResponse:
    workflow: ProcurementWorkflowService = app.state.workflow
    try:
        return await workflow.run(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/advisor/run", response_model=ProcurementRunResponse)
async def run_advisor(payload: ProcurementRunRequest) -> ProcurementRunResponse:
    workflow: ProcurementWorkflowService = app.state.workflow
    try:
        return await workflow.run(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/advisor/run/stream")
async def run_advisor_stream(payload: ProcurementRunRequest) -> StreamingResponse:
    workflow: ProcurementWorkflowService = app.state.workflow
    event_queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

    async def on_progress(event: dict[str, Any]) -> None:
        await event_queue.put(("progress", event))

    async def worker() -> None:
        try:
            result = await workflow.run(payload, progress_callback=on_progress)
            await event_queue.put(("result", result.model_dump(mode="json")))
        except Exception as exc:  # noqa: BLE001
            await event_queue.put(("error", {"message": str(exc)}))
        finally:
            await event_queue.put(None)

    async def event_stream():
        worker_task = asyncio.create_task(worker())
        try:
            while True:
                item = await event_queue.get()
                if item is None:
                    break
                event_name, data = item
                yield _sse_encode(event_name, data)
        finally:
            if not worker_task.done():
                worker_task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/orchestrator/run", response_model=ProcurementRunResponse)
async def run_orchestrator_api(
    payload: ProcurementRunRequest,
    authorization: str | None = Header(default=None),
) -> ProcurementRunResponse:
    token = settings.orchestrator_api_token
    if not token:
        raise HTTPException(status_code=503, detail="ORCHESTRATOR_API_TOKEN is not configured.")
    if not authorization or authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Unauthorized.")

    workflow: ProcurementWorkflowService = app.state.workflow
    run_payload = payload.model_copy(deep=True)
    run_payload.prompt_mode = "weak"
    run_payload.red_team_mode = True if payload.red_team_mode is False else payload.red_team_mode
    try:
        return await workflow.run(run_payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/scenarios/{scenario_id}/run", response_model=ScenarioRunResponse)
async def run_scenario(scenario_id: str) -> ScenarioRunResponse:
    workflow: ProcurementWorkflowService = app.state.workflow
    try:
        return await workflow.run_scenario(scenario_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
