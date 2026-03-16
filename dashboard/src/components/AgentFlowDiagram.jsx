import { useEffect, useState, useMemo } from "react";
import { ReactFlow, Background, Controls } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Text, Alert } from "@mantine/core";
import { fetchGraph } from "../hooks/useApi";
import { computeLayout } from "./graph/layout";
import AgentGroupNode from "./graph/AgentGroupNode";
import GraphNode from "./graph/GraphNode";

const nodeTypes = {
  agentGroup: AgentGroupNode,
  graphNode: GraphNode,
};

export default function AgentFlowDiagram() {
  const [graphData, setGraphData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchGraph()
      .then(setGraphData)
      .catch((e) => setError(e.message));
  }, []);

  const { nodes, edges } = useMemo(
    () => (graphData ? computeLayout(graphData) : { nodes: [], edges: [] }),
    [graphData]
  );

  if (error) {
    return (
      <Alert color="red" mb="sm">
        Failed to load agent graph: {error}
      </Alert>
    );
  }

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
