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

from typing import Any, Literal

from pydantic import BaseModel, Field


Classification = Literal["public", "internal", "confidential", "restricted"]
GuardrailStatus = Literal["clear", "flagged", "blocked", "unknown"]


class ScenarioDefinition(BaseModel):
    scenario_id: str
    title: str
    description: str
    user_request: str
    tool_focus_hint: str | None = None


class ProcurementRunRequest(BaseModel):
    user_request: str | None = None
    scenario_id: str | None = None
    trace_id: str | None = None
    prompt_mode: Literal["strong", "weak"] = "strong"
    red_team_mode: bool = False


class GuardrailEvent(BaseModel):
    code: str
    severity: Literal["info", "warning", "blocked"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionRecord(BaseModel):
    tool_call_id: str
    tool_name: str
    tool_protocol: Literal["mcp", "a2a", "internal"]
    input_classification: Classification
    output_classification: Classification
    original_arguments: dict[str, Any]
    sanitized_arguments: dict[str, Any]
    blocked: bool = False
    redacted_fields: list[str] = Field(default_factory=list)
    transport_metadata: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)


class MCPActivityRecord(BaseModel):
    protocol: Literal["mcp"] = "mcp"
    transport: str
    server: str
    tool_name: str
    request_id: str
    trace_id: str
    session_id: str
    caller_agent: str
    status: Literal["ok", "error"]
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]


class ModelInteraction(BaseModel):
    agent_name: str
    messages: list[dict[str, Any]]
    response_message: dict[str, Any]


class ProcurementRunResponse(BaseModel):
    trace_id: str
    scenario_id: str | None = None
    prompt_mode: Literal["strong", "weak"] = "strong"
    red_team_mode: bool = False
    user_request: str
    generated_plan: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    tool_results: list[ToolExecutionRecord]
    blocked_or_redacted_events: list[GuardrailEvent]
    final_answer: str
    recommendation: dict[str, Any]
    model_interactions: list[ModelInteraction]
    mcp_activity: list[MCPActivityRecord] = Field(default_factory=list)
    guardrail_status: GuardrailStatus = "unknown"


class ScenarioRunResponse(BaseModel):
    scenario_id: str
    title: str
    description: str
    result: ProcurementRunResponse
