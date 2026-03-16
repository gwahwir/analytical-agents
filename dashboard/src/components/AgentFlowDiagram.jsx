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
    return <Text c="dimmed" size="sm">Loading graph...</Text>;
  }

  if (graphData.agents?.length === 0) {
    return <Text c="dimmed" size="sm">No agents online to display.</Text>;
  }

  return (
    <div style={{ height: 420, background: "var(--mantine-color-dark-8)", borderRadius: 8 }}>
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
        <Background color="#333" gap={16} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
