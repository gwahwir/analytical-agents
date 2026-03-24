# Lead Analyst Agent

Multi-instance orchestrator server that hosts N lead analyst agents from YAML configs. Each analyst fans out work to downstream sub-agents via A2A, collects their results in parallel, and uses an LLM meta-analyst to synthesize an aggregated report.

## Architecture

```
lead_analyst/
├── server.py              # Multi-mount FastAPI server
├── config.py              # YAML loading for analyst + sub-agent definitions
├── graph.py               # Dynamic LangGraph with N parallel sub-agent nodes
├── executor.py            # LeadAnalystExecutor (bridges A2A → LangGraph)
├── analyst_configs/       # YAML config files (one per analyst)
│   └── lead_analyst.yaml  # Default analyst (type_id: lead-analyst)
└── prompts/               # Custom aggregation prompts (referenced via aggregation_prompt_file)
```

## Graph

### Static Mode (YAML-defined sub-agents)

```
receive → call_<sub_agent_1> ─┐
        → call_<sub_agent_2> ─┤→ call_peripheral_scan → aggregate → call_ach_red_team → final_synthesis → respond
        → ...                 ─┤
        → call_<sub_agent_N> ─┘
```

### Dynamic Discovery Mode (LLM-selected specialists)

```
receive → discover_and_select → call_specialist (parallel) → call_peripheral_scan → aggregate → call_ach_red_team → final_synthesis → respond
                                       ↑___________________|
                                    (barrier: wait for all)
```

### Node Descriptions

**Core Nodes:**
- **receive** — reads and validates input, initializes state
- **call_\<sub_agent\>** (static mode) — one per sub-agent in YAML config, all fan out in parallel
- **discover_and_select** (dynamic mode) — fetches online specialists from control plane, LLM selects N most relevant
- **call_specialist** (dynamic mode) — shared node invoked once per selected specialist via Send API

**Meta-Analysis Pipeline:**
- **call_peripheral_scan** — identifies weak signals, blind spots, and uncited intelligence that domain specialists missed (runs BEFORE aggregation to catch collective blind spots early)
- **aggregate** — LLM-powered meta-analysis that synthesizes sub-agent results + peripheral findings into consensus
- **call_ach_red_team** — generates alternative hypotheses and challenges the aggregated consensus using Analysis of Competing Hypotheses (ACH) methodology
- **final_synthesis** — integrates consensus + peripheral findings + ACH challenges into a balanced assessment
- **respond** — formats the final output

## YAML Configuration

Each analyst is defined by a YAML file in `analyst_configs/`. The type ID is auto-derived from the filename (e.g., `geopolitical_analyst.yaml` → `geopolitical-analyst`).

### Static Mode Configuration

```yaml
name: Geopolitical Lead Analyst
description: Fans out to ASEAN, Realist IR, and Antifragile specialists

# Optional overrides
version: "0.1.0"
model: null                       # falls back to OPENAI_MODEL env
temperature: 0.3
max_completion_tokens: 4096

# Optional custom aggregation prompt (inline or file)
aggregation_prompt: null
aggregation_prompt_file: null     # relative to agents/lead_analyst/prompts/

# Required: at least one sub-agent (for static mode)
sub_agents:
  - label: ASEAN Security Analyst
    url: http://localhost:8006/asean-security
  - label: Realist IR Analyst
    url: http://localhost:8006/realist-ir

# Optional dashboard metadata
skills: []
input_fields:
  - name: text
    label: Analysis Request
    type: textarea
    required: true
    placeholder: Enter the text or request...
```

### Dynamic Discovery Mode Configuration

