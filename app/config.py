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

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str
    calypsoai_base_url: str
    calypsoai_project_token: str | None
    openai_model: str
    openai_temperature: float
    allow_mock_llm: bool
    orchestrator_api_token: str | None

    @staticmethod
    def from_env() -> "Settings":
        base_url = os.getenv(
            "CALYPSOAI_BASE_URL",
            "https://us1.calypsoai.app/openai/CONNECTION-NAME",
        ).strip()
        token = (
            os.getenv("CALYPSOAI_PROJECT_TOKEN")
            or os.getenv("CALYPSOAI_TOKEN")
            or os.getenv("OPENAI_API_KEY")
            or ""
        ).strip()
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        return Settings(
            app_name=os.getenv("APP_NAME", "Financial Advisor Multi-Agent Guardrails Demo"),
            calypsoai_base_url=base_url.rstrip("/"),
            calypsoai_project_token=token or None,
            openai_model=model or "gpt-4o-mini",
            openai_temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.0")),
            allow_mock_llm=os.getenv("ALLOW_MOCK_LLM", "false").strip().lower() in {"1", "true", "yes"},
            orchestrator_api_token=(os.getenv("ORCHESTRATOR_API_TOKEN") or "").strip() or None,
        )


settings = Settings.from_env()
