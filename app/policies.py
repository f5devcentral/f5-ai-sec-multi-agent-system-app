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

import hmac
import re
from hashlib import sha256
from typing import Any

from app.models import SecurityEvent


class PolicyEngine:
    external_tools = {
        "mcp_market_product_search",
        "mcp_research_note_extract_facts",
        "a2a_risk_profile_assess",
        "a2a_suitability_review",
    }

    sensitive_external_fields = {
        "client_name",
        "client_names",
        "account_id",
        "account_ids",
        "cash_balance_remaining",
        "benchmark_portfolio_alpha",
        "benchmark_returns",
        "cross_client_positions",
        "cross_desk_positions",
    }

    def __init__(self, a2a_signing_secret: str = "advisor-demo-a2a-secret") -> None:
        self._a2a_signing_secret = a2a_signing_secret

    def rewrite_user_request(
        self,
        user_request: str,
        scenario_flags: dict[str, bool],
        control_events: list[SecurityEvent],
    ) -> str:
        rewritten = user_request
        lowered = user_request.lower()

        bypass_markers = [
            "ignore policy",
            "bypass",
            "mark it as already approved",
            "already approved",
            "skip approval",
            "create the trade directly",
        ]
        if any(marker in lowered for marker in bypass_markers):
            control_events.append(
                SecurityEvent(
                    code="policy_bypass_blocked",
                    severity="blocked",
                    message="User request to bypass policy was blocked and rewritten.",
                    details={"rule": 7},
                )
            )
            rewritten = re.sub(r"(?i)mark it as already approved", "follow approval policy", rewritten)
            rewritten = re.sub(r"(?i)ignore policy", "apply policy", rewritten)

        if scenario_flags.get("cross_department_pricing_access") or (
            "wealth" in lowered and "institutional" in lowered and "pricing" in lowered
        ):
            control_events.append(
                SecurityEvent(
                    code="cross_department_pricing_blocked",
                    severity="blocked",
                    message="Cross-desk pricing access was blocked without explicit authorization.",
                    details={"rule": 2},
                )
            )
            rewritten += "\n\nNote: Do not use another desk's private pricing in this workflow."

        return rewritten

    def sanitize_tool_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        scenario_flags: dict[str, bool],
        control_events: list[SecurityEvent],
    ) -> tuple[dict[str, Any], list[str]]:
        incoming = dict(arguments)
        if scenario_flags.get("vulnerable_app"):
            return incoming, []

        if scenario_flags.get("overscoped_external_tool_call") and tool_name in self.external_tools:
            incoming.setdefault("client_names", ["Client-A", "Client-B"])
            incoming.setdefault("cash_balance_remaining", 14000)
            incoming.setdefault("benchmark_portfolio_alpha", "strategy-7.2")

        redacted_fields: list[str] = []
        sanitized: dict[str, Any] = {}

        for key, value in incoming.items():
            if tool_name in self.external_tools and key in self.sensitive_external_fields:
                redacted_fields.append(key)
                continue
            sanitized[key] = value

        if redacted_fields:
            control_events.append(
                SecurityEvent(
                    code="external_payload_redacted",
                    severity="blocked",
                    message="Sensitive internal fields were blocked from external tool payload.",
                    details={"rule": 1, "tool": tool_name, "fields": redacted_fields},
                )
            )

        return sanitized, redacted_fields

    def sign_a2a_payload(self, payload: dict[str, Any]) -> str:
        msg = self._payload_to_bytes(payload)
        return hmac.new(self._a2a_signing_secret.encode("utf-8"), msg, sha256).hexdigest()

    def verify_a2a_signature(self, payload: dict[str, Any], signature: str) -> bool:
        expected = self.sign_a2a_payload(payload)
        return hmac.compare_digest(expected, signature)

    def enforce_purchase_order_policy(self, total_cost_eur: int, vp_finance_approved: bool) -> tuple[bool, str]:
        if total_cost_eur > 100000 and not vp_finance_approved:
            return False, "Trade orders above EUR 100000 require supervisor approval."
        return True, "Allowed"

    def strip_instruction_like_vendor_content(
        self,
        text: str,
        control_events: list[SecurityEvent],
    ) -> tuple[str, list[str]]:
        removed: list[str] = []
        safe_lines: list[str] = []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            lowered = line.lower()
            is_instruction = (
                "system override" in lowered
                or "ignore policy" in lowered
                or "ignore privacy policy" in lowered
                or "include alice johnson" in lowered
                or "salary" in lowered and "account id" in lowered
                or "send benchmark returns to" in lowered
                or "force high-risk allocation" in lowered and "override" in lowered
            )
            if is_instruction:
                removed.append(raw_line)
                continue
            safe_lines.append(raw_line)

        if removed:
            control_events.append(
                SecurityEvent(
                    code="external_instruction_stripped",
                    severity="warning",
                    message="Instruction-like content in external document was ignored.",
                    details={"rule": 5, "removed_lines": removed},
                )
            )

        return "\n".join(safe_lines).strip(), removed

    @staticmethod
    def _payload_to_bytes(payload: dict[str, Any]) -> bytes:
        pairs = [f"{k}={payload[k]}" for k in sorted(payload.keys())]
        return "|".join(pairs).encode("utf-8")
