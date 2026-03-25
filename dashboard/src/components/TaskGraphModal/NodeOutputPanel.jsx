// dashboard/src/components/TaskGraphModal/NodeOutputPanel.jsx
import { useState } from "react";
import { Tabs, Text, Code, Badge, Group, Stack } from "@mantine/core";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";

// Syntax-highlighted JSON tree renderer
function JsonNode({ value, depth = 0 }) {
  const indent = depth * 14;

  if (value === null) {
    return <span style={{ color: "#9ca3af" }}>null</span>;
  }
  if (typeof value === "boolean") {
    return <span style={{ color: "#a78bfa" }}>{String(value)}</span>;
  }
  if (typeof value === "number") {
    return <span style={{ color: "#34d399" }}>{String(value)}</span>;
  }
  if (typeof value === "string") {
    // Try to detect embedded JSON strings and render them recursively
    const trimmed = value.trim();
    if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
      try {
        const inner = JSON.parse(trimmed);
        return (
          <span>
            <span style={{ color: "#fbbf24", fontSize: 10, opacity: 0.6 }}>"</span>
            <JsonNode value={inner} depth={depth} />
            <span style={{ color: "#fbbf24", fontSize: 10, opacity: 0.6 }}>"</span>
          </span>
        );
      } catch {}
    }
    return <span style={{ color: "#fbbf24" }}>"{value}"</span>;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return <span style={{ color: "#9ca3af" }}>[]</span>;
    return (
      <span>
        <span style={{ color: "#9ca3af" }}>[</span>
        <div style={{ paddingLeft: 14 }}>
          {value.map((item, i) => (
            <div key={i}>
              <JsonNode value={item} depth={depth + 1} />
              {i < value.length - 1 && <span style={{ color: "#9ca3af" }}>,</span>}
            </div>
          ))}
        </div>
        <span style={{ color: "#9ca3af" }}>]</span>
      </span>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value);
    if (entries.length === 0) return <span style={{ color: "#9ca3af" }}>{"{}"}</span>;
    return (
      <span>
        <span style={{ color: "#9ca3af" }}>{"{"}</span>
        <div style={{ paddingLeft: 14 }}>
          {entries.map(([k, v], i) => (
            <div key={k} style={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
              <span style={{ color: "#60a5fa", flexShrink: 0 }}>"{k}"</span>
              <span style={{ color: "#9ca3af", flexShrink: 0 }}>: </span>
              <span style={{ flex: 1 }}><JsonNode value={v} depth={depth + 1} /></span>
              {i < entries.length - 1 && <span style={{ color: "#9ca3af" }}>,</span>}
            </div>
          ))}
        </div>
        <span style={{ color: "#9ca3af" }}>{"}"}</span>
      </span>
    );
  }

  return <span style={{ color: "var(--hud-text-primary)" }}>{String(value)}</span>;
}

function JsonTree({ value }) {
  return (
    <div style={{
      backgroundColor: "var(--hud-bg-surface)",
      border: "1px solid var(--hud-border)",
      padding: "10px 12px",
      fontFamily: "monospace",
      fontSize: 12,
      lineHeight: 1.7,
      overflowX: "auto",
      color: "var(--hud-text-primary)",
    }}>
      <JsonNode value={value} depth={0} />
    </div>
  );
}

function renderValue(value) {
  if (typeof value === "string") {
    // Try to parse embedded JSON strings
    const trimmed = value.trim();
    if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
      try {
        const inner = JSON.parse(trimmed);
        return <JsonTree value={inner} />;
      } catch {}
    }
    return (
      <div style={{ color: "var(--hud-text-primary)", fontSize: 13, lineHeight: 1.7 }} className="markdown-output">
        <ReactMarkdown remarkPlugins={[remarkBreaks]}>{value}</ReactMarkdown>
      </div>
    );
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return (
      <Text size="sm" style={{ color: "var(--hud-green)", fontFamily: "monospace" }}>
        {String(value)}
      </Text>
    );
  }
  if (Array.isArray(value)) {
    // Specialist results: array of [label, text] tuples — render as labeled sections
    const isTuplePairs = value.every(
      (v) => Array.isArray(v) && v.length === 2 && typeof v[0] === "string"
    );
    if (isTuplePairs) {
      return (
        <Stack gap="sm">
          {value.map(([label, content], i) => (
            <div key={i} style={{ borderLeft: "2px solid rgba(0,212,255,0.3)", paddingLeft: 8 }}>
              <Text size="xs" mb={4} style={{ color: "var(--hud-cyan)", letterSpacing: "1px", textTransform: "uppercase", fontSize: 10 }}>
                {label}
              </Text>
              {renderValue(content)}
            </div>
          ))}
        </Stack>
      );
    }
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
    return <JsonTree value={value} />;
  }
  return <JsonTree value={value} />;
}

export default function NodeOutputPanel({ nodeId, nodeOutputJson, nodeState, taskError, onClose }) {
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
  if (nodeOutputJson === undefined && nodeState === "failed") {
    return (
      <div style={{ padding: 12 }}>
        {header}
        <Badge color="hud-red" variant="light" mb="xs">Node failed</Badge>
        {taskError ? (
          <Code block style={{ fontSize: 10, color: "var(--hud-red)", backgroundColor: "rgba(255,61,61,0.05)", border: "1px solid rgba(255,61,61,0.2)", whiteSpace: "pre-wrap", marginTop: 4 }}>
            {taskError}
          </Code>
        ) : (
          <Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>No error details available</Text>
        )}
      </div>
    );
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
