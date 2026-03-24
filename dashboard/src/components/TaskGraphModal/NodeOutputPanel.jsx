// dashboard/src/components/TaskGraphModal/NodeOutputPanel.jsx
import { useState } from "react";
import { Tabs, Text, Code, Badge, Group, Stack, List } from "@mantine/core";

function renderValue(value) {
  if (typeof value === "string") {
    return <Text size="sm" style={{ color: "var(--hud-text-primary)", whiteSpace: "pre-wrap" }}>{value}</Text>;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return (
      <Text size="sm" style={{ color: "var(--hud-green)", fontFamily: "monospace" }}>
        {String(value)}
      </Text>
    );
  }
  if (Array.isArray(value)) {
    const allShort = value.every((v) => typeof v === "string" && v.length <= 40);
    if (allShort) {
      return (
        <Group gap="xs" wrap="wrap">
          {value.map((v, i) => (
            <Badge key={i} variant="outline" color="hud-cyan" size="sm">{v}</Badge>
          ))}
        </Group>
      );
    }
    return (
      <List size="sm" style={{ color: "var(--hud-text-primary)" }}>
        {value.map((v, i) => <List.Item key={i}>{String(v)}</List.Item>)}
      </List>
    );
  }
  return (
    <Code block style={{ color: "var(--hud-cyan)", backgroundColor: "var(--hud-bg-surface)", fontSize: 11 }}>
      {JSON.stringify(value, null, 2)}
    </Code>
  );
}

export default function NodeOutputPanel({ nodeId, nodeOutputJson, nodeState, onClose }) {
  const [tab, setTab] = useState("formatted");

  const header = (
    <Group justify="space-between" mb="sm">
      <Text size="xs" fw={600} style={{ color: "var(--hud-cyan)", letterSpacing: "1px", textTransform: "uppercase" }}>
        [ {nodeId} ] OUTPUT
      </Text>
      <Text size="xs" style={{ color: "var(--hud-text-dimmed)", cursor: "pointer" }} onClick={onClose}>
        ✕
      </Text>
    </Group>
  );

  if (nodeOutputJson === undefined && nodeState === "running") {
    return <div style={{ padding: 12 }}>{header}<Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>Node is running<span style={{ animation: "blink-cursor 1s step-end infinite" }}>_</span></Text></div>;
  }
  if (nodeOutputJson === undefined && nodeState === "pending") {
    return <div style={{ padding: 12 }}>{header}<Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>Node has not run yet</Text></div>;
  }
  if (nodeOutputJson === undefined) {
    return <div style={{ padding: 12 }}>{header}<Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>Output not available for this task</Text></div>;
  }
  if (nodeOutputJson === "{}") {
    return <div style={{ padding: 12 }}>{header}<Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>Node produced no output</Text></div>;
  }

  let parsed;
  try {
    parsed = JSON.parse(nodeOutputJson);
  } catch {
    return (
      <div style={{ padding: 12 }}>
        {header}
        <Badge color="hud-amber" variant="light" mb="xs">Parse error</Badge>
        <Code block style={{ color: "var(--hud-text-primary)", backgroundColor: "var(--hud-bg-surface)", fontSize: 11 }}>
          {nodeOutputJson}
        </Code>
      </div>
    );
  }

  return (
    <div style={{ padding: 12, height: "100%", overflow: "auto" }}>
      {header}
      <Tabs value={tab} onChange={setTab}>
        <Tabs.List mb="sm">
          <Tabs.Tab value="formatted" style={{ fontSize: 11, letterSpacing: "1px" }}>FORMATTED</Tabs.Tab>
          <Tabs.Tab value="raw" style={{ fontSize: 11, letterSpacing: "1px" }}>RAW</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="formatted">
          <Stack gap="sm">
            {Object.entries(parsed).map(([key, value]) => (
              <div key={key}>
                <Text size="xs" mb={4} style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px", textTransform: "uppercase", fontSize: 11 }}>{key}</Text>
                {renderValue(value)}
              </div>
            ))}
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="raw">
          <Code block style={{ color: "var(--hud-cyan)", backgroundColor: "var(--hud-bg-surface)", fontSize: 11, whiteSpace: "pre-wrap" }}>
            {JSON.stringify(parsed, null, 2)}
          </Code>
        </Tabs.Panel>
      </Tabs>
    </div>
  );
}
