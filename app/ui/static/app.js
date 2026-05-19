/*
 * Copyright F5, Inc. 2026
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *     http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

(function () {
  const el = (id) => document.getElementById(id);

  const state = {
    topology: null,
    selectedNodeId: null,
    popoverNodeId: null,
    runtimeNodeId: null,
    runtimeToolNodeId: null,
    runtimeLlmNodeId: null,
    runtimeTriggeredToolNodeIds: new Set(),
    showGuardrailOverlay: true,
    topologyZoom: 1,
  };

  const TOPOLOGY_VIEW_WIDTH = 1500;
  const TOPOLOGY_VIEW_HEIGHT = 700;
  const TOPOLOGY_ZOOM_MIN = 0.65;
  const TOPOLOGY_ZOOM_MAX = 1.75;
  const TOPOLOGY_ZOOM_STEP = 0.1;

  const TOOL_COMPONENTS = [
    {
      name: "a2a_risk_profile_assess",
      label: "Risk Profile",
      summary: "A2A signed risk-profile assessment for investor suitability context.",
    },
    {
      name: "mcp_market_product_search",
      label: "Product Search",
      summary: "MCP product discovery across available market instruments.",
    },
    {
      name: "mcp_research_note_extract_facts",
      label: "Research Parse",
      summary: "MCP parser that extracts factual terms and strips instruction-like text.",
    },
    {
      name: "mcp_disclosure_repository_fetch",
      label: "Disclosure Fetch",
      summary: "MCP disclosure lookup for legal and client-facing product requirements.",
    },
    {
      name: "a2a_suitability_review",
      label: "Suitability",
      summary: "A2A suitability review service validating recommendation conditions.",
    },
    {
      name: "internal_exposure_check",
      label: "Exposure Check",
      summary: "Internal control to evaluate exposure constraints and approval thresholds.",
    },
    {
      name: "internal_recommendation_create_draft",
      label: "Draft Creation",
      summary: "Internal system creating a draft advisory recommendation record.",
    },
    {
      name: "internal_trade_order_create",
      label: "Trade Order",
      summary: "Internal final trade-order action subject to approval and policy gates.",
    },
  ];

  function pretty(value) {
    return JSON.stringify(value, null, 2);
  }

  function compactText(value, maxLen = 160) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (!text) return "";
    if (text.length <= maxLen) return text;
    return `${text.slice(0, maxLen)}...`;
  }

  function normalizeGuardrailStatus(status) {
    const raw = String(status || "").toLowerCase().trim();
    if (raw === "blocked") return "blocked";
    if (raw === "flagged" || raw === "redacted") return "flagged";
    if (raw === "clear" || raw === "cleared") return "clear";
    return "unknown";
  }

  function renderGuardrailStatus(status) {
    const container = el("guardrailStatus");
    const textEl = el("guardrailStatusText");
    if (!container || !textEl) return;
    const normalized = normalizeGuardrailStatus(status);
    container.className = `guardrail-status status-${normalized}`;
    textEl.textContent = normalized;
  }

  function stripGuardrailSection(text) {
    const lines = String(text || "").split("\n");
    const kept = [];
    let skipping = false;

    lines.forEach((line) => {
      const trimmed = line.trim();
      const lowered = trimmed.toLowerCase();
      if (lowered.startsWith("guardrail events:")) {
        skipping = true;
        return;
      }
      if (skipping) {
        if (!trimmed) return;
        if (trimmed.startsWith("-") || trimmed.startsWith("*")) return;
        skipping = false;
      }
      kept.push(line);
    });

    return kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function iconMarkup(icon) {
    if (icon === "user") {
      return (
        '<svg viewBox="0 0 24 24" aria-hidden="true">' +
        '<circle cx="12" cy="8" r="3.2"></circle>' +
        '<path d="M4.5 20c.9-3.7 3.8-5.8 7.5-5.8s6.6 2.1 7.5 5.8"></path>' +
        "</svg>"
      );
    }
    if (icon === "orchestrator") {
      return (
        '<svg viewBox="0 0 24 24" aria-hidden="true">' +
        '<circle cx="6" cy="6" r="2"></circle>' +
        '<circle cx="18" cy="6" r="2"></circle>' +
        '<circle cx="12" cy="18" r="2"></circle>' +
        '<path d="M7.8 7.2L10.3 15"></path>' +
        '<path d="M16.2 7.2L13.7 15"></path>' +
        '<path d="M8 6h8"></path>' +
        "</svg>"
      );
    }
    if (icon === "agent") {
      return (
        '<svg viewBox="0 0 24 24" aria-hidden="true">' +
        '<rect x="4.5" y="6.2" width="15" height="11.5" rx="3"></rect>' +
        '<circle cx="9.5" cy="12" r="1"></circle>' +
        '<circle cx="14.5" cy="12" r="1"></circle>' +
        '<path d="M9 16h6"></path>' +
        '<path d="M12 3.5v2.7"></path>' +
        "</svg>"
      );
    }
    if (icon === "tool") {
      return (
        '<svg viewBox="0 0 24 24" aria-hidden="true">' +
        '<rect x="5" y="5" width="5" height="5" rx="1"></rect>' +
        '<rect x="14" y="5" width="5" height="5" rx="1"></rect>' +
        '<rect x="5" y="14" width="5" height="5" rx="1"></rect>' +
        '<rect x="14" y="14" width="5" height="5" rx="1"></rect>' +
        "</svg>"
      );
    }
    if (icon === "final_agent") {
      return (
        '<svg viewBox="0 0 24 24" aria-hidden="true">' +
        '<rect x="5" y="4.5" width="11" height="15" rx="2"></rect>' +
        '<path d="M8 9.5h5"></path>' +
        '<path d="M8 13h5"></path>' +
        '<path d="M16 16l2.8-2.8 1.7 1.7L17.7 17.7"></path>' +
        "</svg>"
      );
    }
    if (icon === "memory") {
      return (
        '<svg viewBox="0 0 24 24" aria-hidden="true">' +
        '<rect x="6" y="7" width="12" height="10" rx="2"></rect>' +
        '<path d="M9 11h6"></path>' +
        '<path d="M9 14h4"></path>' +
        '<path d="M8 7V5"></path>' +
        '<path d="M12 7V5"></path>' +
        '<path d="M16 7V5"></path>' +
        '<path d="M8 19v-2"></path>' +
        '<path d="M12 19v-2"></path>' +
        '<path d="M16 19v-2"></path>' +
        "</svg>"
      );
    }
    if (icon === "guardrail") {
      return (
        '<svg viewBox="0 0 24 24" aria-hidden="true">' +
        '<path d="M12 3l7 3v5c0 5.3-3.2 8.8-7 10-3.8-1.2-7-4.7-7-10V6l7-3z"></path>' +
        '<path d="M8.7 11.6l2.1 2.1 4.4-4.4"></path>' +
        "</svg>"
      );
    }
    return (
      '<svg viewBox="0 0 24 24" aria-hidden="true">' +
      '<rect x="4.5" y="5" width="15" height="14" rx="2.5"></rect>' +
      '<path d="M8.3 12.2l2.4 2.4 4.9-4.9"></path>' +
      "</svg>"
    );
  }

  async function api(path, opts) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });

    const text = await response.text();
    let body = {};
    try {
      body = text ? JSON.parse(text) : {};
    } catch {
      body = { raw: text };
    }
    if (!response.ok) {
      throw new Error(pretty({ status: response.status, body }));
    }
    return body;
  }

  function hideChatEmpty() {
    const empty = el("chatEmpty");
    if (empty) empty.style.display = "none";
  }

  function scrollChatToBottom() {
    const stream = el("chatStream");
    if (!stream) return;
    stream.scrollTop = stream.scrollHeight;
  }

  function addMessage(role, text, metaText) {
    hideChatEmpty();
    const stream = el("chatStream");
    const container = document.createElement("div");
    container.className = `message ${role}`;

    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = metaText;

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;

    container.appendChild(meta);
    container.appendChild(bubble);
    stream.appendChild(container);
    scrollChatToBottom();

    return bubble;
  }

  function nodeById(nodes, id) {
    return nodes.find((n) => n.id === id);
  }

  function uniqueToolNames(result) {
    const calls = Array.isArray(result.tool_calls) ? result.tool_calls : [];
    const names = [];
    calls.forEach((call) => {
      const name = String(call.tool_name || "");
      if (!name || names.includes(name)) return;
      names.push(name);
    });
    return names;
  }

  function buildStoryTopology(result) {
    const interactions = Array.isArray(result.model_interactions) ? result.model_interactions : [];
    const tools = Array.isArray(result.tool_calls) ? result.tool_calls : [];
    const toolResults = Array.isArray(result.tool_results) ? result.tool_results : [];
    const route = String(result.generated_plan?.route || "unknown");

    const hasToolPhase = tools.length > 0;
    const hasFinalAgentTurn = interactions.some((x) => x.agent_name === "advisor_final_response_agent");
    const names = uniqueToolNames(result);
    const llmCallCounts = interactions.reduce((acc, interaction) => {
      const key = String(interaction.agent_name || "");
      if (!key) return acc;
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});
    const orchestratorCallCount = Number(llmCallCounts["advisor_orchestrator"] || 0);
    const toolAgentCallCount = Number(llmCallCounts["advisor_tool_agent"] || 0);
    const finalAgentCallCount = Number(llmCallCounts["advisor_final_response_agent"] || 0);
    const callCountByTool = {};
    tools.forEach((call) => {
      const name = String(call.tool_name || "");
      if (!name) return;
      callCountByTool[name] = (callCountByTool[name] || 0) + 1;
    });

    const roleSummary = {
      user_input:
        "Entry point for end-user intent. The initial request and trace id start here and are propagated across the workflow.",
      orchestrator:
        "Classifies intent and routes execution. Builds the plan and determines whether tool workflow is required or out-of-scope response is sufficient.",
      tool_agent:
        "Executes approved tool calls in sequence, using canonical OpenAI tool-call structure and feeding results back into the conversation state.",
      tool_layer:
        "Abstracted execution layer for MCP/A2A/internal tools. Returns structured outputs back to the agent workflow.",
      workflow_memory:
        "Shared working memory for this trace. Stores orchestrator plan, validated tool outputs, and accumulated context passed between agents.",
      final_agent:
        "Synthesizes validated context into the final advisory narrative for the client-facing response.",
      final_output:
        "Customer-visible answer returned to UI/API, including recommendation, required approvals, and actions taken.",
      calypso_guardrails:
        "All LLM turns route through F5 AI Guardrails via OpenAI-compatible /chat/completions with the shared trace_id in x-cai-metadata-session-id for enforcement and traceability.",
    };

    const baseNodes = [
      {
        id: "user_input",
        label: "User Input",
        icon: "user",
        kind: "input",
        x: 320,
        y: 84,
        active: true,
        meta: {
          role_summary: roleSummary.user_input,
          trace_id: result.trace_id || null,
          request: result.user_request || null,
        },
      },
      {
        id: "orchestrator",
        label: "Orchestrator",
        icon: "orchestrator",
        kind: "agent",
        x: 320,
        y: 190,
        active: true,
        meta: {
          role_summary: roleSummary.orchestrator,
          agent_name: "advisor_orchestrator",
          route,
          plan_summary: result.generated_plan?.plan_summary || null,
          steps: result.generated_plan?.steps || [],
        },
      },
      {
        id: "tool_agent",
        label: "Advisor Tool Agent",
        icon: "agent",
        kind: "agent",
        x: 240,
        y: 332,
        active: hasToolPhase,
        meta: {
          role_summary: roleSummary.tool_agent,
          agent_name: "advisor_tool_agent",
          tool_call_count: tools.length,
          unique_tools: names.length,
        },
      },
      {
        id: "tool_layer",
        label: "Tool Layer",
        icon: "tool",
        kind: "tool",
        x: 560,
        y: 286,
        active: hasToolPhase,
        meta: {
          role_summary: roleSummary.tool_layer,
          tools: names,
          recent_results: toolResults.slice(-3).map((r) => ({
            tool_name: r.tool_name,
            status: r.output?.status || "unknown",
            protocol: r.tool_protocol,
          })),
        },
      },
      {
        id: "workflow_memory",
        label: "Workflow Memory",
        icon: "memory",
        kind: "memory",
        x: 560,
        y: 456,
        active: true,
        meta: {
          role_summary: roleSummary.workflow_memory,
          stored_plan: Boolean(result.generated_plan?.steps?.length),
          stored_tool_results: toolResults.length,
          stored_llm_turns: interactions.length,
        },
      },
      {
        id: "calypso_guardrails",
        label: "F5 AI Guardrails",
        icon: "guardrail",
        kind: "guardrail",
        x: 560,
        y: 92,
        active: true,
        guardrailOverlay: true,
        meta: {
          role_summary: roleSummary.calypso_guardrails,
          total_llm_calls: interactions.length,
          orchestrator_calls: orchestratorCallCount,
          tool_agent_calls: toolAgentCallCount,
          final_agent_calls: finalAgentCallCount,
        },
      },
      {
        id: "final_agent",
        label: "Final Response Agent",
        icon: "final_agent",
        kind: "agent",
        x: 320,
        y: 548,
        active: hasFinalAgentTurn,
        meta: {
          role_summary: roleSummary.final_agent,
          agent_name: "advisor_final_response_agent",
          llm_turn_present: hasFinalAgentTurn,
        },
      },
      {
        id: "final_output",
        label: "Final Response",
        icon: "output",
        kind: "output",
        x: 320,
        y: 646,
        active: true,
        meta: {
          role_summary: roleSummary.final_output,
          final_answer: result.final_answer || "",
        },
      },
    ];

    const toolChildNodes = TOOL_COMPONENTS.map((tool, index) => {
      const col = index % 2;
      const row = Math.floor(index / 2);
      const x = col === 0 ? 760 : 940;
      const y = 256 + row * 92;
      const callCount = Number(callCountByTool[tool.name] || 0);
      return {
        id: `tool_component_${tool.name}`,
        label: tool.label,
        icon: "tool",
        kind: "tool-child",
        x,
        y,
        active: true,
        meta: {
          role_summary: tool.summary,
          tool_name: tool.name,
          call_count: callCount,
          invoked: callCount > 0,
        },
      };
    });

    const nodes = [...baseNodes, ...toolChildNodes];

    const edges = [
      { id: "e1", source: "user_input", target: "orchestrator", label: "request", active: true },
      { id: "e2", source: "orchestrator", target: "tool_agent", label: "plan", active: hasToolPhase },
      { id: "e3", source: "orchestrator", target: "tool_layer", label: "plan", active: hasToolPhase },
      { id: "e4", source: "tool_agent", target: "tool_layer", label: "execute", active: hasToolPhase },
      {
        id: "e5",
        source: "tool_layer",
        target: "tool_agent",
        label: "results",
        active: hasToolPhase,
        secondary: true,
      },
      {
        id: "e6",
        source: "tool_agent",
        target: "workflow_memory",
        label: "write",
        active: hasFinalAgentTurn,
      },
      {
        id: "e7",
        source: "orchestrator",
        target: "workflow_memory",
        label: "state",
        active: true,
        secondary: true,
      },
      {
        id: "e8",
        source: "workflow_memory",
        target: "final_agent",
        label: "context",
        active: hasFinalAgentTurn,
      },
      {
        id: "e9",
        source: "final_agent",
        target: "final_output",
        label: "respond",
        active: hasFinalAgentTurn,
      },
      {
        id: "e10",
        source: "orchestrator",
        target: "final_output",
        label: "direct",
        active: !hasToolPhase,
        secondary: true,
      },
      {
        id: "e_guardrail_orchestrator",
        source: "orchestrator",
        target: "calypso_guardrails",
        label: orchestratorCallCount > 0 ? `llm x${orchestratorCallCount}` : "",
        active: orchestratorCallCount > 0,
        secondary: true,
        guardrailOverlay: true,
      },
      {
        id: "e_guardrail_tool_agent",
        source: "tool_agent",
        target: "calypso_guardrails",
        label: toolAgentCallCount > 0 ? `llm x${toolAgentCallCount}` : "",
        active: toolAgentCallCount > 0,
        secondary: true,
        guardrailOverlay: true,
      },
      {
        id: "e_guardrail_final_agent",
        source: "final_agent",
        target: "calypso_guardrails",
        label: finalAgentCallCount > 0 ? `llm x${finalAgentCallCount}` : "",
        active: finalAgentCallCount > 0,
        secondary: true,
        guardrailOverlay: true,
      },
    ];
    toolChildNodes.forEach((node, index) => {
      const callCount = Number(node.meta?.call_count || 0);
      edges.push({
        id: `e_tool_${index + 1}`,
        source: "tool_layer",
        target: node.id,
        label: callCount > 0 ? `x${callCount}` : "",
        active: hasToolPhase && callCount > 0,
        secondary: true,
      });
    });

    const invokedToolLabels = toolChildNodes
      .filter((node) => Boolean(node.meta?.invoked))
      .map((node) => String(node.label));
    const invokedSummary = invokedToolLabels.length ? invokedToolLabels.join(", ") : "n/a";

    const steps = [];
    steps.push({
      nodeId: "user_input",
      text: `Prompt received: ${compactText(result.user_request, 88)}`,
    });
    steps.push({
      nodeId: "orchestrator",
      text: `Orchestrator routed to ${route}.`,
    });
    steps.push({
      nodeId: "tool_layer",
      text: hasToolPhase
        ? `Tool phase executed ${tools.length} call(s) across ${names.length} tool(s): ${invokedSummary}.`
        : "Tool phase skipped for this request.",
    });
    steps.push({
      nodeId: "workflow_memory",
      text: hasToolPhase
        ? "Workflow memory captured plan and validated tool outputs for downstream synthesis."
        : "Workflow memory retained route context for direct response handling.",
    });

    steps.push({
      nodeId: "final_agent",
      text: hasFinalAgentTurn
        ? "Final response agent produced the narrative response."
        : "No final response agent turn captured; using fallback response path.",
    });
    steps.push({ nodeId: "final_output", text: "Final response returned to client." });

    return { nodes, edges, steps };
  }

  function buildInitialTopology() {
    const topology = buildStoryTopology({
      user_request: "Waiting for first request.",
      generated_plan: { route: "idle" },
      tool_calls: [],
      tool_results: [],
      model_interactions: [],
      final_answer: "",
    });
    topology.steps = [
      { nodeId: "user_input", text: "Awaiting user request." },
      { nodeId: "orchestrator", text: "Architecture map is ready before first run." },
      { nodeId: "tool_layer", text: "Tool components are preloaded; invoked tools are highlighted during execution." },
      { nodeId: "workflow_memory", text: "Shared workflow memory is ready to capture plan and tool context." },
      { nodeId: "final_output", text: "Submit a request to populate the live execution path." },
    ];
    return topology;
  }

  function drawEdge(svg, source, target, edge) {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const activeNodeId = state.runtimeToolNodeId || state.runtimeNodeId;
    const isRuntimeEdge =
      activeNodeId && (edge.source === activeNodeId || edge.target === activeNodeId);
    const isGuardrailLive = isRuntimeEdge && Boolean(edge.guardrailOverlay);
    const isTriggeredToolEdge =
      edge.source === "tool_layer" && state.runtimeTriggeredToolNodeIds.has(String(edge.target || ""));
    const className = [
      "topology-edge",
      edge.secondary ? "edge-secondary" : "",
      edge.guardrailOverlay ? "edge-guardrail" : "",
      isRuntimeEdge ? "edge-live" : "",
      isGuardrailLive ? "edge-guardrail-live" : "",
      isTriggeredToolEdge ? "edge-tool-triggered" : "",
      edge.active ? "edge-active" : "edge-muted",
    ]
      .filter(Boolean)
      .join(" ");
    line.setAttribute("class", className);
    line.setAttribute("d", `M ${source.x} ${source.y} L ${target.x} ${target.y}`);
    svg.appendChild(line);

    const midX = (source.x + target.x) / 2;
    const midY = (source.y + target.y) / 2;
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const len = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
    const nx = -dy / len;
    const ny = dx / len;
    const edgeOffset = edge.secondary ? -8 : 9;
    if (edge.label) {
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("class", "topology-edge-label");
      label.setAttribute("x", String(midX + nx * edgeOffset));
      label.setAttribute("y", String(midY + ny * edgeOffset));
      label.setAttribute("text-anchor", "middle");
      label.textContent = edge.label;
      svg.appendChild(label);
    }
  }

  function drawTopology() {
    const topology = state.topology;
    if (!topology) return;

    const svg = el("topologySvg");
    const nodeLayer = el("topologyNodes");
    if (!svg || !nodeLayer) return;
    svg.setAttribute("viewBox", `0 0 ${TOPOLOGY_VIEW_WIDTH} ${TOPOLOGY_VIEW_HEIGHT}`);

    svg.querySelectorAll(".topology-edge, .topology-edge-label").forEach((item) => item.remove());
    nodeLayer.innerHTML = "";

    const visibleNodes = topology.nodes.filter((node) => state.showGuardrailOverlay || !node.guardrailOverlay);
    const visibleNodeIds = new Set(visibleNodes.map((node) => String(node.id)));
    const visibleEdges = topology.edges.filter(
      (edge) => visibleNodeIds.has(String(edge.source)) && visibleNodeIds.has(String(edge.target))
    );

    visibleEdges.forEach((edge) => {
      const source = nodeById(visibleNodes, edge.source);
      const target = nodeById(visibleNodes, edge.target);
      if (!source || !target) return;
      drawEdge(svg, source, target, edge);
    });

    visibleNodes.forEach((node) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = [
        "topology-node",
        `kind-${node.kind}`,
        node.active ? "is-active" : "is-muted",
        node.kind === "tool-child" && node.meta?.invoked ? "is-invoked" : "",
        node.kind === "tool-child" && !node.meta?.invoked ? "is-idle" : "",
        node.kind === "tool-child" && state.runtimeTriggeredToolNodeIds.has(node.id) ? "is-triggered-live" : "",
        state.runtimeNodeId === node.id || state.runtimeToolNodeId === node.id ? "working" : "",
        state.runtimeLlmNodeId === node.id ? "llm-active" : "",
        state.selectedNodeId === node.id ? "selected" : "",
      ]
        .filter(Boolean)
        .join(" ");
      button.style.left = `${node.x}px`;
      button.style.top = `${node.y}px`;
      button.innerHTML = `
        <span class="topology-node-icon">${iconMarkup(node.icon)}</span>
        <span class="topology-node-label">${node.label}</span>
      `;
      button.addEventListener("click", () => selectNode(node.id));
      nodeLayer.appendChild(button);
    });
  }

  function applyTopologyZoom(nextZoom, keepCenter = true) {
    const stage = el("topologyStage");
    const canvas = el("topologyCanvas");
    const scene = el("topologyScene");
    const label = el("topologyZoomLabel");
    if (!stage || !canvas || !scene) return;

    const clamped = Math.max(TOPOLOGY_ZOOM_MIN, Math.min(TOPOLOGY_ZOOM_MAX, Number(nextZoom) || 1));
    const prev = state.topologyZoom || 1;

    let worldX = 0;
    let worldY = 0;
    if (keepCenter) {
      worldX = (stage.scrollLeft + stage.clientWidth / 2) / prev;
      worldY = (stage.scrollTop + stage.clientHeight / 2) / prev;
    }

    state.topologyZoom = clamped;
    canvas.style.width = `${TOPOLOGY_VIEW_WIDTH * clamped}px`;
    canvas.style.height = `${TOPOLOGY_VIEW_HEIGHT * clamped}px`;
    scene.style.transform = `scale(${clamped})`;

    if (label) {
      label.textContent = `${Math.round(clamped * 100)}%`;
    }

    if (keepCenter) {
      const nextLeft = worldX * clamped - stage.clientWidth / 2;
      const nextTop = worldY * clamped - stage.clientHeight / 2;
      stage.scrollLeft = Math.max(0, nextLeft);
      stage.scrollTop = Math.max(0, nextTop);
    }

    if (state.popoverNodeId && state.topology) {
      const node = nodeById(state.topology.nodes, state.popoverNodeId);
      if (node) showNodePopover(node);
    }
  }

  function renderSteps() {
    const list = el("flowSteps");
    if (!list || !state.topology) return;
    list.innerHTML = "";
    state.topology.steps.forEach((step) => {
      const li = document.createElement("li");
      if (state.selectedNodeId === step.nodeId) li.classList.add("active");
      if (state.runtimeNodeId === step.nodeId) li.classList.add("live");
      li.textContent = step.text;
      li.addEventListener("click", () => selectNode(step.nodeId));
      list.appendChild(li);
    });
  }

  function selectNode(nodeId) {
    state.selectedNodeId = nodeId;
    drawTopology();
    renderSteps();

    if (!state.topology) return;
    const node = nodeById(state.topology.nodes, nodeId);
    if (!node) return;

    showNodePopover(node);
  }

  function showNodePopover(node) {
    const popover = el("nodePopover");
    const title = el("nodePopoverTitle");
    const summary = el("nodePopoverSummary");
    const stage = el("topologyStage");
    if (!popover || !title || !summary || !stage || !node) return;

    state.popoverNodeId = node.id;
    title.textContent = node.label;
    summary.textContent = String(node.meta?.role_summary || "No summary available.");
    popover.hidden = false;

    const zoom = state.topologyZoom || 1;
    const xPx = Number(node.x || 0) * zoom;
    const yPx = Number(node.y || 0) * zoom;
    const scrollLeft = stage.scrollLeft;
    const scrollTop = stage.scrollTop;
    const viewportWidth = stage.clientWidth;
    const viewportHeight = stage.clientHeight;

    let left = xPx + 20;
    let top = yPx - 70;
    const popWidth = 270;
    const popHeight = 120;

    if (left + popWidth > scrollLeft + viewportWidth - 10) left = xPx - popWidth - 20;
    if (left < scrollLeft + 10) left = scrollLeft + 10;
    if (top < scrollTop + 10) top = yPx + 18;
    if (top + popHeight > scrollTop + viewportHeight - 10) {
      top = scrollTop + viewportHeight - popHeight - 10;
    }

    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  }

  function hideNodePopover() {
    const pop = el("nodePopover");
    if (pop) pop.hidden = true;
    state.popoverNodeId = null;
  }

  function updateGuardrailToggleButton() {
    const toggleBtn = el("toggleGuardrailCallsBtn");
    if (!toggleBtn) return;
    toggleBtn.textContent = state.showGuardrailOverlay ? "Hide Guardrail Calls" : "Show Guardrail Calls";
  }

  function renderTopology(result) {
    state.topology = buildStoryTopology(result);
    state.runtimeNodeId = null;
    state.runtimeToolNodeId = null;
    state.runtimeLlmNodeId = null;
    state.runtimeTriggeredToolNodeIds = new Set();
    state.selectedNodeId = null;
    el("traceId").textContent = result.trace_id || "-";
    renderGuardrailStatus(result.guardrail_status || "unknown");
    drawTopology();
    renderSteps();
    hideNodePopover();
    updateGuardrailToggleButton();
  }

  function renderInitialTopology() {
    state.topology = buildInitialTopology();
    state.runtimeNodeId = null;
    state.runtimeToolNodeId = null;
    state.runtimeLlmNodeId = null;
    state.runtimeTriggeredToolNodeIds = new Set();
    state.selectedNodeId = null;
    el("traceId").textContent = "-";
    renderGuardrailStatus("unknown");
    drawTopology();
    renderSteps();
    hideNodePopover();
    updateGuardrailToggleButton();
  }

  function activateRuntimeNode(nodeId) {
    if (!state.topology) return;
    state.runtimeNodeId = nodeId;
    state.runtimeToolNodeId = null;
    drawTopology();
    renderSteps();
  }

  function buildRuntimeExecutionSteps(userRequest) {
    if (!state.topology) return;
    const promptPreview = compactText(userRequest, 88);
    state.topology.steps = [
      { nodeId: "user_input", text: `Prompt received: ${promptPreview}` },
      { nodeId: "orchestrator", text: "Orchestrator is classifying intent and building the route." },
      { nodeId: "tool_agent", text: "Tool agent is preparing approved tool calls." },
      { nodeId: "tool_layer", text: "Tool layer is executing calls and returning structured outputs." },
      { nodeId: "workflow_memory", text: "Workflow memory is updating shared state for downstream synthesis." },
      { nodeId: "final_agent", text: "Final response agent is synthesizing the advisory narrative." },
      { nodeId: "final_output", text: "Response is being prepared for delivery to the client." },
    ];
    renderSteps();
  }

  function beginLiveProgress(pendingBubble, userRequest) {
    stopRuntimeActivity();
    if (!state.topology) {
      renderInitialTopology();
    }
    state.runtimeTriggeredToolNodeIds = new Set();
    buildRuntimeExecutionSteps(userRequest);
    activateRuntimeNode("user_input");
    pendingBubble.textContent = "Running advisor workflow...\nRequest accepted by the workflow service.";
  }

  function applyProgressEvent(progressEvent, pendingBubble) {
    if (!progressEvent || typeof progressEvent !== "object") return;

    const componentId = String(progressEvent.component_id || "").trim();
    const toolComponentId = String(progressEvent.tool_component_id || "").trim();
    const eventKind = String(progressEvent.kind || "").trim();
    const eventStatus = String(progressEvent.status || "").trim();
    const eventMessage = String(progressEvent.message || "").trim();

    if (componentId) {
      state.runtimeNodeId = componentId;
    }

    if (eventKind === "tool_call" && eventStatus === "started" && toolComponentId) {
      state.runtimeToolNodeId = toolComponentId;
      state.runtimeTriggeredToolNodeIds.add(toolComponentId);
      state.runtimeLlmNodeId = null;
    } else if (eventKind === "tool_call" && eventStatus === "completed") {
      if (toolComponentId) {
        state.runtimeTriggeredToolNodeIds.add(toolComponentId);
      }
      state.runtimeToolNodeId = null;
    }

    if (eventKind === "llm_call" && eventStatus === "started" && componentId) {
      state.runtimeLlmNodeId = componentId;
    } else if (eventKind === "llm_call" && eventStatus === "completed") {
      state.runtimeLlmNodeId = null;
    }

    if (componentId === "final_output" && eventStatus === "completed") {
      state.runtimeToolNodeId = null;
      state.runtimeLlmNodeId = null;
    }

    drawTopology();
    renderSteps();

    if (eventMessage) {
      pendingBubble.textContent = `Running advisor workflow...\n${eventMessage}`;
    }
  }

  async function streamAdvisorRun(userRequest, onEvent) {
    const response = await fetch("/api/advisor/run/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_request: userRequest }),
    });

    if (!response.ok) {
      const text = await response.text();
      let body = {};
      try {
        body = text ? JSON.parse(text) : {};
      } catch {
        body = { raw: text };
      }
      throw new Error(pretty({ status: response.status, body }));
    }

    if (!response.body) {
      throw new Error("Streaming response body was empty.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let finalResult = null;

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary).trim();
        buffer = buffer.slice(boundary + 2);

        if (block) {
          let eventName = "message";
          const dataLines = [];
          block.split("\n").forEach((line) => {
            if (line.startsWith("event:")) {
              eventName = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataLines.push(line.slice(5).trim());
            }
          });

          let payload = {};
          const dataText = dataLines.join("\n");
          if (dataText) {
            try {
              payload = JSON.parse(dataText);
            } catch {
              payload = { raw: dataText };
            }
          }

          onEvent(eventName, payload);
          if (eventName === "error") {
            throw new Error(String(payload.message || "Streaming workflow failed."));
          }
          if (eventName === "result") {
            finalResult = payload;
          }
        }

        boundary = buffer.indexOf("\n\n");
      }

      if (done) {
        break;
      }
    }

    if (!finalResult) {
      throw new Error("Stream completed without a final result payload.");
    }
    return finalResult;
  }

  function stopRuntimeActivity() {
    if (
      state.runtimeNodeId ||
      state.runtimeToolNodeId ||
      state.runtimeLlmNodeId ||
      state.runtimeTriggeredToolNodeIds.size
    ) {
      state.runtimeNodeId = null;
      state.runtimeToolNodeId = null;
      state.runtimeLlmNodeId = null;
      state.runtimeTriggeredToolNodeIds = new Set();
      drawTopology();
      renderSteps();
    }
  }

  async function runCustom() {
    const userRequest = el("customRequest").value.trim();
    if (!userRequest) return;

    addMessage("user", userRequest, "user • custom");
    const pendingBubble = addMessage("assistant", "Running advisor workflow...", "assistant • pending");
    pendingBubble.classList.add("pending");
    renderGuardrailStatus("unknown");
    beginLiveProgress(pendingBubble, userRequest);

    try {
      let body;
      try {
        body = await streamAdvisorRun(userRequest, (eventName, payload) => {
          if (eventName === "progress") {
            applyProgressEvent(payload, pendingBubble);
          }
        });
      } catch (streamError) {
        pendingBubble.textContent = "Running advisor workflow...\nLive stream unavailable, falling back to standard run.";
        body = await api("/api/advisor/run", {
          method: "POST",
          body: JSON.stringify({ user_request: userRequest }),
        });
      }

      renderTopology(body);
      pendingBubble.classList.remove("pending");
      pendingBubble.textContent = stripGuardrailSection(body.final_answer || "No assistant response.");
      scrollChatToBottom();
    } finally {
      stopRuntimeActivity();
    }
  }

  async function loadScenarios() {
    const scenarios = await api("/api/scenarios");
    const promptLibrary = el("promptLibrary");
    promptLibrary.innerHTML = "";

    scenarios.forEach((scenario) => {
      const card = document.createElement("article");
      card.className = "prompt-card";

      const title = document.createElement("h4");
      title.textContent = scenario.title;
      const desc = document.createElement("p");
      desc.textContent = scenario.description;
      const hint = document.createElement("p");
      hint.className = "prompt-hint";
      hint.textContent = scenario.tool_focus_hint
        ? `Tool focus: ${scenario.tool_focus_hint}`
        : "Tool focus: Observe orchestrator and downstream tool-layer decisions.";
      const promptText = document.createElement("div");
      promptText.className = "prompt-text";
      promptText.textContent = scenario.user_request || "";

      const actions = document.createElement("div");
      actions.className = "prompt-actions";

      const copyBtn = document.createElement("button");
      copyBtn.className = "secondary";
      copyBtn.type = "button";
      copyBtn.textContent = "Copy";
      copyBtn.addEventListener("click", async () => {
        const original = copyBtn.textContent;
        try {
          await navigator.clipboard.writeText(scenario.user_request || "");
          copyBtn.textContent = "Copied";
        } catch (error) {
          addMessage("assistant", String(error.message || error), "assistant • error");
        } finally {
          setTimeout(() => {
            copyBtn.textContent = original;
          }, 900);
        }
      });

      const insertBtn = document.createElement("button");
      insertBtn.className = "secondary";
      insertBtn.type = "button";
      insertBtn.textContent = "Insert in Composer";
      insertBtn.addEventListener("click", () => {
        el("customRequest").value = scenario.user_request || "";
        setActiveTab("chat");
      });

      actions.appendChild(copyBtn);
      actions.appendChild(insertBtn);
      card.appendChild(title);
      card.appendChild(desc);
      card.appendChild(hint);
      card.appendChild(promptText);
      card.appendChild(actions);
      promptLibrary.appendChild(card);
    });
  }

  function setActiveTab(tabName) {
    const isChat = tabName === "chat";
    el("tabChatBtn").classList.toggle("active", isChat);
    el("tabPromptsBtn").classList.toggle("active", !isChat);
    el("chatTab").classList.toggle("active", isChat);
    el("promptsTab").classList.toggle("active", !isChat);
  }

  function clearChat() {
    stopRuntimeActivity();
    const stream = el("chatStream");
    const empty = el("chatEmpty");
    stream.innerHTML = "";
    if (empty) {
      empty.style.display = "block";
      stream.appendChild(empty);
    }
    renderGuardrailStatus("unknown");
    el("traceId").textContent = "-";
    hideNodePopover();
  }

  document.addEventListener("DOMContentLoaded", async () => {
    const runCustomBtn = el("runCustomBtn");
    const clearChatBtn = el("clearChatBtn");
    const tabChatBtn = el("tabChatBtn");
    const tabPromptsBtn = el("tabPromptsBtn");
    const nodePopoverClose = el("nodePopoverClose");
    const zoomOutBtn = el("zoomOutBtn");
    const zoomInBtn = el("zoomInBtn");
    const zoomResetBtn = el("zoomResetBtn");
    const toggleGuardrailCallsBtn = el("toggleGuardrailCallsBtn");

    runCustomBtn.addEventListener("click", async () => {
      runCustomBtn.disabled = true;
      runCustomBtn.textContent = "Running...";
      try {
        await runCustom();
      } catch (error) {
        addMessage("assistant", String(error.message || error), "assistant • error");
      } finally {
        runCustomBtn.disabled = false;
        runCustomBtn.textContent = "Send Request";
      }
    });

    clearChatBtn.addEventListener("click", () => clearChat());
    tabChatBtn.addEventListener("click", () => setActiveTab("chat"));
    tabPromptsBtn.addEventListener("click", () => setActiveTab("prompts"));
    if (nodePopoverClose) {
      nodePopoverClose.addEventListener("click", () => {
        hideNodePopover();
      });
    }
    if (zoomOutBtn) {
      zoomOutBtn.addEventListener("click", () => {
        applyTopologyZoom(state.topologyZoom - TOPOLOGY_ZOOM_STEP, true);
      });
    }
    if (zoomInBtn) {
      zoomInBtn.addEventListener("click", () => {
        applyTopologyZoom(state.topologyZoom + TOPOLOGY_ZOOM_STEP, true);
      });
    }
    if (zoomResetBtn) {
      zoomResetBtn.addEventListener("click", () => {
        applyTopologyZoom(1, true);
      });
    }
    if (toggleGuardrailCallsBtn) {
      toggleGuardrailCallsBtn.addEventListener("click", () => {
        state.showGuardrailOverlay = !state.showGuardrailOverlay;
        drawTopology();
        updateGuardrailToggleButton();
        hideNodePopover();
      });
    }

    renderInitialTopology();
    applyTopologyZoom(1, false);

    try {
      await loadScenarios();
    } catch (error) {
      addMessage("assistant", String(error.message || error), "assistant • error");
    }
  });
})();
