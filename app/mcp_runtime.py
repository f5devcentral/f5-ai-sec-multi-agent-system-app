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

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4


ToolHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class MCPToolCallResult:
    output: dict[str, Any]
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]
    status: str
    request_id: str


class LoopbackMCPServer:
    """
    Minimal in-process MCP JSON-RPC server.
    This keeps a real client/server contract while remaining local for demo use.
    """

    def __init__(self, *, server_name: str, tool_handlers: dict[str, ToolHandler]) -> None:
        self.server_name = server_name
        self._tool_handlers = dict(tool_handlers)

    def handle_jsonrpc(
        self,
        request_payload: dict[str, Any],
        *,
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime_context = runtime_context or {}
        request_id = request_payload.get("id")

        if str(request_payload.get("jsonrpc", "")) != "2.0":
            return self._error(
                request_id=request_id,
                code=-32600,
                message="Invalid Request: jsonrpc must be 2.0",
            )

        method = str(request_payload.get("method", "")).strip()
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": sorted(self._tool_handlers.keys()),
                    "server_name": self.server_name,
                },
            }

        if method != "tools/call":
            return self._error(
                request_id=request_id,
                code=-32601,
                message=f"Method not found: {method}",
            )

        params = request_payload.get("params")
        if not isinstance(params, dict):
            return self._error(
                request_id=request_id,
                code=-32602,
                message="Invalid params: params must be an object",
            )

        tool_name = str(params.get("name", "")).strip()
        arguments = params.get("arguments")
        if not tool_name:
            return self._error(
                request_id=request_id,
                code=-32602,
                message="Invalid params: tool name is required",
            )
        if not isinstance(arguments, dict):
            return self._error(
                request_id=request_id,
                code=-32602,
                message="Invalid params: arguments must be an object",
            )

        handler = self._tool_handlers.get(tool_name)
        if not handler:
            return self._error(
                request_id=request_id,
                code=-32601,
                message=f"Unknown MCP tool: {tool_name}",
            )

        try:
            payload = handler(arguments, runtime_context)
        except Exception as exc:  # noqa: BLE001
            return self._error(
                request_id=request_id,
                code=-32000,
                message=f"Tool execution error: {exc}",
            )

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "isError": False,
                "server_name": self.server_name,
                "content": [
                    {
                        "type": "json",
                        "json": payload,
                    }
                ],
            },
        }

    @staticmethod
    def _error(*, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }


class LoopbackMCPClient:
    """
    Minimal MCP JSON-RPC client with explicit request/response payloads.
    """

    def __init__(self, server: LoopbackMCPServer) -> None:
        self._server = server

    def call_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        trace_id: str,
        session_id: str,
        caller_agent: str,
        runtime_context: dict[str, Any] | None = None,
    ) -> MCPToolCallResult:
        request_id = f"mcp-{uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()
        request_payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
                "metadata": {
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "caller_agent": caller_agent,
                    "timestamp": now,
                },
            },
        }

        response_payload = self._server.handle_jsonrpc(
            request_payload,
            runtime_context=runtime_context or {},
        )

        output, status = self._extract_output(response_payload)
        return MCPToolCallResult(
            output=output,
            request_payload=request_payload,
            response_payload=response_payload,
            status=status,
            request_id=request_id,
        )

    @staticmethod
    def _extract_output(response_payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if not isinstance(response_payload, dict):
            return {"status": "error", "message": "Invalid MCP response payload"}, "error"

        error_node = response_payload.get("error")
        if isinstance(error_node, dict):
            return {
                "status": "error",
                "message": str(error_node.get("message", "Unknown MCP error")),
                "code": error_node.get("code"),
            }, "error"

        result = response_payload.get("result")
        if not isinstance(result, dict):
            return {"status": "error", "message": "Missing MCP result node"}, "error"

        content = result.get("content")
        if not isinstance(content, list) or not content:
            return {"status": "error", "message": "Missing MCP content node"}, "error"

        first = content[0]
        if not isinstance(first, dict):
            return {"status": "error", "message": "Invalid MCP content item"}, "error"

        json_payload = first.get("json")
        if not isinstance(json_payload, dict):
            return {"status": "error", "message": "MCP content.json must be an object"}, "error"

        status = "error" if bool(result.get("isError")) else "ok"
        return json_payload, status
