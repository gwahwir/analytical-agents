import { useState } from "react";
import { Drawer, Stack, Text, Badge, Group, Code, Divider, Box, Button, Tooltip } from "@mantine/core";
import { deregisterAgent } from "../hooks/useApi";

export default function AgentDetailDrawer({ agent, onClose }) {
  const [confirmUrl, setConfirmUrl] = useState(null);
  const [deregistering, setDeregistering] = useState(null);

  if (!agent) return null;

  const isOnline = agent.status === "online";
  const instances = agent.instances || [];
  const onlineInstances = instances.filter((i) => i.status === "online");
  const totalActive = instances.reduce((sum, i) => sum + (i.active_tasks || 0), 0);
  const skills = agent.skills || [];
  const capabilities = agent.capabilities || {};

  const statusColor = isOnline ? "var(--hud-green)" : "var(--hud-red)";

  const handleDeregister = async (url) => {
    if (confirmUrl !== url) {
      setConfirmUrl(url);
      setTimeout(() => setConfirmUrl(null), 3000);
      return;
    }
    setDeregistering(url);
    try {
      await deregisterAgent(agent.id, url);
      setConfirmUrl(null);
      onClose();
    } catch {
      // stay open so user can see the failure
    } finally {
      setDeregistering(null);
    }
  };

  const handleClose = () => {
    setConfirmUrl(null);
    setDeregistering(null);
    onClose();
  };

  return (
    <Drawer
      opened={!!agent}
      onClose={handleClose}
      title={
        <Text fw={600} style={{ textTransform: "uppercase", letterSpacing: "2px", fontSize: 14 }}>
          [ AGENT DETAIL ]
        </Text>
      }
      position="right"
      size="lg"
    >
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Text fw={700} size="xl">{agent.name}</Text>
          <Badge
            color={isOnline ? "hud-green" : "hud-red"}
            variant="light"
            size="lg"
            leftSection={
              <span
                style={{
                  width: 8,
                  height: 8,
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

        <div>
          <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase" fw={500}>
            Type ID
          </Text>
          <Code>{agent.id}</Code>
        </div>

        <div>
          <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase" fw={500}>
            Description
          </Text>
          <Text size="sm" mt={4} style={{ whiteSpace: "pre-wrap" }}>
            {agent.description || "\u2014"}
          </Text>
        </div>

        {agent.version && (
          <div>
            <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase" fw={500}>
              Version
            </Text>
            <Text size="sm">{agent.version}</Text>
          </div>
        )}

        <Divider color="var(--hud-border)" />

        {skills.length > 0 && (
          <div>
            <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase" fw={500} mb="xs">
              Skills
            </Text>
            <Stack gap="xs">
              {skills.map((skill) => (
                <Box
                  key={skill.id}
                  p="xs"
                  style={{
                    backgroundColor: "var(--hud-bg-surface)",
                    border: "1px solid var(--hud-border)",
                    borderRadius: 0,
                  }}
                >
                  <Group justify="space-between" mb={4}>
                    <Text size="sm" fw={600}>{skill.name}</Text>
                    <Code style={{ fontSize: 11 }}>{skill.id}</Code>
                  </Group>
                  {skill.description && (
                    <Text size="xs" style={{ color: "var(--hud-text-dimmed)" }}>{skill.description}</Text>
                  )}
                  {skill.tags?.length > 0 && (
                    <Group gap={4} mt={6}>
                      {skill.tags.map((tag) => (
                        <Badge key={tag} variant="outline" size="xs" style={{ borderColor: "var(--hud-border)" }}>
                          {tag}
                        </Badge>
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
            <Divider color="var(--hud-border)" />
            <div>
              <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase" fw={500} mb="xs">
                Capabilities
              </Text>
              <Group gap="xs">
                {Object.entries(capabilities).map(([key, value]) => (
                  <Badge
                    key={key}
                    variant={value ? "light" : "outline"}
                    color={value ? "hud-cyan" : "gray"}
                    size="sm"
                  >
                    {key}: {String(value)}
                  </Badge>
                ))}
              </Group>
            </div>
          </>
        )}

        <Divider color="var(--hud-border)" />

        <div>
          <Group justify="space-between" mb="xs">
            <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase" fw={500}>
              Instances ({onlineInstances.length}/{instances.length} online)
            </Text>
            {totalActive > 0 && (
              <Badge variant="light" color="hud-amber" size="xs">
                {totalActive} active task{totalActive !== 1 ? "s" : ""}
              </Badge>
            )}
          </Group>
          {instances.length === 0 && (
            <Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>No instances registered.</Text>
          )}
          <Stack gap="xs">
            {instances.map((inst, i) => {
              const instOnline = inst.status === "online";
              const instColor = instOnline ? "var(--hud-green)" : "var(--hud-red)";
              const isConfirming = confirmUrl === inst.url;
              return (
                <Box
                  key={inst.url || i}
                  p="xs"
                  style={{
                    backgroundColor: "var(--hud-bg-surface)",
                    border: "1px solid var(--hud-border)",
                    borderRadius: 0,
                  }}
                >
                  <Group justify="space-between">
                    <Code style={{ fontSize: 12 }}>{inst.url}</Code>
                    <Badge
                      size="xs"
                      color={instOnline ? "hud-green" : "hud-red"}
                      variant="light"
                      leftSection={
                        <span
                          style={{
                            width: 5,
                            height: 5,
                            borderRadius: "50%",
                            backgroundColor: instColor,
                            display: "inline-block",
                            animation: "pulse-glow 2s ease-in-out infinite",
                            color: instColor,
                          }}
                        />
                      }
                    >
                      {inst.status}
                    </Badge>
                  </Group>
                  <Group justify="space-between" mt={4}>
                    <Text size="xs" style={{ color: "var(--hud-text-dimmed)" }}>
                      Active tasks: {inst.active_tasks ?? 0}
                    </Text>
                    <Tooltip label="Remove this instance from the registry">
                      <Button
                        size="compact-xs"
                        variant={isConfirming ? "filled" : "outline"}
                        color="hud-red"
                        loading={deregistering === inst.url}
                        onClick={() => handleDeregister(inst.url)}
                        style={
                          isConfirming
                            ? { boxShadow: "0 0 12px rgba(255, 61, 61, 0.3)" }
                            : { borderColor: "var(--hud-red)", color: "var(--hud-red)" }
                        }
                      >
                        {isConfirming ? "CONFIRM" : "UNREGISTER"}
                      </Button>
                    </Tooltip>
                  </Group>
                </Box>
              );
            })}
          </Stack>
        </div>
      </Stack>
    </Drawer>
  );
}
