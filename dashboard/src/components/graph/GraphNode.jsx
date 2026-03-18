import { Handle, Position } from "@xyflow/react";
import { Text, Group } from "@mantine/core";

export default function GraphNode({ data }) {
  const isEntry = data.isEntry;
  const isDownstream = data.isDownstream;

  const handleStyle = {
    background: "var(--hud-cyan)",
    boxShadow: "0 0 4px rgba(0, 212, 255, 0.5)",
    width: 6,
    height: 6,
  };

  return (
    <div
      style={{
        background: "var(--hud-bg-surface)",
        border: "1px solid var(--hud-border)",
        borderRadius: 0,
        borderLeft: isEntry
          ? "3px solid var(--hud-cyan)"
          : isDownstream
            ? "3px solid var(--hud-amber)"
            : "1px solid var(--hud-border)",
        boxShadow: isEntry
          ? "inset 3px 0 8px rgba(0, 212, 255, 0.1)"
          : undefined,
        minWidth: 140,
        padding: "6px 12px",
      }}
    >
      <Handle type="target" position={Position.Left} style={handleStyle} />
      <Group gap={6} wrap="nowrap">
        {isDownstream && (
          <Text size="xs" style={{ color: "var(--hud-amber)", lineHeight: 1 }}>
            &#8599;
          </Text>
        )}
        <Text
          size="xs"
          fw={500}
          style={{
            color: "var(--hud-text-dimmed)",
            textTransform: "uppercase",
          }}
        >
          {data.label}
        </Text>
      </Group>
      <Handle type="source" position={Position.Right} style={handleStyle} />
    </div>
  );
}
