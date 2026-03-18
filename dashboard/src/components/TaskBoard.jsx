import { SimpleGrid, Card, Text, Badge, Title, Group, Stack } from "@mantine/core";

const STATE_COLUMNS = [
  { key: "submitted", label: "Queued", color: "var(--hud-text-dimmed)" },
  { key: "working", label: "Working", color: "var(--hud-amber)" },
  { key: "input-required", label: "Input Required", color: "var(--hud-violet)" },
  { key: "completed", label: "Done", color: "var(--hud-green)" },
  { key: "canceled", label: "Cancelled", color: "var(--hud-red)" },
  { key: "failed", label: "Failed", color: "var(--hud-red)" },
];

const STATE_BORDER_COLORS = {
  submitted: "var(--hud-text-dimmed)",
  working: "var(--hud-amber)",
  "input-required": "var(--hud-violet)",
  completed: "var(--hud-green)",
  canceled: "var(--hud-red)",
  failed: "var(--hud-red)",
};

export default function TaskBoard({ tasks, onSelectTask }) {
  const grouped = {};
  for (const col of STATE_COLUMNS) grouped[col.key] = [];
  for (const t of tasks) {
    if (grouped[t.state]) grouped[t.state].push(t);
  }

  return (
    <div>
      <Title
        order={3}
        mb="md"
        style={{ textTransform: "uppercase", letterSpacing: "2px", fontSize: 16 }}
      >
        [ ACTIVE TASKS ]
      </Title>
      <SimpleGrid cols={{ base: 2, md: 3, lg: 6 }}>
        {STATE_COLUMNS.map((col) => (
          <div key={col.key}>
            <Group gap="xs" mb="xs">
              <Text
                size="sm"
                fw={500}
                style={{
                  color: col.color,
                  textTransform: "uppercase",
                  letterSpacing: "1px",
                  fontSize: 11,
                }}
              >
                {col.label}
              </Text>
              <Text size="xs" fw={700} style={{ color: col.color }}>
                {grouped[col.key].length}
              </Text>
            </Group>
            <Stack gap="xs">
              {grouped[col.key].map((task) => (
                <Card
                  key={task.task_id}
                  padding="xs"
                  onClick={() => onSelectTask(task)}
                  style={{
                    cursor: "pointer",
                    backgroundColor: "var(--hud-bg-surface)",
                    borderLeft: `2px solid ${STATE_BORDER_COLORS[task.state] || "var(--hud-border)"}`,
                    transition: "border-color 0.2s, box-shadow 0.2s",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = col.color;
                    e.currentTarget.style.boxShadow = `0 0 8px ${col.color}33`;
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = "var(--hud-border)";
                    e.currentTarget.style.borderLeftColor = STATE_BORDER_COLORS[task.state] || "var(--hud-border)";
                    e.currentTarget.style.boxShadow = "none";
                  }}
                >
                  <Text size="xs" lineClamp={1}>
                    {task.input_text}
                  </Text>
                  <Text
                    size="xs"
                    mt={4}
                    style={{
                      color: "var(--hud-text-dimmed)",
                      textTransform: "uppercase",
                      fontSize: 10,
                    }}
                  >
                    {task.agent_id}
                  </Text>
                </Card>
              ))}
            </Stack>
          </div>
        ))}
      </SimpleGrid>
    </div>
  );
}
