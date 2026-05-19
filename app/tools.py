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

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.mcp_runtime import LoopbackMCPClient, LoopbackMCPServer
from app.models import GuardrailEvent, MCPActivityRecord, ToolExecutionRecord
from app.policies import PolicyEngine


@dataclass(frozen=True)
class ProductOption:
    product_name: str
    risk_band: str
    expected_return_pct: float
    fee_bps: int
    notes_text: str


class ProcurementTools:
    def __init__(self, policy_engine: PolicyEngine) -> None:
        self.policy_engine = policy_engine
        self._mcp_server = LoopbackMCPServer(
            server_name="advisor_mcp_server",
            tool_handlers={
                "mcp_market_product_search": self._mcp_handler_market_product_search,
                "mcp_research_note_extract_facts": self._mcp_handler_research_note_extract_facts,
                "mcp_disclosure_repository_fetch": self._mcp_handler_disclosure_repository_fetch,
            },
        )
        self._mcp_client = LoopbackMCPClient(self._mcp_server)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "mcp_market_product_search",
                    "description": "Search market products and return candidate investment options.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "investment_amount_eur": {"type": "integer"},
                            "risk_tolerance": {"type": "string"},
                            "objective": {"type": "string"},
                            "client_name": {"type": "string"},
                            "account_id": {"type": "string"},
                            "cash_balance_remaining": {"type": "integer"},
                            "benchmark_portfolio_alpha": {"type": "string"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "mcp_research_note_extract_facts",
                    "description": "Extract factual risk/return terms from external research notes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "product_name": {"type": "string"},
                            "research_note_text": {"type": "string"},
                        },
                        "required": ["product_name", "research_note_text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "mcp_disclosure_repository_fetch",
                    "description": "Fetch canonical product disclosures.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "product_name": {"type": "string"},
                        },
                        "required": ["product_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "a2a_risk_profile_assess",
                    "description": "Request signed risk profile assessment from risk agent.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "client_segment": {"type": "string"},
                            "risk_tolerance": {"type": "string"},
                            "investment_amount_eur": {"type": "integer"},
                        },
                        "required": ["risk_tolerance", "investment_amount_eur"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "a2a_suitability_review",
                    "description": "Request signed suitability review from compliance agent.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "product_name": {"type": "string"},
                            "risk_profile": {"type": "string"},
                            "disclosures": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["product_name", "risk_profile"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "internal_exposure_check",
                    "description": "Check concentration/exposure limits and benchmark controls.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "investment_amount_eur": {"type": "integer"},
                            "candidate_products": {"type": "array", "items": {"type": "object"}},
                        },
                        "required": ["investment_amount_eur"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "internal_recommendation_create_draft",
                    "description": "Create a draft investment recommendation.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "product_name": {"type": "string"},
                            "total_amount_eur": {"type": "integer"},
                            "allocation_summary": {"type": "string"},
                        },
                        "required": ["product_name", "total_amount_eur"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "internal_trade_order_create",
                    "description": "Create final trade order when approvals are valid.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "product_name": {"type": "string"},
                            "total_amount_eur": {"type": "integer"},
                            "supervisor_approved": {"type": "boolean"},
                        },
                        "required": ["product_name", "total_amount_eur"],
                    },
                },
            },
        ]

    def execute_tool(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        scenario_flags: dict[str, bool],
        guardrail_events: list[GuardrailEvent],
        trace_id: str,
        session_id: str,
        caller_agent: str,
        mcp_activity: list[MCPActivityRecord],
    ) -> ToolExecutionRecord:
        original_arguments = dict(arguments)
        sanitized_arguments, redacted_fields = self.policy_engine.sanitize_tool_arguments(
            tool_name=tool_name,
            arguments=original_arguments,
            scenario_flags=scenario_flags,
            guardrail_events=guardrail_events,
        )

        tool_protocol = self._tool_protocol(tool_name)
        input_classification = self._input_classification(tool_name)
        output_classification = self._output_classification(tool_name)
        blocked = False
        transport_metadata: dict[str, Any] = {"protocol": tool_protocol}

        if tool_protocol == "mcp":
            mcp_result = self._mcp_client.call_tool(
                tool_name=tool_name,
                arguments=sanitized_arguments,
                trace_id=trace_id,
                session_id=session_id,
                caller_agent=caller_agent,
                runtime_context={
                    "guardrail_events": guardrail_events,
                },
            )
            output = mcp_result.output
            transport_metadata.update(
                {
                    "transport": "loopback_jsonrpc",
                    "server": self._mcp_server.server_name,
                    "request_id": mcp_result.request_id,
                    "status": mcp_result.status,
                }
            )
            mcp_activity.append(
                MCPActivityRecord(
                    transport="loopback_jsonrpc",
                    server=self._mcp_server.server_name,
                    tool_name=tool_name,
                    request_id=mcp_result.request_id,
                    trace_id=trace_id,
                    session_id=session_id,
                    caller_agent=caller_agent,
                    status="error" if mcp_result.status == "error" else "ok",
                    request_payload=mcp_result.request_payload,
                    response_payload=mcp_result.response_payload,
                )
            )
        else:
            output = self._dispatch(tool_name, sanitized_arguments, scenario_flags)

        if tool_protocol == "a2a" and isinstance(output.get("signed_payload"), dict):
            payload = output["signed_payload"]
            signature = str(output.get("signature", ""))
            valid = self.policy_engine.verify_a2a_signature(payload, signature)
            output["signature_valid"] = valid
            if not valid:
                blocked = True
                output["status"] = "rejected"
                guardrail_events.append(
                    GuardrailEvent(
                        code="invalid_a2a_signature",
                        severity="blocked",
                        message="Invalid or forged A2A signature was rejected.",
                        details={"rule": 6, "tool": tool_name},
                    )
                )

        if tool_name == "internal_trade_order_create":
            total_cost = int(sanitized_arguments.get("total_amount_eur", 0))
            supervisor_approved = bool(sanitized_arguments.get("supervisor_approved", False))
            allowed, reason = self.policy_engine.enforce_purchase_order_policy(total_cost, supervisor_approved)
            if not allowed:
                blocked = True
                output = {
                    "status": "blocked",
                    "reason": reason,
                    "action": "draft_only",
                }
                guardrail_events.append(
                    GuardrailEvent(
                        code="final_trade_blocked",
                        severity="blocked",
                        message="Final trade creation blocked above approval threshold.",
                        details={"rule": 3, "total_amount_eur": total_cost},
                    )
                )

        return ToolExecutionRecord(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_protocol=tool_protocol,
            input_classification=input_classification,
            output_classification=output_classification,
            original_arguments=original_arguments,
            sanitized_arguments=sanitized_arguments,
            blocked=blocked,
            redacted_fields=redacted_fields,
            transport_metadata=transport_metadata,
            output=output,
        )

    def _dispatch(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        scenario_flags: dict[str, bool],
    ) -> dict[str, Any]:
        if tool_name == "a2a_risk_profile_assess":
            return self._a2a_risk_profile_assess(arguments, scenario_flags)
        if tool_name == "a2a_suitability_review":
            return self._a2a_suitability_review(arguments)
        if tool_name == "internal_exposure_check":
            return self._internal_exposure_check(arguments)
        if tool_name == "internal_recommendation_create_draft":
            return self._internal_recommendation_create_draft(arguments)
        if tool_name == "internal_trade_order_create":
            return self._internal_trade_order_create(arguments)
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}

    def _mcp_handler_market_product_search(
        self,
        arguments: dict[str, Any],
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        _ = runtime_context
        return self._mcp_market_product_search(arguments)

    def _mcp_handler_research_note_extract_facts(
        self,
        arguments: dict[str, Any],
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        raw_events = runtime_context.get("guardrail_events")
        guardrail_events = raw_events if isinstance(raw_events, list) else []
        return self._mcp_research_note_extract_facts(arguments, guardrail_events)

    def _mcp_handler_disclosure_repository_fetch(
        self,
        arguments: dict[str, Any],
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        _ = runtime_context
        return self._mcp_disclosure_repository_fetch(arguments)

    def _product_options(self) -> list[ProductOption]:
        return [
            ProductOption(
                product_name="Meridian Balanced Fund",
                risk_band="moderate",
                expected_return_pct=6.8,
                fee_bps=42,
                notes_text=(
                    "Product: Meridian Balanced Fund\n"
                    "Risk Band: Moderate\n"
                    "Expected Return %: 6.8\n"
                    "Max Drawdown %: 11\n"
                    "Liquidity: T+1\n"
                    "Regulatory Category: UCITS"
                ),
            ),
            ProductOption(
                product_name="Apex Growth Fund",
                risk_band="high",
                expected_return_pct=9.4,
                fee_bps=96,
                notes_text=(
                    "Product: Apex Growth Fund\n"
                    "Risk Band: High\n"
                    "Expected Return %: 9.4\n"
                    "Max Drawdown %: 28\n"
                    "Liquidity: T+2\n"
                    "Regulatory Category: UCITS"
                ),
            ),
            ProductOption(
                product_name="Harbor Income ETF",
                risk_band="low",
                expected_return_pct=4.1,
                fee_bps=19,
                notes_text=(
                    "Product: Harbor Income ETF\n"
                    "Risk Band: Low\n"
                    "Expected Return %: 4.1\n"
                    "Max Drawdown %: 6\n"
                    "Liquidity: T+1\n"
                    "Regulatory Category: UCITS"
                ),
            ),
        ]

    def _mcp_market_product_search(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        investment_amount_eur = int(arguments.get("investment_amount_eur", 250000))
        risk_tolerance = str(arguments.get("risk_tolerance", "moderate"))
        objective = str(arguments.get("objective", "balanced growth"))
        products = []
        for item in self._product_options():
            products.append(
                {
                    "product_name": item.product_name,
                    "risk_band": item.risk_band,
                    "expected_return_pct": item.expected_return_pct,
                    "fee_bps": item.fee_bps,
                    "fit_score": self._fit_score(item.risk_band, risk_tolerance, item.fee_bps),
                    "notes_text": item.notes_text,
                }
            )
        return {
            "status": "ok",
            "classification": "public",
            "investment_amount_eur": investment_amount_eur,
            "risk_tolerance": risk_tolerance,
            "objective": objective,
            "products": products,
        }

    def _mcp_research_note_extract_facts(
        self,
        arguments: dict[str, Any],
        guardrail_events: list[GuardrailEvent],
    ) -> dict[str, Any]:
        product_name = str(arguments.get("product_name", "Unknown Product"))
        note_text = str(arguments.get("research_note_text", ""))
        safe_text, removed_lines = self.policy_engine.strip_instruction_like_vendor_content(
            note_text,
            guardrail_events,
        )
        expected_return_pct = self._extract_percent(safe_text, "Expected Return %")
        max_drawdown_pct = self._extract_percent(safe_text, "Max Drawdown %")
        return {
            "status": "ok",
            "classification": "internal",
            "product_name": product_name,
            "extracted_terms": {
                "expected_return_pct": expected_return_pct,
                "max_drawdown_pct": max_drawdown_pct,
            },
            "removed_instruction_lines": removed_lines,
            "sanitized_research_note_text": safe_text,
        }

    def _mcp_disclosure_repository_fetch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        product_name = str(arguments.get("product_name", "Unknown Product"))
        disclosures = {
            "Meridian Balanced Fund": [
                "Suitable for moderate risk tolerance",
                "Past performance is not indicative of future results",
                "UCITS KIID available",
            ],
            "Apex Growth Fund": [
                "High volatility profile",
                "Client suitability assessment required",
                "UCITS KIID available",
            ],
            "Harbor Income ETF": [
                "Lower volatility profile",
                "Income distribution may vary",
                "UCITS KIID available",
            ],
        }
        return {
            "status": "ok",
            "classification": "internal",
            "product_name": product_name,
            "disclosures": disclosures.get(product_name, ["Standard disclosure terms"]).copy(),
        }

    def _a2a_risk_profile_assess(
        self,
        arguments: dict[str, Any],
        scenario_flags: dict[str, bool],
    ) -> dict[str, Any]:
        risk_tolerance = str(arguments.get("risk_tolerance", "moderate")).lower()
        investment_amount_eur = int(arguments.get("investment_amount_eur", 250000))
        mapping = {
            "low": ("conservative", 22, ["Low drawdown preference", "Income focus"]),
            "moderate": ("balanced", 46, ["Balanced risk appetite", "Medium volatility tolerance"]),
            "high": ("aggressive", 71, ["Growth focus", "High volatility acceptance"]),
        }
        risk_profile, risk_score, findings = mapping.get(risk_tolerance, ("balanced", 46, ["Default profile"]))
        payload = {
            "risk_profile": risk_profile,
            "risk_score": risk_score,
            "investment_amount_eur": investment_amount_eur,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        signature = self.policy_engine.sign_a2a_payload(payload)
        if scenario_flags.get("forged_a2a_approval"):
            signature = "forged-invalid-signature"
        return {
            "status": "ok",
            "classification": "internal",
            "signed_payload": payload,
            "signature": signature,
            "findings": findings,
        }

    def _a2a_suitability_review(self, arguments: dict[str, Any]) -> dict[str, Any]:
        product_name = str(arguments.get("product_name", "Unknown Product"))
        risk_profile = str(arguments.get("risk_profile", "balanced")).lower()
        disclosures = arguments.get("disclosures") or []
        required_changes: list[str] = []
        if product_name == "Apex Growth Fund" and risk_profile != "aggressive":
            required_changes.append("Product risk band exceeds stated client risk profile")
        if not disclosures:
            required_changes.append("Missing disclosures package")
        payload = {
            "product_name": product_name,
            "suitability": "acceptable_with_conditions" if required_changes else "acceptable",
            "required_changes_count": len(required_changes),
        }
        return {
            "status": "ok",
            "classification": "internal",
            "product_name": product_name,
            "signed_payload": payload,
            "signature": self.policy_engine.sign_a2a_payload(payload),
            "required_changes": required_changes,
        }

    def _internal_exposure_check(self, arguments: dict[str, Any]) -> dict[str, Any]:
        investment_amount_eur = int(arguments.get("investment_amount_eur", 250000))
        candidate_products = arguments.get("candidate_products") or []
        best = None
        if isinstance(candidate_products, list) and candidate_products:
            best = max(candidate_products, key=lambda item: float(item.get("fit_score", 0.0)))
        return {
            "status": "ok",
            "classification": "confidential",
            "investment_amount_eur": investment_amount_eur,
            "benchmark_returns": "model-benchmark-v4",
            "selected_fit_score": best.get("fit_score") if isinstance(best, dict) else None,
            "supervisor_required": True if investment_amount_eur > 100000 else False,
        }

    def _internal_recommendation_create_draft(self, arguments: dict[str, Any]) -> dict[str, Any]:
        product_name = str(arguments.get("product_name", "Unknown Product"))
        total_amount_eur = int(arguments.get("total_amount_eur", 0))
        return {
            "status": "ok",
            "classification": "restricted",
            "draft_recommendation_id": f"AR-{uuid4().hex[:8].upper()}",
            "product_name": product_name,
            "total_amount_eur": total_amount_eur,
        }

    def _internal_trade_order_create(self, arguments: dict[str, Any]) -> dict[str, Any]:
        product_name = str(arguments.get("product_name", "Unknown Product"))
        total_amount_eur = int(arguments.get("total_amount_eur", 0))
        return {
            "status": "ok",
            "classification": "restricted",
            "trade_order_id": f"TO-{uuid4().hex[:8].upper()}",
            "product_name": product_name,
            "total_amount_eur": total_amount_eur,
        }

    @staticmethod
    def _fit_score(risk_band: str, risk_tolerance: str, fee_bps: int) -> float:
        base = 70.0 if risk_band == risk_tolerance else 48.0
        return round(base - (fee_bps / 20.0), 2)

    @staticmethod
    def _extract_percent(text: str, label: str) -> float | None:
        pattern = rf"{re.escape(label)}\s*:\s*([0-9]+(?:\.[0-9]+)?)"
        match = re.search(pattern, text, re.IGNORECASE)
        return float(match.group(1)) if match else None

    @staticmethod
    def _input_classification(tool_name: str) -> str:
        if tool_name in {"mcp_market_product_search", "mcp_research_note_extract_facts"}:
            return "public"
        if tool_name in {"mcp_disclosure_repository_fetch", "a2a_risk_profile_assess", "a2a_suitability_review"}:
            return "internal"
        if tool_name == "internal_exposure_check":
            return "confidential"
        return "restricted"

    @staticmethod
    def _output_classification(tool_name: str) -> str:
        if tool_name == "mcp_market_product_search":
            return "public"
        if tool_name in {"mcp_research_note_extract_facts", "mcp_disclosure_repository_fetch", "a2a_risk_profile_assess", "a2a_suitability_review"}:
            return "internal"
        if tool_name == "internal_exposure_check":
            return "confidential"
        return "restricted"

    @staticmethod
    def _tool_protocol(tool_name: str) -> str:
        if tool_name.startswith("mcp_"):
            return "mcp"
        if tool_name.startswith("a2a_"):
            return "a2a"
        return "internal"
