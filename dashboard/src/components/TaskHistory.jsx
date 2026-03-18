import { useState } from "react";
import {
  TextInput,
  Select,
  Table,
  Title,
  Group,
  Badge,
  Text,
  Button,
  ActionIcon,
  Tooltip,
} from "@mantine/core";

const stateColors = {
  completed: "hud-green",
  working: "hud-amber",
  submitted: "gray",
  canceled: "hud-red",
  failed: "hud-red",
  "input-required": "hud-violet",
};

export default function TaskHistory({ tasks, onSelectTask, onDeleteTask, onClearAll }) {
  const [search, setSearch] = useState("");
  const [filterState, setFilterState] = useState(null);
  const [confirmClear, setConfirmClear] = useState(false);

  const filtered = tasks.filter((t) => {
    const matchesSearch =
      !search ||
      t.input_text.toLowerCase().includes(search.toLowerCase()) ||
      t.agent_id.toLowerCase().includes(search.toLowerCase()) ||
      t.task_id.toLowerCase().includes(search.toLowerCase());
    const matchesState = !filterState || t.state === filterState;
    return matchesSearch && matchesState;
  });

  const handleClearAll = () => {
    if (!confirmClear) {
      setConfirmClear(true);
      setTimeout(() => setConfirmClear(false), 3000);
      return;
    }
    onClearAll();
    setConfirmClear(false);
  };

  return (
    <div>
      <Group mb="md" justify="space-between">
        <Title
          order={3}
          style={{ textTransform: "uppercase", letterSpacing: "2px", fontSize: 16 }}
        >
          [ TASK HISTORY ]
        </Title>
        {tasks.length > 0 && (
          <Button
            variant={confirmClear ? "filled" : "outline"}
            color={confirmClear ? "hud-red" : "hud-red"}
            size="xs"
            onClick={handleClearAll}
            style={
              confirmClear
                ? { boxShadow: "0 0 12px rgba(255, 61, 61, 0.3)" }
                : { borderColor: "var(--hud-red)", color: "var(--hud-red)" }
            }
          >
            {confirmClear ? "CONFIRM CLEAR ALL" : "CLEAR ALL"}
          </Button>
        )}
      </Group>

      <Group mb="md">
        <TextInput
          placeholder="Search tasks..."
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          style={{ flex: 1, minWidth: 200 }}
        />
        <Select
          placeholder="All states"
          clearable
          data={[
            { value: "completed", label: "Completed" },
            { value: "working", label: "Working" },
            { value: "submitted", label: "Submitted" },
            { value: "canceled", label: "Cancelled" },
            { value: "failed", label: "Failed" },
          ]}
          value={filterState}
          onChange={setFilterState}
        />
      </Group>

      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Task ID</Table.Th>
            <Table.Th>Agent</Table.Th>
            <Table.Th>Input</Table.Th>
            <Table.Th>State</Table.Th>
            <Table.Th>Time</Table.Th>
            <Table.Th w={50}></Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {filtered.map((task) => (
            <Table.Tr
              key={task.task_id}
              style={{
                cursor: "pointer",
                backgroundColor: "var(--hud-bg-panel)",
                transition: "background-color 0.15s",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = "var(--hud-bg-surface)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = "var(--hud-bg-panel)";
              }}
            >
              <Table.Td onClick={() => onSelectTask(task)}>
                <Text size="xs" style={{ color: "var(--hud-cyan)" }}>
                  {task.task_id.slice(0, 8)}...
                </Text>
              </Table.Td>
              <Table.Td onClick={() => onSelectTask(task)}>{task.agent_id}</Table.Td>
              <Table.Td
                onClick={() => onSelectTask(task)}
                maw={200}
                style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
              >
                {task.input_text}
              </Table.Td>
              <Table.Td onClick={() => onSelectTask(task)}>
                <Group gap={4}>
                  <Badge color={stateColors[task.state] || "gray"} variant="light" size="sm">
                    {task.state}
                  </Badge>
                  {task.error && (
                    <Tooltip label={task.error.slice(0, 120)} multiline w={300}>
                      <Badge color="hud-red" variant="filled" size="xs">err</Badge>
                    </Tooltip>
                  )}
                </Group>
              </Table.Td>
              <Table.Td onClick={() => onSelectTask(task)}>
                <Text size="xs" style={{ color: "var(--hud-text-dimmed)" }}>
                  {new Date(task.created_at * 1000).toLocaleString()}
                </Text>
              </Table.Td>
              <Table.Td>
                <Tooltip label="Delete">
                  <ActionIcon
                    variant="subtle"
                    color="hud-red"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteTask(task.task_id);
                    }}
                    style={{ transition: "box-shadow 0.2s" }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.boxShadow = "0 0 8px rgba(255, 61, 61, 0.4)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.boxShadow = "none";
                    }}
                  >
                    x
                  </ActionIcon>
                </Tooltip>
              </Table.Td>
            </Table.Tr>
          ))}
          {filtered.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={6}>
                <Text ta="center" style={{ color: "var(--hud-text-dimmed)" }} py="md">
                  No tasks found.
                </Text>
              </Table.Td>
            </Table.Tr>
          )}
        </Table.Tbody>
      </Table>
    </div>
  );
}
