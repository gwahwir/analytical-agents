import { Drawer, Stack, Text, Badge, Group, Code, Divider, Box } from "@mantine/core";

export default function AgentDetailDrawer({ agent, onClose }) {
  if (!agent) return null;

  const isOnline = agent.status === "online";
  const instances = agent.instances || [];
  const onlineInstances = instances.filter((i) => i.status === "online");
  const totalActive = instances.reduce((sum, i) => sum + (i.active_tasks || 0), 0);
  const skills = agent.skills || [];
  const capabilities = agent.capabilities || {};

  return (
    <Drawer
      opened={!!agent}
      onClose={onClose}
      title="Agent Detail"
      position="right"
      size="lg"
    >
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Text fw={700} size="xl">{agent.name}</Text>
          <Badge
            color={isOnline ? "green" : "red"}
            variant="light"
            size="lg"
            leftSection={
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  backgroundColor: isOnline
                    ? "var(--mantine-color-green-5)"
                    : "var(--mantine-color-red-5)",
                  display: "inline-block",
                }}
              />
            }
          >
            {agent.status}
          </Badge>
        </Group>

        <div>
          <Text size="xs" c="dimmed" tt="uppercase" fw={500}>
            Type ID
          </Text>
          <Code>{agent.id}</Code>
        </div>

        <div>
          <Text size="xs" c="dimmed" tt="uppercase" fw={500}>
            Description
          </Text>
          <Text size="sm" mt={4} style={{ whiteSpace: "pre-wrap" }}>
            {agent.description || "—"}
          </Text>
        </div>

        {agent.version && (
          <div>
            <Text size="xs" c="dimmed" tt="uppercase" fw={500}>
              Version
            </Text>
            <Text size="sm">{agent.version}</Text>
          </div>
        )}

        <Divider />

        {skills.length > 0 && (
          <div>
            <Text size="xs" c="dimmed" tt="uppercase" fw={500} mb="xs">
              Skills
            </Text>
            <Stack gap="xs">
              {skills.map((skill) => (
                <Box
                  key={skill.id}
                  p="xs"
                  style={{
                    border: "1px solid var(--mantine-color-default-border)",
                    borderRadius: "var(--mantine-radius-sm)",
                  }}
                >
                  <Group justify="space-between" mb={4}>
                    <Text size="sm" fw={600}>{skill.name}</Text>
                    <Code style={{ fontSize: 11 }}>{skill.id}</Code>
                  </Group>
                  {skill.description && (
                    <Text size="xs" c="dimmed">{skill.description}</Text>
                  )}
                  {skill.tags?.length > 0 && (
                    <Group gap={4} mt={6}>
                      {skill.tags.map((tag) => (
                        <Badge key={tag} variant="default" size="xs">{tag}</Badge>
                      ))}
                    </Group>
                  )}
                </Box>
              ))}
            </Stack>
          </div>
        )}

        {Object.keys(capabilities).length > 0 && (
          <>
            <Divider />
            <div>
              <Text size="xs" c="dimmed" tt="uppercase" fw={500} mb="xs">
                Capabilities
              </Text>
              <Group gap="xs">
                {Object.entries(capabilities).map(([key, value]) => (
                  <Badge
                    key={key}
                    variant={value ? "light" : "outline"}
                    color={value ? "blue" : "gray"}
                    size="sm"
                  >
                    {key}: {String(value)}
                  </Badge>
                ))}
              </Group>
            </div>
          </>
        )}

        <Divider />

        <div>
          <Group justify="space-between" mb="xs">
            <Text size="xs" c="dimmed" tt="uppercase" fw={500}>
              Instances ({onlineInstances.length}/{instances.length} online)
            </Text>
            {totalActive > 0 && (
              <Badge variant="light" color="yellow" size="xs">
                {totalActive} active task{totalActive !== 1 ? "s" : ""}
              </Badge>
            )}
          </Group>
          {instances.length === 0 && (
            <Text size="sm" c="dimmed">No instances registered.</Text>
          )}
          <Stack gap="xs">
            {instances.map((inst, i) => {
              const instOnline = inst.status === "online";
              return (
                <Box
                  key={inst.url || i}
                  p="xs"
                  style={{
                    border: "1px solid var(--mantine-color-default-border)",
                    borderRadius: "var(--mantine-radius-sm)",
                  }}
                >
                  <Group justify="space-between">
                    <Code style={{ fontSize: 12 }}>{inst.url}</Code>
                    <Badge
                      size="xs"
                      color={instOnline ? "green" : "red"}
                      variant="light"
                    >
                      {inst.status}
                    </Badge>
                  </Group>
                  <Text size="xs" c="dimmed" mt={4}>
                    Active tasks: {inst.active_tasks ?? 0}
                  </Text>
                </Box>
              );
            })}
          </Stack>
        </div>
      </Stack>
    </Drawer>
  );
}