```yaml
name: Dynamic Intelligence Analyst
description: Dynamically selects relevant specialists from control plane

# Enable dynamic discovery
dynamic_discovery: true
control_plane_url: http://localhost:8000  # or set via CONTROL_PLANE_URL env var
min_specialists: 3                         # minimum number of specialists to select

# Sub-agents are optional in dynamic mode (will be selected at runtime)
sub_agents: []

# Other fields same as static mode
version: "0.1.0"
model: null
temperature: 0.3
max_completion_tokens: 4096

skills: []
input_fields:
  - name: text
    label: Analysis Request
    type: textarea
    required: true
    placeholder: Enter intelligence task or question...
  - name: baselines
    label: Current Baseline Assessments (optional)
    type: textarea
    required: false
    placeholder: Existing assessments to evaluate changes against...
  - name: key_questions
    label: Key Questions (optional)
    type: textarea
    required: false
    placeholder: Specific questions for specialists to address...
```

## Running

```bash
OPENAI_API_KEY=sk-... python -m agents.lead_analyst.server
```

Default port: **8005**

Each analyst is mounted at `/{type_id}/` (e.g., `/lead-analyst/`).

- `GET /` — lists all mounted analysts
- `GET /{type_id}/.well-known/agent-card.json` — agent card
- `GET /{type_id}/graph` — graph topology with downstream agents

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `LEAD_ANALYST_AGENT_URL` | No | `http://localhost:8005` | This server's externally-reachable base URL |
| `CONTROL_PLANE_URL` | No | — | Control plane URL for self-registration/deregistration (required for dynamic discovery mode) |
| `SPECIALIST_AGENT_URL` | No | `http://specialist-agent:8006` | Base URL for meta-analysis specialists (peripheral_scan, ach_red_team) |
| `OPENAI_API_KEY` | No | — | Required for LLM-powered aggregation, dynamic specialist selection, and final synthesis |
| `OPENAI_BASE_URL` | No | OpenAI default | Custom OpenAI-compatible base URL |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Default LLM model for aggregation (can be overridden per-analyst in YAML) |

Falls back to the generic `AGENT_URL` env var if `LEAD_ANALYST_AGENT_URL` is not set.

## Output

When `OPENAI_API_KEY` is set, the meta-analysis pipeline produces a comprehensive assessment:

### Final Output Structure

```json
{
  "synthesis": "3-5 paragraph narrative integrating all perspectives",
  "perspective_comparison": {
    "convergent_points": ["where frameworks agree - signals high confidence"],
    "divergent_points": ["where frameworks disagree - signals uncertainty"],
    "complementary_insights": ["how frameworks illuminate different dimensions"]
  },
  "key_takeaways": ["3-5 actionable insights for decision-makers"],
  "recommended_actions": ["3-5 strategic recommendations or considerations"],
  "areas_for_further_research": ["2-3 critical unknowns requiring deeper investigation"]
}
```

### Meta-Analysis Pipeline Stages

1. **Domain Specialists** — N specialists analyze from different theoretical frameworks
2. **Peripheral Scan** — Identifies weak signals and blind spots missed by domain specialists
3. **Aggregation** — Synthesizes domain analyses + peripheral findings into consensus
4. **ACH Red Team** — Generates alternative hypotheses and challenges consensus
5. **Final Synthesis** — Integrates consensus + peripheral + ACH into balanced assessment

Without `OPENAI_API_KEY`, falls back to simple concatenation of sub-agent outputs at each stage.

## Meta-Analysis Methodology

### Peripheral Scan
- **Purpose**: Catch weak signals BEFORE consensus solidifies
- **Focus**: Uncited intelligence, anomalies, cross-domain connections, framework blind spots
- **Output**: High-signal insights that would materially change the analysis

### ACH Red Team
- **Purpose**: Challenge the aggregated consensus
- **Methodology**: Analysis of Competing Hypotheses (ACH)
- **Output**: Alternative hypotheses (H2, H3, H4), disconfirming evidence, pre-mortem analysis

### Final Synthesis
- **Purpose**: Produce balanced assessment for decision-makers
- **Integration**: Preserves consensus where well-supported, flags alternatives worth monitoring, highlights uncertainties
- **Tone**: Balanced, acknowledges uncertainty, action-oriented
