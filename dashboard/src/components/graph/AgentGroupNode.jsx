import { Paper, Group, Text, Badge } from "@mantine/core";

export default function AgentGroupNode({ data }) {
  const isOnline = data.status === "online";

  return (
    <Paper
      shadow="md"
      p="sm"
      withBorder
      style={{
        width: data.width || 200,
        height: data.height || 120,
        background: "var(--mantine-color-dark-7)",
        borderColor: isOnline
          ? "var(--mantine-color-green-8)"
          : "var(--mantine-color-red-8)",
        borderWidth: 2,
      }}
    >
      <Group gap="xs" mb={4}>
        <Text size="sm" fw={700}>
          {data.label}
        </Text>
        <Badge
          size="xs"
          color={isOnline ? "green" : "red"}
          variant="light"
        >
          {data.status}
        </Badge>
      </Group>
    </Paper>
  );
}
