// dashboard/src/components/TaskGraphModal/TaskFlowGraph.jsx
import { useMemo } from "react";
import { ReactFlow, Background, Controls } from "@xyflow/react";
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

function ExecutionNode({ data }) {
  const style = STATE_STYLES[data.executionState] || STATE_STYLES.pending;
  const dotColor = DOT_COLORS[data.executionState];
  return (
    <div style={{ ...style, borderRadius: 0, minWidth: 140, padding: "6px 12px", fontFamily: "monospace", fontSize: 11, letterSpacing: "0.5px", textTransform: "uppercase", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
      {dotColor && <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", backgroundColor: dotColor, flexShrink: 0 }} />}
      {data.label}
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

export default function TaskFlowGraph({ agentData, taskState, selectedNodeId, onNodeSelect }) {
  const nodeOutputs = taskState?.node_outputs;
  const runningNode = taskState?.running_node || null;
  const taskFailed = taskState?.state === "failed";

  const { nodes: rawNodes, edges } = useMemo(
    () => agentData ? computeLayout({ agents: [agentData], cross_agent_edges: [] }) : { nodes: [], edges: [] },
    [agentData]
  );

  const nodes = useMemo(() => rawNodes.map((node) => {
    if (node.type !== "graphNode") return node;
    const bareId = node.id.split(":").slice(1).join(":");
    const executionState = getExecutionState({ bareId, selectedNodeId, runningNode, nodeOutputs, taskFailed });
    return { ...node, type: "executionNode", data: { ...node.data, executionState } };
  }), [rawNodes, selectedNodeId, runningNode, nodeOutputs, taskFailed]);

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
