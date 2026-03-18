import { useState } from "react";
import { Drawer, Stack, Text, Badge, Code, Button, Group, Alert } from "@mantine/core";
import { cancelTask } from "../hooks/useApi";

const stateColors = {
  completed: "hud-green",
  working: "hud-amber",
  submitted: "gray",
  canceled: "hud-red",
  failed: "hud-red",
  "input-required": "hud-violet",
};

export default function TaskDetailDrawer({ task, onClose, onCancelled }) {
  const [cancelling, setCancelling] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  if (!task) return null;

  const canCancel = ["submitted", "working"].includes(task.state);

  const handleCancel = async () => {
    if (!confirmCancel) {
      setConfirmCancel(true);
      return;
    }
    setCancelling(true);
    try {
      await cancelTask(task.agent_id, task.task_id);
      onCancelled(task.task_id);
    } catch (err) {
      alert("Cancel failed: " + err.message);
    } finally {
      setCancelling(false);
      setConfirmCancel(false);
    }
  };

  const handleClose = () => {
    setConfirmCancel(false);
    onClose();
  };

  return (
    <Drawer
      opened={!!task}
      onClose={handleClose}
      title={
        <Text fw={600} style={{ textTransform: "uppercase", letterSpacing: "2px", fontSize: 14 }}>
          [ TASK DETAIL ]
        </Text>
      }
      position="right"
      size="lg"
    >
      <Stack gap="md">
        <div>
          <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase" fw={500}>
            Task ID
          </Text>
          <Code>{task.task_id}</Code>
        </div>

        <div>
          <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase" fw={500}>
            Agent
          </Text>
          <Text size="sm">{task.agent_id}</Text>
        </div>

        <div>
          <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase" fw={500}>
            State
          </Text>
          <Badge color={stateColors[task.state] || "gray"} variant="light">
            {task.state}
          </Badge>
        </div>

        {task.error && (
          <Alert color="red" title="Error" variant="light" style={{ borderLeftColor: "var(--hud-red)" }}>
            <Code block style={{ whiteSpace: "pre-wrap", background: "transparent", color: "inherit" }}>
              {task.error}
            </Code>
          </Alert>
        )}

        <div>
          <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase" fw={500}>
            Input
          </Text>
          <Code
            block
            mt="xs"
            style={{
              backgroundColor: "var(--hud-bg-surface)",
              border: "1px solid var(--hud-border)",
              color: "var(--hud-cyan)",
            }}
          >
            {task.input_text || "\u2014"}
          </Code>
        </div>

        <div>
          <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase" fw={500}>
            Output
          </Text>
          <Code
            block
            mt="xs"
            style={{
              backgroundColor: "var(--hud-bg-surface)",
              border: "1px solid var(--hud-border)",
              color: "var(--hud-cyan)",
            }}
          >
            {task.output_text || "\u2014"}
          </Code>
        </div>

        <div>
          <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase" fw={500}>
            Created
          </Text>
          <Text size="sm">
            {task.created_at
              ? new Date(task.created_at * 1000).toLocaleString()
              : "\u2014"}
          </Text>
        </div>

        {canCancel && (
          <Group mt="md">
            <Button
              color="hud-red"
              variant={confirmCancel ? "filled" : "outline"}
              onClick={handleCancel}
              loading={cancelling}
              style={
                confirmCancel
                  ? { boxShadow: "0 0 12px rgba(255, 61, 61, 0.3)" }
                  : { borderColor: "var(--hud-red)", color: "var(--hud-red)" }
              }
            >
              {confirmCancel ? "CLICK AGAIN TO CONFIRM" : "CANCEL TASK"}
            </Button>
          </Group>
        )}
      </Stack>
    </Drawer>
  );
}
