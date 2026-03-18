# Lead Analyst Agent

Orchestrator agent that fans out work to N downstream sub-agents via A2A, collects their results in parallel, and uses an LLM meta-analyst to synthesize an aggregated report. Sub-agents are defined in `sub_agents.yaml`.

## Architecture

```
lead_analyst/
├── server.py          # FastAPI server, A2A routes, /graph endpoint
├── config.py          # YAML loading for sub-agent definitions
├── graph.py           # Dynamic LangGraph with N parallel sub-agent nodes
├── executor.py        # LeadAnalystExecutor (bridges A2A → LangGraph)
└── sub_agents.yaml    # Sub-agent definitions (label + URL pairs)
```

## Graph

```
receive → call_<sub_agent_1> ─┐
        → call_<sub_agent_2> ─┤→ aggregate → respond
        → ...                 ─┤
        → call_<sub_agent_N> ─┘
```

- **receive** — reads and validates input
- **call_\<sub_agent\>** — one per entry in `sub_agents.yaml`, all fan out in parallel
- **aggregate** — LLM-powered meta-analysis that synthesizes sub-agent results, identifying convergent, divergent, and complementary insights
- **respond** — formats the final output

The sub-agent nodes are dynamically generated from `sub_agents.yaml`. All fan out from `receive` and converge at `aggregate`.

## Sub-Agent Configuration

Define sub-agents in `sub_agents.yaml`:

```yaml
sub_agents:
  - label: ASEAN Security Analyst
    url: http://localhost:8006/asean-security
  - label: Realist IR Analyst
    url: http://localhost:8006/realist-ir
  - label: Taleb Antifragile Analyst
    url: http://localhost:8006/taleb-antifragile
```

Each entry becomes a parallel LangGraph node. The `label` is used in the aggregation prompt and the node name is derived from it (e.g. `call_asean_security_analyst`). The `url` points to any A2A-compliant agent endpoint.

## Running

```bash
OPENAI_API_KEY=sk-... python -m agents.lead_analyst.server
```

Default port: **8005**

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `LEAD_ANALYST_AGENT_URL` | No | `http://localhost:8005` | This agent's externally-reachable URL (used for self-registration) |
| `CONTROL_PLANE_URL` | No | — | Control plane URL for self-registration/deregistration |
| `OPENAI_API_KEY` | No | — | Required for LLM-powered aggregation (falls back to simple concatenation without it) |
| `OPENAI_BASE_URL` | No | OpenAI default | Custom OpenAI-compatible base URL |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | LLM model for aggregation |

Falls back to the generic `AGENT_URL` env var if `LEAD_ANALYST_AGENT_URL` is not set.

## Input

Single text field — the analysis request or text to process.

## Output

When `OPENAI_API_KEY` is set, produces an LLM-synthesized JSON report:

```json
{
  "synthesis": "3-5 paragraph narrative integrating all perspectives",
  "perspective_comparison": {
    "convergent_points": ["where frameworks agree"],
    "divergent_points": ["where frameworks disagree"],
    "complementary_insights": ["how frameworks illuminate different dimensions"]
  },
  "key_takeaways": ["actionable insights for decision-makers"],
  "recommended_actions": ["strategic recommendations"],
  "areas_for_further_research": ["critical unknowns"]
}
```

The aggregator automatically parses JSON analyses from specialist agents (extracting framework_name, key_findings, evidence, etc.) and falls back to plain-text inclusion for non-JSON results.

Without `OPENAI_API_KEY`, falls back to simple concatenation of sub-agent outputs.
