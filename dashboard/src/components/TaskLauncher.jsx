import { useState, useMemo } from "react";
import {
  Group,
  Select,
  TextInput,
  Textarea,
  Button,
  Title,
  Alert,
  Stack,
} from "@mantine/core";
import { dispatchTask } from "../hooks/useApi";

const DEFAULT_FIELDS = [
  {
    name: "text",
    label: "Prompt",
    type: "text",
    required: true,
    placeholder: "Enter a task prompt...",
  },
];

export default function TaskLauncher({ agents, graphData, onTaskCreated }) {
  const [agentId, setAgentId] = useState(null);
  const [fields, setFields] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const inputFields = useMemo(() => {
    if (!agentId || !graphData?.agents) return DEFAULT_FIELDS;
    const agentGraph = graphData.agents.find((a) => a.id === agentId);
    if (!agentGraph?.input_fields?.length) return DEFAULT_FIELDS;
    return agentGraph.input_fields;
  }, [agentId, graphData]);

  const handleAgentChange = (id) => {
    setAgentId(id);
    setFields({});
    setError(null);
  };

  const handleFieldChange = (name, value) => {
    setFields((prev) => ({ ...prev, [name]: value }));
  };

  const canSubmit = useMemo(() => {
    if (!agentId) return false;
    return inputFields
      .filter((f) => f.required)
      .every((f) => (fields[f.name] || "").trim());
  }, [agentId, inputFields, fields]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;

    setLoading(true);
    setError(null);
    try {
      let payload;
      if (inputFields.length === 1 && inputFields[0].name === "text") {
        payload = (fields.text || "").trim();
      } else {
        const data = {};
        inputFields.forEach((f) => {
          data[f.name] = (fields[f.name] || "").trim();
        });
        payload = JSON.stringify(data);
      }

      const result = await dispatchTask(agentId, payload);
      onTaskCreated(result);
      setFields({});
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const agentOptions = agents
    .filter((a) => a.status === "online")
    .map((a) => ({ value: a.id, label: a.name }));

  return (
    <div>
      <Title
        order={3}
        mb="md"
        style={{ textTransform: "uppercase", letterSpacing: "2px", fontSize: 16 }}
      >
        [ DISPATCH TASK ]
      </Title>
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <Group align="end">
            <Select
              label="Agent"
              placeholder="Select agent..."
              data={agentOptions}
              value={agentId}
              onChange={handleAgentChange}
              style={{ minWidth: 200 }}
            />
          </Group>

          {inputFields.map((field) => {
            const Component = field.type === "textarea" ? Textarea : TextInput;
            return (
              <Component
                key={field.name}
                label={field.label}
                placeholder={field.placeholder || ""}
                required={field.required}
                value={fields[field.name] || ""}
                onChange={(e) =>
                  handleFieldChange(field.name, e.currentTarget.value)
                }
                autosize={field.type === "textarea"}
                minRows={field.type === "textarea" ? 3 : undefined}
                maxRows={field.type === "textarea" ? 10 : undefined}
              />
            );
          })}

          <Group>
            <Button
              type="submit"
              loading={loading}
              disabled={!canSubmit}
              variant="outline"
              style={{
                borderColor: "var(--hud-cyan)",
                color: "var(--hud-cyan)",
                background: "transparent",
                transition: "all 0.2s",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "rgba(0, 212, 255, 0.1)";
                e.currentTarget.style.textShadow = "0 0 8px rgba(0, 212, 255, 0.5)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "transparent";
                e.currentTarget.style.textShadow = "none";
              }}
            >
              EXECUTE
            </Button>
          </Group>
        </Stack>
      </form>
      {error && (
        <Alert color="red" mt="sm" style={{ borderLeftColor: "var(--hud-red)" }}>
          {error}
        </Alert>
      )}
    </div>
  );
}
