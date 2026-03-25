// dashboard/src/components/TaskGraphModal/TaskFlowGraph.jsx
import { useMemo } from "react";
import { ReactFlow, Background, Controls, Handle, Position } from "@xyflow/react";
import { Text } from "@mantine/core";
import { computeLayout } from "../graph/layout";

const STATE_STYLES = {
  pending:   { background: "#0d1117", border: "1px solid #374151",  color: "#6b7280", opacity: 0.5, boxShadow: "none" },
  running:   { background: "#1a1200", border: "1px solid #f59e0b",  color: "#fbbf24", opacity: 1,   boxShadow: "0 0 12px rgba(245,158,11,0.5)" },
  completed: { background: "#0a1a0a", border: "1px solid #22c55e",  color: "#4ade80", opacity: 1,   boxShadow: "none" },
  failed:    { background: "#1a0505", border: "1px solid #ef4444",  color: "#f87171", opacity: 1,   boxShadow: "none" },
  selected:  { background: "#001a2a", border: "2px solid #00d4ff",  color: "#00d4ff", opacity: 1,   boxShadow: "0 0 14px rgba(0,212,255,0.3)" },
};

const DOT_COLORS = {
  running: "#f59e0b", completed: "#22c55e", failed: "#ef4444", selected: "#00d4ff",
};

const NODE_STRIDE = 56; // px between stacked fan-out nodes

function ExecutionNode({ data }) {
  const style = STATE_STYLES[data.executionState] || STATE_STYLES.pending;
  const dotColor = DOT_COLORS[data.executionState];
  const handleStyle = { background: "var(--hud-cyan)", width: 6, height: 6 };
  return (
    <div style={{
      ...style,
      borderRadius: 0,
      minWidth: 140,
      padding: "6px 12px",
      fontFamily: "monospace",
      fontSize: 11,
      letterSpacing: "0.5px",
      textTransform: "uppercase",
      display: "flex",
      alignItems: "center",
      gap: 6,
      cursor: "pointer",
      // Fan-out nodes get a subtle left accent to distinguish them from base
      ...(data.isFanOut && { borderLeft: "3px solid rgba(0,212,255,0.35)" }),
    }}>
      <Handle type="target" position={Position.Left} style={handleStyle} />
      {dotColor && <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", backgroundColor: dotColor, flexShrink: 0 }} />}
      {data.label}
      <Handle type="source" position={Position.Right} style={handleStyle} />
    </div>
  );
}

const nodeTypes = { executionNode: ExecutionNode };

function getExecutionState({ bareId, selectedNodeId, runningNode, nodeOutputs, taskFailed }) {
  if (bareId === selectedNodeId) return "selected";
  if (runningNode && bareId === runningNode) return "running";
  if (nodeOutputs && bareId in nodeOutputs) return "completed";
  if (taskFailed && nodeOutputs && !(bareId in nodeOutputs)) return "failed";
  return "pending";
}

// Extract specialist name from a call_specialist output JSON string, if present.
function extractSpecialistLabel(jsonStr) {
  if (!jsonStr) return null;
  try {
    const parsed = JSON.parse(jsonStr);
    const results = parsed?.results;
    if (Array.isArray(results) && results.length > 0 && Array.isArray(results[0])) {
      return results[0][0]; // tuple[0] = specialist label
    }
  } catch {}
  return null;
}

// Pattern: "baseName:N" where N is a positive integer — created by the control plane
// when multiple fan-out executions share the same node name.
const FAN_OUT_KEY_RE = /^(.+):(\d+)$/;

export default function TaskFlowGraph({ agentData, taskState, selectedNodeId, onNodeSelect }) {
  const nodeOutputs = taskState?.node_outputs;
  const runningNode = taskState?.running_node || null;
  const taskFailed = taskState?.state === "failed";

  const { nodes: rawNodes, edges: rawEdges } = useMemo(
    () => agentData ? computeLayout({ agents: [agentData], cross_agent_edges: [] }) : { nodes: [], edges: [] },
    [agentData]
  );

  const [nodes, edges] = useMemo(() => {
    // Step 1: build base converted nodes (graphNode → executionNode)
    const converted = rawNodes.map((node) => {
      if (node.type !== "graphNode") return node;
      const bareId = node.id.split(":").slice(1).join(":");
      const executionState = getExecutionState({ bareId, selectedNodeId, runningNode, nodeOutputs, taskFailed });

      // If this is a specialist call node and its output contains a specialist name, use it as label
      const label = extractSpecialistLabel(nodeOutputs?.[bareId]) ?? node.data.label;

      return { ...node, type: "executionNode", data: { ...node.data, label, executionState } };
    });

    if (!nodeOutputs) return [converted, rawEdges];

    // Step 2: find any fan-out keys (e.g. "call_specialist:1", "call_specialist:2")
    const extrasByBase = {};
    for (const key of Object.keys(nodeOutputs)) {
      const m = FAN_OUT_KEY_RE.exec(key);
      if (m) {
        const base = m[1];
        if (!extrasByBase[base]) extrasByBase[base] = [];
        extrasByBase[base].push(key);
      }
    }

    if (Object.keys(extrasByBase).length === 0) return [converted, rawEdges];

    // Step 3: for each base node that has fan-out extras, inject new nodes + edges
    const extraNodes = [];
    const extraEdges = [];

    for (const node of converted) {
      if (node.type !== "executionNode") continue;
      const bareId = node.id.split(":").slice(1).join(":");
      const agentId = node.id.split(":")[0];
      const extras = extrasByBase[bareId];
      if (!extras) continue;

      extras.forEach((extraKey, idx) => {
        const executionState = getExecutionState({ bareId: extraKey, selectedNodeId, runningNode, nodeOutputs, taskFailed });
        const label = extractSpecialistLabel(nodeOutputs[extraKey]) ?? extraKey;

        extraNodes.push({
          ...node,
          id: `${agentId}:${extraKey}`,
          position: {
            x: node.position.x,
            y: node.position.y + (idx + 1) * NODE_STRIDE,
          },
          data: {
            ...node.data,
            label,
            executionState,
            isFanOut: true,
          },
        });

        // Mirror the base node's incoming + outgoing edges for each fan-out instance
        for (const e of rawEdges) {
          if (e.source === node.id) {
            extraEdges.push({ ...e, id: `${e.id}-fo${idx}-src`, source: `${agentId}:${extraKey}` });
          }
          if (e.target === node.id) {
            extraEdges.push({ ...e, id: `${e.id}-fo${idx}-tgt`, target: `${agentId}:${extraKey}` });
          }
        }
      });
    }

    return [[...converted, ...extraNodes], [...rawEdges, ...extraEdges]];
  }, [rawNodes, rawEdges, selectedNodeId, runningNode, nodeOutputs, taskFailed]);

  if (!agentData) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
        <Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>
          Graph topology unavailable — agent is no longer registered
        </Text>
      </div>
    );
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.3 }}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={true}
      onNodeClick={(_, node) => {
        if (node.type !== "executionNode") return;
        onNodeSelect(node.id.split(":").slice(1).join(":"));
      }}
      proOptions={{ hideAttribution: true }}
    >
      <Background color="rgba(0, 212, 255, 0.06)" gap={20} />
      <Controls showInteractive={false} style={{ background: "var(--hud-bg-panel)", border: "1px solid var(--hud-border)", borderRadius: 0 }} />
    </ReactFlow>
  );
}
