import { Card, Group, Text, Badge } from "@mantine/core";

export default function AgentCard({ agent, onSelect }) {
  const isOnline = agent.status === "online";
  const instances = agent.instances || [];
  const onlineInstances = instances.filter((i) => i.status === "online");
  const totalActive = instances.reduce((sum, i) => sum + (i.active_tasks || 0), 0);

  return (
    <Card
      shadow="sm"
      padding="md"
      withBorder
      onClick={() => onSelect(agent)}
      style={{ cursor: "pointer" }}
    >
      <Group justify="space-between" mb="xs">
        <Text fw={600} size="lg" style={{ flex: 1, minWidth: 0 }} lineClamp={1}>
          {agent.name}
        </Text>
        <Badge
          color={isOnline ? "green" : "red"}
          variant="light"
          size="sm"
          leftSection={
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                backgroundColor: isOnline ? "var(--mantine-color-green-5)" : "var(--mantine-color-red-5)",
                display: "inline-block",
              }}
            />
          }
        >
          {agent.status}
        </Badge>
      </Group>

      <Text size="sm" c="dimmed" lineClamp={2} mb="sm">
        {agent.description}
      </Text>

      <Group gap="xs" justify="space-between">
        <Group gap="xs">
          {agent.skills?.length > 0 &&
            agent.skills.slice(0, 3).map((skill) => (
              <Badge key={skill.id} variant="default" size="xs">
                {skill.name}
              </Badge>
            ))}
          {agent.skills?.length > 3 && (
            <Badge variant="default" size="xs">
              +{agent.skills.length - 3}
            </Badge>
          )}
        </Group>

        <Group gap={6}>
          {instances.length > 1 && (
            <Badge variant="light" color="blue" size="xs">
              {onlineInstances.length}/{instances.length} instances
            </Badge>
          )}
          {totalActive > 0 && (
            <Badge variant="light" color="yellow" size="xs">
              {totalActive} active
            </Badge>
          )}
        </Group>
      </Group>
    </Card>
  );
}
