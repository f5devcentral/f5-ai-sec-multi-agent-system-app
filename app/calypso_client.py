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

import json
from dataclasses import dataclass
from typing import Any

from app.config import settings

try:
    from openai import OpenAI
except Exception:  # noqa: BLE001
    OpenAI = None  # type: ignore[assignment]


class CalypsoChatError(RuntimeError):
    pass


@dataclass(frozen=True)
class CalypsoGuardrailResult:
    outcome: str
    scanner_results: list[dict[str, Any]]
    message: str | None = None
    response: Any | None = None
    analysis: Any | None = None


class CalypsoGuardrailBlockedError(CalypsoChatError):
    def __init__(
        self,
        *,
        agent_name: str,
        trace_id: str,
        status_code: int | None,
        result: CalypsoGuardrailResult,
        raw_error: dict[str, Any] | None,
    ) -> None:
        super().__init__(result.message or "Calypso guardrails blocked the prompt")
        self.agent_name = agent_name
        self.trace_id = trace_id
        self.status_code = status_code
        self.result = result
        self.raw_error = raw_error or {}


class CalypsoChatClient:
    def __init__(self) -> None:
        self._token = settings.calypsoai_project_token
        self._mock_mode = settings.allow_mock_llm and not self._token
        self._counter = 0

        self._client: OpenAI | None = None
        if not self._mock_mode:
            if "CONNECTION-NAME" in settings.calypsoai_base_url:
                raise CalypsoChatError(
                    "CALYPSOAI_BASE_URL is still using placeholder CONNECTION-NAME. "
                    "Set CALYPSOAI_BASE_URL=https://us1.calypsoai.app/openai/<your-connection-name>."
                )
            if OpenAI is None:
                raise CalypsoChatError("openai package is not installed")
            if not self._token:
                raise CalypsoChatError(
                    "Missing CALYPSOAI_PROJECT_TOKEN (or OPENAI_API_KEY). "
                    "Set ALLOW_MOCK_LLM=true for offline mode."
                )
            self._client = OpenAI(base_url=settings.calypsoai_base_url, api_key=self._token)

    @property
    def base_url(self) -> str:
        return settings.calypsoai_base_url

    @property
    def model(self) -> str:
        return settings.openai_model

    def complete(
        self,
        *,
        agent_name: str,
        trace_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._mock_mode:
            response = self._mock_complete(
                agent_name=agent_name,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
            )
            response["_meta"] = {
                "agent_name": agent_name,
                "trace_id": trace_id,
                "completion_id": f"mock_{self._counter}",
                "model": settings.openai_model,
                "mock_mode": True,
                "guardrail_outcome": "clear",
            }
            return response

        if not self._client:
            raise CalypsoChatError("Calypso OpenAI client is not initialized")

        request: dict[str, Any] = {
            "model": settings.openai_model,
            "messages": messages,
            "temperature": settings.openai_temperature,
        }
        if tools:
            request["tools"] = tools
        if tool_choice:
            request["tool_choice"] = tool_choice
        if response_format:
            request["response_format"] = response_format

        try:
            completion = self._client.chat.completions.create(
                **request,
                extra_headers={"x-cai-metadata-session-id": trace_id},
            )
        except Exception as exc:  # noqa: BLE001
            parsed = self._extract_guardrail_result_from_exception(exc)
            if parsed and parsed.outcome == "blocked":
                raise CalypsoGuardrailBlockedError(
                    agent_name=agent_name,
                    trace_id=trace_id,
                    status_code=getattr(exc, "status_code", None),
                    result=parsed,
                    raw_error=self._extract_error_payload(exc),
                ) from exc
            raise

        return self._assistant_message_to_dict(
            completion=completion,
            agent_name=agent_name,
            trace_id=trace_id,
        )

    def _assistant_message_to_dict(
        self,
        *,
        completion: Any,
        agent_name: str,
        trace_id: str,
    ) -> dict[str, Any]:
        message = completion.choices[0].message
        guardrail_outcome = self._extract_guardrail_outcome_from_completion(completion)
        payload: dict[str, Any] = {
            "role": "assistant",
            "content": getattr(message, "content", None),
            "_meta": {
                "agent_name": agent_name,
                "trace_id": trace_id,
                "completion_id": str(getattr(completion, "id", "") or ""),
                "model": str(getattr(completion, "model", "") or ""),
                "created": getattr(completion, "created", None),
                "mock_mode": False,
                "guardrail_outcome": guardrail_outcome,
            },
        }
        raw_tool_calls = list(getattr(message, "tool_calls", []) or [])
        if raw_tool_calls:
            payload["tool_calls"] = [
                {
                    "id": str(getattr(call, "id", "") or ""),
                    "type": "function",
                    "function": {
                        "name": str(getattr(getattr(call, "function", None), "name", "") or ""),
                        "arguments": str(
                            getattr(getattr(call, "function", None), "arguments", "") or "{}"
                        ),
                    },
                }
                for call in raw_tool_calls
            ]
        return payload

    def _mock_complete(
        self,
        *,
        agent_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_choice: dict[str, Any] | str | None,
    ) -> dict[str, Any]:
        self._counter += 1

        if tools and isinstance(tool_choice, dict):
            forced_name = str((tool_choice.get("function") or {}).get("name") or "")
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_mock_{self._counter}",
                        "type": "function",
                        "function": {
                            "name": forced_name,
                            "arguments": json.dumps(self._default_mock_tool_args(forced_name)),
                        },
                    }
                ],
            }

        if agent_name == "advisor_orchestrator":
            raw_user_content = self._last_user_content(messages)
            if self._is_mock_out_of_scope(raw_user_content):
                return {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "route": "out_of_scope",
                            "plan_summary": "Request is outside advisory workflow scope.",
                            "steps": [],
                            "decision_notes": [
                                "No financial advisory specialist agents required for this request."
                            ],
                            "out_of_scope_response": (
                                "I am a financial advisory assistant for product comparison, research note analysis, "
                                "risk profile checks, suitability review, and draft recommendation preparation."
                            ),
                        }
                    ),
                }

            content = json.dumps(
                {
                    "route": "advisor_workflow",
                    "plan_summary": (
                        "Collect market options, extract research terms, assess risk/suitability, "
                        "run internal exposure checks, and produce draft recommendation."
                    ),
                    "steps": [
                        {
                            "step_id": "s1",
                            "objective": "Gather market products",
                            "tool_candidates": ["mcp_market_product_search"],
                            "required": True,
                        },
                        {
                            "step_id": "s2",
                            "objective": "Extract research note facts",
                            "tool_candidates": ["mcp_research_note_extract_facts"],
                            "required": True,
                        },
                        {
                            "step_id": "s3",
                            "objective": "Fetch disclosures and review suitability",
                            "tool_candidates": ["mcp_disclosure_repository_fetch", "a2a_suitability_review"],
                            "required": True,
                        },
                        {
                            "step_id": "s4",
                            "objective": "Assess client risk profile",
                            "tool_candidates": ["a2a_risk_profile_assess"],
                            "required": True,
                        },
                        {
                            "step_id": "s5",
                            "objective": "Check exposure and create draft recommendation",
                            "tool_candidates": ["internal_exposure_check", "internal_recommendation_create_draft"],
                            "required": True,
                        },
                    ],
                    "decision_notes": ["Avoid final trade above approval threshold unless supervisor approved."],
                }
            )
            return {"role": "assistant", "content": content}

        if agent_name == "advisor_final_response_agent":
            request_payload = self._parse_last_user_json(messages)
            recommendation = request_payload.get("recommendation_payload") or {}
            action_taken = recommendation.get("action_taken") or []
            return {
                "role": "assistant",
                "content": (
                    f"Recommended strategy: {recommendation.get('recommended_product', 'Meridian Balanced Fund')}\n\n"
                    f"Allocation summary: {recommendation.get('allocation_summary', 'N/A')}\n"
                    f"Risk summary: {recommendation.get('risk_summary', 'N/A')}\n"
                    f"Compliance review summary: {recommendation.get('compliance_review_summary', 'N/A')}\n"
                    f"Approval requirement: {recommendation.get('approval_requirement', 'N/A')}\n"
                    f"Action taken: {' '.join(action_taken) if action_taken else 'None'}"
                ),
            }

        return {"role": "assistant", "content": "Acknowledged."}

    @staticmethod
    def _default_mock_tool_args(tool_name: str) -> dict[str, Any]:
        if tool_name == "mcp_market_product_search":
            return {
                "investment_amount_eur": 250000,
                "risk_tolerance": "moderate",
                "objective": "balanced growth",
            }
        if tool_name == "mcp_research_note_extract_facts":
            return {
                "product_name": "Meridian Balanced Fund",
                "research_note_text": (
                    "Product: Meridian Balanced Fund\\nRisk Band: Moderate\\n"
                    "Expected Return %: 6.8\\nMax Drawdown %: 11"
                ),
            }
        if tool_name == "mcp_disclosure_repository_fetch":
            return {"product_name": "Meridian Balanced Fund"}
        if tool_name == "a2a_risk_profile_assess":
            return {"risk_tolerance": "moderate", "investment_amount_eur": 250000}
        if tool_name == "a2a_suitability_review":
            return {
                "product_name": "Meridian Balanced Fund",
                "risk_profile": "balanced",
                "disclosures": ["UCITS KIID available"],
            }
        if tool_name == "internal_exposure_check":
            return {"investment_amount_eur": 250000, "candidate_products": []}
        if tool_name == "internal_recommendation_create_draft":
            return {"product_name": "Meridian Balanced Fund", "total_amount_eur": 250000}
        if tool_name == "internal_trade_order_create":
            return {"product_name": "Meridian Balanced Fund", "total_amount_eur": 250000, "supervisor_approved": False}
        return {}

    @staticmethod
    def _extract_error_payload(exc: Exception) -> dict[str, Any]:
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            return body
        if isinstance(body, str):
            try:
                parsed = json.loads(body)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @classmethod
    def _extract_guardrail_result_from_exception(
        cls,
        exc: Exception,
    ) -> CalypsoGuardrailResult | None:
        payload = cls._extract_error_payload(exc)
        return cls._extract_guardrail_result_from_payload(payload)

    @staticmethod
    def _extract_guardrail_result_from_payload(payload: dict[str, Any]) -> CalypsoGuardrailResult | None:
        if not isinstance(payload, dict):
            return None

        error_node = payload.get("error") if isinstance(payload.get("error"), dict) else payload
        if not isinstance(error_node, dict):
            return None

        cai_error = error_node.get("cai_error")
        if not isinstance(cai_error, dict):
            return None

        outcome = str(cai_error.get("outcome") or "").strip().lower()
        if outcome not in {"blocked", "flagged", "redacted", "cleared", "clear"}:
            return None

        scanner_results = cai_error.get("scanner_results")
        normalized_results = (
            scanner_results
            if isinstance(scanner_results, list)
            else cai_error.get("scannerResults")
            if isinstance(cai_error.get("scannerResults"), list)
            else []
        )
        scanner_list: list[dict[str, Any]] = []
        for item in normalized_results:
            if isinstance(item, dict):
                scanner_list.append(item)

        return CalypsoGuardrailResult(
            outcome=outcome,
            scanner_results=scanner_list,
            message=str(error_node.get("message") or ""),
            analysis=cai_error.get("analysis"),
            response=cai_error.get("response"),
        )

    @classmethod
    def _extract_guardrail_outcome_from_completion(cls, completion: Any) -> str | None:
        outcome = cls._extract_guardrail_outcome_from_node(getattr(completion, "model_extra", None))
        if outcome:
            return outcome
        try:
            dumped = completion.model_dump(mode="python")
        except Exception:  # noqa: BLE001
            dumped = None
        outcome = cls._extract_guardrail_outcome_from_node(dumped)
        if outcome:
            return outcome
        message = completion.choices[0].message if getattr(completion, "choices", None) else None
        return cls._extract_guardrail_outcome_from_node(getattr(message, "model_extra", None))

    @classmethod
    def _extract_guardrail_outcome_from_node(cls, node: Any) -> str | None:
        if not isinstance(node, dict):
            return None

        parsed = cls._extract_guardrail_result_from_payload(node)
        if parsed:
            return parsed.outcome

        keys = ("cai_error", "guardrails", "guardrail", "cai", "metadata", "_meta")
        for key in keys:
            child = node.get(key)
            if not isinstance(child, dict):
                continue
            outcome = str(child.get("outcome") or "").strip().lower()
            if outcome in {"blocked", "flagged", "redacted", "cleared", "clear"}:
                return outcome
            nested = cls._extract_guardrail_outcome_from_node(child)
            if nested:
                return nested
        return None

    @staticmethod
    def _last_user_content(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if str(message.get("role")) == "user":
                return str(message.get("content") or "")
        return ""

    @staticmethod
    def _parse_last_user_json(messages: list[dict[str, Any]]) -> dict[str, Any]:
        raw = CalypsoChatClient._last_user_content(messages).strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _is_mock_out_of_scope(raw_user_content: str) -> bool:
        payload = {}
        try:
            parsed = json.loads(raw_user_content)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            pass

        request_text = str(payload.get("request") or raw_user_content).lower()
        advisory_markers = {
            "portfolio",
            "investment",
            "advisor",
            "allocation",
            "trade",
            "fund",
            "etf",
            "suitability",
            "returns",
            "risk",
            "client",
        }
        return not any(marker in request_text for marker in advisory_markers)
