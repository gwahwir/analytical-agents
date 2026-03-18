import { Group, Text, Badge } from "@mantine/core";

export default function AgentGroupNode({ data }) {
  const isOnline = data.status === "online";
  const borderColor = isOnline ? "var(--hud-green)" : "var(--hud-red)";
  const glowColor = isOnline ? "rgba(0, 255, 136, 0.2)" : "rgba(255, 61, 61, 0.2)";

  return (
    <div
      style={{
        width: data.width || 200,
        height: data.height || 120,
        background: "rgba(13, 17, 23, 0.7)",
        border: `1px solid ${borderColor}`,
        borderRadius: 0,
        boxShadow: `0 0 12px ${glowColor}`,
        padding: 12,
      }}
    >
      <Group gap="xs" mb={4}>
        <Text
          size="sm"
          fw={700}
          style={{
            textTransform: "uppercase",
            letterSpacing: "1px",
          }}
        >
          {data.label}
        </Text>
        <Badge
          size="xs"
          color={isOnline ? "hud-green" : "hud-red"}
          variant="light"
        >
          {data.status}
        </Badge>
      </Group>
    </div>
  );
}
