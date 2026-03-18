import { useMemo } from "react";
import { ReactFlow, Background, Controls } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Text } from "@mantine/core";
import { computeLayout } from "./graph/layout";
import AgentGroupNode from "./graph/AgentGroupNode";
import GraphNode from "./graph/GraphNode";

const nodeTypes = {
  agentGroup: AgentGroupNode,
  graphNode: GraphNode,
};

export default function AgentFlowDiagram({ graphData }) {
  const { nodes, edges } = useMemo(
    () => (graphData ? computeLayout(graphData) : { nodes: [], edges: [] }),
    [graphData]
  );

  if (!graphData) {
    return (
      <Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>
        Loading graph
        <span style={{ animation: "blink-cursor 1s step-end infinite" }}>_</span>
      </Text>
    );
  }

  if (graphData.agents?.length === 0) {
    return (
      <Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>
        No agents online to display
        <span style={{ animation: "blink-cursor 1s step-end infinite" }}>_</span>
      </Text>
    );
  }

  return (
    <div
      style={{
        height: 500,
        background: "var(--hud-bg-deep)",
        borderRadius: 0,
        border: "1px solid var(--hud-border)",
      }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="rgba(0, 212, 255, 0.06)" gap={20} />
        <Controls
          showInteractive={false}
          style={{
            background: "var(--hud-bg-panel)",
            border: "1px solid var(--hud-border)",
            borderRadius: 0,
          }}
        />
      </ReactFlow>
    </div>
  );
}
