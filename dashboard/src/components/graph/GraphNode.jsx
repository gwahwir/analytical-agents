import { Handle, Position } from "@xyflow/react";
import { Paper, Text, Group } from "@mantine/core";

export default function GraphNode({ data }) {
  const isEntry = data.isEntry;
  const isDownstream = data.isDownstream;

  return (
    <Paper
      shadow="xs"
      px="sm"
      py={6}
      withBorder
      style={{
        borderLeft: isEntry
          ? "3px solid var(--mantine-color-indigo-5)"
          : isDownstream
            ? "3px solid var(--mantine-color-orange-5)"
            : undefined,
        minWidth: 140,
        background: "var(--mantine-color-dark-6)",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: "#555" }} />
      <Group gap={6} wrap="nowrap">
        {isDownstream && (
          <Text size="xs" c="orange" style={{ lineHeight: 1 }}>
            &#8599;
          </Text>
        )}
        <Text size="xs" fw={500} c="dimmed" style={{ fontFamily: "monospace" }}>
          {data.label}
        </Text>
      </Group>
      <Handle type="source" position={Position.Right} style={{ background: "#555" }} />
    </Paper>
  );
}
