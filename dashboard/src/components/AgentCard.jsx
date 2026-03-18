import { Card, Group, Text, Badge } from "@mantine/core";

export default function AgentCard({ agent, onSelect }) {
  const isOnline = agent.status === "online";
  const instances = agent.instances || [];
  const onlineInstances = instances.filter((i) => i.status === "online");
  const totalActive = instances.reduce((sum, i) => sum + (i.active_tasks || 0), 0);

  const statusColor = isOnline ? "var(--hud-green)" : "var(--hud-red)";

  return (
    <Card
      padding="md"
      onClick={() => onSelect(agent)}
      style={{
        cursor: "pointer",
        position: "relative",
        transition: "border-color 0.2s, box-shadow 0.2s",
        animation: "fade-in-up 0.3s ease-out",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "var(--hud-cyan)";
        e.currentTarget.style.boxShadow = "0 0 12px rgba(0, 212, 255, 0.15)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "var(--hud-border)";
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      {/* Corner bracket decoration */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: 12,
          height: 12,
          borderTop: "2px solid var(--hud-cyan)",
          borderLeft: "2px solid var(--hud-cyan)",
        }}
      />

      <Group justify="space-between" mb="xs">
        <Text
          fw={600}
          size="lg"
          style={{ flex: 1, minWidth: 0, color: "var(--hud-text-primary)" }}
          lineClamp={1}
        >
          {agent.name}
        </Text>
        <Badge
          color={isOnline ? "hud-green" : "hud-red"}
          variant="light"
          size="sm"
          leftSection={
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                backgroundColor: statusColor,
                display: "inline-block",
                animation: "pulse-glow 2s ease-in-out infinite",
                color: statusColor,
              }}
            />
          }
        >
          {agent.status}
        </Badge>
      </Group>

      <Text size="sm" style={{ color: "var(--hud-text-dimmed)" }} lineClamp={2} mb="sm">
        {agent.description}
      </Text>

      <Group gap="xs" justify="space-between">
        <Group gap="xs">
          {agent.skills?.length > 0 &&
            agent.skills.slice(0, 3).map((skill) => (
              <Badge
                key={skill.id}
                variant="outline"
                size="xs"
                style={{
                  borderColor: "var(--hud-border)",
                  color: "var(--hud-text-dimmed)",
                  textTransform: "uppercase",
                }}
              >
                {skill.name}
              </Badge>
            ))}
          {agent.skills?.length > 3 && (
            <Badge
              variant="outline"
              size="xs"
              style={{
                borderColor: "var(--hud-border)",
                color: "var(--hud-text-dimmed)",
              }}
            >
              +{agent.skills.length - 3}
            </Badge>
          )}
        </Group>

        <Group gap={6}>
          {instances.length > 1 && (
            <Badge variant="light" color="hud-cyan" size="xs">
              {onlineInstances.length}/{instances.length} instances
            </Badge>
          )}
          {totalActive > 0 && (
            <Badge variant="light" color="hud-amber" size="xs">
              {totalActive} active
            </Badge>
          )}
        </Group>
      </Group>
    </Card>
  );
}
