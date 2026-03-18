import dagre from "@dagrejs/dagre";

const NODE_WIDTH = 160;
const NODE_HEIGHT = 36;
const GROUP_PADDING_TOP = 50;
const GROUP_PADDING_X = 24;
const GROUP_PADDING_BOTTOM = 24;
const GROUP_GAP = 100;

/**
 * Convert the /graph API response into React Flow nodes and edges.
 *
 * All nodes use absolute positioning (no parentId) so that cross-agent
 * edges render correctly. Agent group nodes are placed behind their
 * children using lower zIndex.
 */
export function computeLayout(graphData) {
  const { agents = [], cross_agent_edges = [] } = graphData;
  const nodes = [];
  const edges = [];

  if (!agents.length) return { nodes, edges };

  // Step 1: Layout each agent's internal graph with dagre
  const agentLayouts = {};

  agents.forEach((agent) => {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: "LR", nodesep: 20, ranksep: 40 });
    g.setDefaultEdgeLabel(() => ({}));

    agent.nodes.forEach((n) => {
      g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
    });
    agent.edges.forEach((e) => {
      g.setEdge(e.source, e.target);
    });

    dagre.layout(g);

    const positioned = [];
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    g.nodes().forEach((nid) => {
      const n = g.node(nid);
      if (!n) return;
      positioned.push({ id: nid, x: n.x, y: n.y });
      minX = Math.min(minX, n.x - NODE_WIDTH / 2);
      minY = Math.min(minY, n.y - NODE_HEIGHT / 2);
      maxX = Math.max(maxX, n.x + NODE_WIDTH / 2);
      maxY = Math.max(maxY, n.y + NODE_HEIGHT / 2);
    });

    const contentWidth = maxX - minX;
    const contentHeight = maxY - minY;

    agentLayouts[agent.id] = {
      agent,
      positioned,
      minX,
      minY,
      groupWidth: contentWidth + GROUP_PADDING_X * 2,
      groupHeight: contentHeight + GROUP_PADDING_TOP + GROUP_PADDING_BOTTOM,
    };
  });

  // Step 2: Align all agent groups vertically centered, laid out left-to-right
  const maxGroupHeight = Math.max(
    ...Object.values(agentLayouts).map((l) => l.groupHeight)
  );

  let currentX = 0;
  const agentPositions = {};

  agents.forEach((agent) => {
    const layout = agentLayouts[agent.id];
    // Center vertically relative to the tallest group
    const yOffset = (maxGroupHeight - layout.groupHeight) / 2;
    agentPositions[agent.id] = { x: currentX, y: yOffset };
    currentX += layout.groupWidth + GROUP_GAP;
  });

  // Step 3: Build React Flow nodes with absolute positions
  agents.forEach((agent) => {
    const layout = agentLayouts[agent.id];
    const groupPos = agentPositions[agent.id];

    // Agent group node (background container, lower z-index)
    nodes.push({
      id: `group-${agent.id}`,
      type: "agentGroup",
      position: { x: groupPos.x, y: groupPos.y },
      data: {
        label: agent.name,
        status: agent.status,
        width: layout.groupWidth,
        height: layout.groupHeight,
      },
      draggable: false,
      selectable: false,
      zIndex: 0,
    });

    // Internal nodes — absolute position (group origin + padding + relative pos)
    layout.positioned.forEach((n) => {
      const isEntry = n.id === agent.entry_node;
      const isDownstream = cross_agent_edges.some(
        (e) => e.source_agent === agent.id && e.source_node === n.id
      );

      nodes.push({
        id: `${agent.id}:${n.id}`,
        type: "graphNode",
        position: {
          x: groupPos.x + (n.x - layout.minX + GROUP_PADDING_X - NODE_WIDTH / 2),
          y: groupPos.y + (n.y - layout.minY + GROUP_PADDING_TOP - NODE_HEIGHT / 2),
        },
        data: {
          label: n.id,
          isEntry,
          isDownstream,
        },
        draggable: false,
        zIndex: 1,
      });
    });

    // Internal edges
    agent.edges.forEach((e) => {
      edges.push({
        id: `${agent.id}:${e.source}-${e.target}`,
        source: `${agent.id}:${e.source}`,
        target: `${agent.id}:${e.target}`,
        type: "smoothstep",
        style: { stroke: "rgba(0, 212, 255, 0.25)", strokeDasharray: "4 4" },
        animated: true,
        zIndex: 2,
      });
    });
  });

  // Step 4: Cross-agent edges
  cross_agent_edges.forEach((e, i) => {
    edges.push({
      id: `cross-${i}`,
      source: `${e.source_agent}:${e.source_node}`,
      target: `${e.target_agent}:${e.target_node}`,
      type: "smoothstep",
      style: { stroke: "var(--hud-amber)", strokeDasharray: "6 3" },
      animated: true,
      label: "A2A",
      labelStyle: { fill: "var(--hud-amber)", fontSize: 11 },
      labelBgStyle: { fill: "var(--hud-bg-deep)" },
      labelBgPadding: [6, 3],
      zIndex: 3,
    });
  });

  return { nodes, edges };
}
