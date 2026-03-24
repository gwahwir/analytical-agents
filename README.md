# Mission Control

A 3-tier A2A-compliant agent orchestration platform built with FastAPI, LangGraph, and React.

## Overview

Mission Control is a distributed agent orchestration system that enables dynamic task routing, load balancing, and real-time monitoring of LangGraph-based agents. The platform implements the Agent-to-Agent (A2A) communication protocol for standardized inter-agent messaging.

### Key Capabilities

**Orchestration & Scaling:**
- Async task dispatch (202 Accepted pattern)
- Horizontal scaling with least-active-tasks load balancing
- Self-registration & health monitoring (30s intervals)
- Dynamic agent discovery via control plane

**Advanced Analysis Pipeline:**
- **3-tier specialist architecture**: Domain (L1) → Peripheral Scanner (L2) → ACH Red Team (L3)
- **Parallel domain analysis**: 3-8 specialists called concurrently for speed
- **Sequential meta-analysis**: Systematic blind spot detection & consensus challenging
- **Balanced output**: Presents both primary assessment AND credible alternatives

**Developer Experience:**
- Real-time WebSocket streaming for task updates
- Graph topology introspection (`GET /graph`)
- Langfuse LLM tracing with span nesting
- PostgreSQL + Redis for multi-instance deployments

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              USER / CLIENT                               │
│                         (Dashboard / API Client)                         │
└────────────────┬───────────────────────────────────┬────────────────────┘
                 │                                   │
                 │ HTTP/WebSocket                    │ Poll /agents, /tasks
                 │                                   │ WebSocket /ws/tasks/:id
                 ▼                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          CONTROL PLANE (FastAPI)                         │
│                          http://localhost:8000                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌────────────────┐  ┌──────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │    Registry    │  │  Task Store  │  │   Pub/Sub   │  │ A2A Client │ │
│  │                │  │              │  │             │  │            │ │
│  │ • Health check │  │ • In-memory  │  │ • WS fanout │  │ • JSON-RPC │ │
│  │ • Load balance │  │ • PostgreSQL │  │ • Redis pub │  │ • message/ │ │
│  │ • Auto-register│  │              │  │             │  │   send     │ │
│  └────────────────┘  └──────────────┘  └─────────────┘  └────────────┘ │
│                                                                           │
│  Routes:                                                                  │
│  • POST   /agents/:id/tasks  → 202 Accepted (async dispatch)            │
│  • GET    /tasks/:id          → Task status & output                     │
│  • DELETE /tasks/:id          → Cancel task                              │
│  • GET    /agents             → List registered agents                   │
│  • GET    /graph              → Aggregated agent topology                │
│  • WS     /ws/tasks/:id       → Live task updates                        │
│                                                                           │
└────────────────┬──────────────────────────────────────┬─────────────────┘
                 │                                      │
                 │ A2A JSON-RPC                         │ Self-register
                 │ (message/send)                       │ on startup
                 ▼                                      │
┌─────────────────────────────────────────────────────────────────────────┐
│                          AGENT LAYER (LangGraph)                         │
│                       Wrapped with a2a-sdk HTTP servers                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │  Echo Agent  │  │ Summarizer   │  │  Relevancy   │  │ Extraction  │ │
│  │  :8001       │  │  :8002       │  │  :8003       │  │  :8004      │ │
│  │              │  │              │  │              │  │             │ │
│  │ • Uppercase  │  │ • LLM        │  │ • LLM        │  │ • LLM       │ │
│  │ • Forward    │  │ • Summarize  │  │ • Relevance  │  │ • Extract   │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────┘ │
│                                                                           │
│  ┌──────────────────┐  ┌────────────────┐  ┌────────────────────────┐  │
│  │  Lead Analyst    │  │  Specialist    │  │  Probability Agent     │  │
│  │  :8005           │  │  :8006         │  │  :8007                 │  │
│  │                  │  │                │  │                        │  │
│  │ Multi-instance:  │  │ Multi-agent:   │  │ • Aggregation         │  │
│  │ • 3 leads (A/B/C)│  │ • 16 geopolit. │  │ • Disagreement detect │  │
│  │ • Fan-out to     │◄─┤   intelligence │◄─┤ • Peripheral scan     │  │
│  │   specialists    │  │   specialists  │  │ • Tail-risk reserves  │  │
│  │ • Aggregate      │  │                │  │ • Equal-weighted avg  │  │
│  └──────────────────┘  └────────────────┘  └────────────────────────┘  │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker & Docker Compose (optional)

### Local Development

```bash
# Install Python dependencies
pip install -r requirements.txt

# Start the full stack (control plane + all agents + dashboard)
bash run-local.sh

# Or start components individually:
python -m control_plane.server                    # Control plane on :8000
python -m agents.echo.server                       # Echo agent on :8001
OPENAI_API_KEY=sk-... python -m agents.summarizer.server  # Summarizer on :8002
```

### Docker

```bash
# Start everything
OPENAI_API_KEY=sk-... docker compose up

# Scale an agent horizontally
docker compose up --scale echo-agent=3
```

**Dashboard:** http://localhost:5173
**Control Plane API:** http://localhost:8000
**API Docs:** http://localhost:8000/docs

## Workflows

### 1. Task Lifecycle

```
┌──────────┐
│  CLIENT  │
└────┬─────┘
     │
     │ POST /agents/:id/tasks
     │ {"input": "analyze this"}
     ▼
┌─────────────────┐
│ CONTROL PLANE   │
│                 │
│ 1. Create task  │      ┌──────────────────────────────────┐
│    id: task-123 │      │    TASK STATE MACHINE            │
│    state: submitted    │                                  │
│                 │      │  submitted → working → completed │
│ 2. Return 202   │      │                ↓          ↓      │
└────┬────────────┘      │           input-required  failed │
     │                   │                ↓          ↓      │
     │ 202 Accepted      │             canceled   canceled  │
     │ task_id: task-123 └──────────────────────────────────┘
     ▼
┌──────────┐
│  CLIENT  │─────────┐
└──────────┘         │
                     │ Poll GET /tasks/task-123
                     │ or WebSocket /ws/tasks/task-123
                     ▼
              ┌──────────────┐
              │ LIVE UPDATES │
              │              │
              │ • Node start │
              │ • Progress   │
              │ • Completion │
              └──────────────┘
```

#### State Transitions

```
submitted ──────────────► working ──────────────► completed
                              │                        ▲
                              │                        │
                              ├──► input-required ─────┤
                              │                        │
                              ├──► failed              │
                              │                        │
                              └──► canceled ◄──────────┘
                                        ▲
                                        │
                                   DELETE /tasks/:id
```

### 2. Agent Registration Flow

```
┌─────────────┐                              ┌─────────────────┐
│   AGENT     │                              │ CONTROL PLANE   │
│   STARTUP   │                              │                 │
└──────┬──────┘                              └────────┬────────┘
       │                                              │
       │ 1. Agent starts                              │
       │    Reads CONTROL_PLANE_URL                   │
       │                                              │
       │ 2. POST /register                            │
       │    {                                         │
       │      "type_name": "echo-agent",              │
       │      "agent_url": "http://localhost:8001"    │
       │    }                                         │
       ├─────────────────────────────────────────────►│
       │                                              │
       │                                     3. Store in registry
       │                                        Start health check
       │                                              │
       │ 4. 200 OK                                    │
       │◄─────────────────────────────────────────────┤
       │                                              │
       │                                              │
       │         5. Health checks (every 30s)         │
       │         GET /.well-known/agent-card.json     │
       │◄─────────────────────────────────────────────┤
       │                                              │
       │         200 OK                               │
       ├─────────────────────────────────────────────►│
       │                                              │
       │                                              │
       │ 6. Agent shutdown signal                     │
       │    POST /deregister                          │
       │    {"type_name": "echo-agent",               │
       │     "agent_url": "http://localhost:8001"}    │
       ├─────────────────────────────────────────────►│
       │                                              │
       │                                     7. Remove from registry
       │                                        Stop health checks
       │                                              │
       │ 8. 200 OK                                    │
       │◄─────────────────────────────────────────────┤
       │                                              │
```

### 3. Lead Analyst Orchestration

The Lead Analyst demonstrates complex multi-agent orchestration:

```
┌────────────────────────────────────────────────────────────────────────────┐
│              LEAD ANALYST WORKFLOW (Dynamic Discovery Mode)                │
│  Sequential Meta-Analysis Pipeline: Domain → Peripheral → ACH → Synthesis  │
└────────────────────────────────────────────────────────────────────────────┘

         ┌──────────────────────┐
         │       receive        │
         │ Input: text          │
         │   + baselines (opt)  │
         │   + key_questions    │
         └──────────┬───────────┘
                    │
                    ▼
         ┌───────────────────────────────────────────────┐
         │         discover_and_select                   │
         │                                               │
         │ 1. GET /agents from control plane             │
         │ 2. Filter online DOMAIN specialists           │
         │    (excludes meta-specialists L2/L3)          │
         │ 3. LLM selects 3-8 most relevant              │
         │    based on input + baselines                 │
         └──────────┬────────────────────────────────────┘
                    │
                    ▼
         ┌───────────────────────────────────────────────┐
         │      call_specialist (parallel)               │
         │                                               │
         │  Send() to each selected DOMAIN specialist    │
         │  Concurrent A2A calls via LangGraph           │
         │  ┌─────────┐  ┌─────────┐  ┌─────────┐       │
         │  │ Realist │  │  ASEAN  │  │ Climate │       │
         │  │   IR    │  │Security │  │Security │  ...  │
         │  │  :8006  │  │  :8006  │  │  :8006  │       │
         │  └────┬────┘  └────┬────┘  └────┬────┘       │
         │       └────────────┴─────────────┘            │
         │           All results in state.results        │
         └──────────┬────────────────────────────────────┘
                    │
                    ▼
         ┌───────────────────────────────────────────────┐
         │         aggregate (LLM Meta-Analyst)          │
         │  Synthesizes domain specialist outputs        │
         │                                               │
         │  • Identify convergent points                 │
         │  • Identify divergent points                  │
         │  • Synthesize complementary insights          │
         │  • Generate key takeaways                     │
         │  • Recommend actions                          │
         │  • Flag research gaps                         │
         │                                               │
         │  Output → state.aggregated_consensus          │
         └──────────┬────────────────────────────────────┘
                    │
                    │ Meta-Analysis Pipeline (Sequential)
                    ▼
         ┌───────────────────────────────────────────────┐
         │      call_peripheral_scan (L2)                │
         │  Identifies what domain specialists MISSED    │
         │                                               │
         │  Input: raw docs + domain summaries           │
         │  Detects:                                     │
         │  • Uncited intelligence (not in any analysis) │
         │  • Weak signals & anomalies                   │
         │  • Cross-domain connections                   │
         │  • Framework blind spots                      │
         │  • Gaps in addressing key questions           │
         │                                               │
         │  Output → state.peripheral_findings           │
         └──────────┬────────────────────────────────────┘
                    │
                    ▼
         ┌───────────────────────────────────────────────┐
         │       call_ach_red_team (L3)                  │
         │  Challenges aggregated consensus              │
         │                                               │
         │  Input: consensus + peripheral findings       │
         │  + key questions                              │
         │  Generates:                                   │
         │  • Alternative hypotheses (H2, H3, H4)        │
         │  • Disconfirming evidence for consensus       │
         │  • Pre-mortem: "If we're wrong, what missed?" │
         │  • Challenges to question framing itself      │
         │  • Peripheral signals supporting alternatives │
         │                                               │
         │  Output → state.ach_analysis                  │
         └──────────┬────────────────────────────────────┘
                    │
                    ▼
         ┌───────────────────────────────────────────────┐
         │         final_synthesis (LLM)                 │
         │  Integrates red team challenges               │
         │                                               │
         │  Input: consensus + ACH challenges            │
         │  Produces balanced assessment:                │
         │  • Executive Summary                          │
         │  • Primary Assessment (consensus view)        │
         │  • Alternative Hypotheses Worth Monitoring    │
         │  • Key Uncertainties & Disconfirming Evidence │
         │  • Recommended Actions                        │
         │                                               │
         │  Output → state.output (final JSON report)    │
         └──────────┬────────────────────────────────────┘
                    │
                    ▼
         ┌───────────────────────┐
         │       respond         │
         │  Returns final output │
         └──────────┬────────────┘
                    │
                    ▼
               ┌─────────┐
               │   END   │
               └─────────┘

┌────────────────────────────────────────────────────────────────────┐
│              LEAD ANALYST WORKFLOW (Static Config Mode)            │
│              Same Meta-Analysis Pipeline, Pre-configured URLs      │
└────────────────────────────────────────────────────────────────────┘

         ┌──────────────────────┐
         │       receive        │
         └──────────┬───────────┘
                    │
         ┌──────────┼──────────┐  (Parallel calls to
         │          │          │   YAML-defined domain
         ▼          ▼          ▼   specialists)
    ┌────────┐ ┌────────┐ ┌────────┐
    │Domain  │ │Domain  │ │Domain  │
    │Spec #1 │ │Spec #2 │ │Spec #N │
    └───┬────┘ └───┬────┘ └───┬────┘
        └──────────┴──────────┘
                   │
                   ▼
         ┌──────────────────┐
         │    aggregate     │ → aggregated_consensus
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │  peripheral_scan │ → peripheral_findings
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │   ach_red_team   │ → ach_analysis
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ final_synthesis  │ → output
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │     respond      │
         └────────┬─────────┘
                  │
                  ▼
             ┌────────┐
             │  END   │
             └────────┘
```

#### Specialist Categorization & Selection

The system uses a **3-tier specialist architecture**:

**L1: Domain Specialists** (Selected by LLM, called in parallel)
- Geopolitical frameworks, regional experts, thought leaders
- LLM selects 3-8 most relevant based on query
- Called concurrently to generate diverse analytical perspectives

**L2: Peripheral Scanner** (Always called sequentially after L1)
- Identifies collective blind spots across all domain analyses
- Detects weak signals, uncited intelligence, cross-domain connections
- Tagged with `specialist_L2` to exclude from LLM selection

**L3: ACH Red Team** (Always called sequentially after L2)
- Challenges aggregated consensus with alternative hypotheses
- Identifies disconfirming evidence and question-framing issues
- Tagged with `specialist_L3` to exclude from LLM selection

```
Specialist Agent (:8006) hosts 16 geopolitical/intelligence specialists:

┌────────────────────────────────────────────────────────────┐
│  META-SPECIALISTS (L2/L3) - Sequential Pipeline            │
├────────────────────────────────────────────────────────────┤
│ • peripheral-scan (L2)         │  Blind spots & uncited    │
│                                │  intelligence detection   │
│ • ach-red-team (L3)            │  Analysis of Competing    │
│                                │  Hypotheses & red teaming │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  DOMAIN SPECIALISTS (L1) - LLM Selected & Parallel         │
├────────────────────────────────────────────────────────────┤
│ ANALYTICAL METHODOLOGIES:                                  │
│ • behavioral-economics         │  Cognitive biases &       │
│                                │  decision-making patterns │
│ • counterfactual-thinking      │  Alternative history &    │
│                                │  what-if scenarios        │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  INTERNATIONAL RELATIONS FRAMEWORKS                        │
├────────────────────────────────────────────────────────────┤
│ • realist-ir                   │  Power politics & state   │
│                                │  interests (realism)      │
│ • liberal-ir                   │  Institutions & norms     │
│                                │  (liberal IR theory)      │
│ • copenhagen-securitization    │  Security construction &  │
│                                │  speech-act theory        │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  DOMAIN EXPERTS                                            │
├────────────────────────────────────────────────────────────┤
│ • asean-security               │  Southeast Asia security  │
│ • climate-security             │  Climate & environmental  │
│                                │  security nexus           │
│ • economic-statecraft          │  Economic tools of power  │
│ • military-strategy-deterrence │  Military doctrine &      │
│                                │  deterrence theory        │
│ • technology-emerging-threats  │  Tech disruption & cyber  │
│                                │  threats                  │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  THOUGHT LEADERS                                           │
├────────────────────────────────────────────────────────────┤
│ • bilahari-kausikan            │  Singaporean diplomat &   │
│                                │  strategic realist        │
│ • bridget-welsh                │  Southeast Asia politics  │
│                                │  expert                   │
│ • taleb-antifragile            │  Antifragility, black     │
│                                │  swans, tail risks        │
│ • yergin-energy                │  Energy geopolitics &     │
│                                │  resource security        │
└────────────────────────────────────────────────────────────┘

**Selection Process:**
1. **discover_and_select** filters out L2/L3 meta-specialists
2. LLM selects 3-8 L1 domain specialists based on query relevance
3. Domain specialists called in parallel (concurrent A2A)
4. Meta-specialists always called sequentially: L2 → L3

Each domain specialist returns structured JSON with key findings,
evidence, predictions, limitations, and confidence levels.

**Deployment Variants:**
• Lead Analyst A: Docker deployment with static specialist URLs
• Lead Analyst B: Local dev with localhost specialist URLs
• Lead Analyst C: Dynamic specialist discovery via control plane

**Pipeline Execution:**
- Domain specialists analyze in parallel (speed)
- Meta-specialists run sequentially (each builds on prior outputs)
- Final synthesis integrates all layers into balanced assessment

**Note:** The Probability Agent (:8007) is separate and not part of
the Lead Analyst workflow. It can be called independently for
probability aggregation, but is NOT automatically invoked.
```

### 4. Meta-Analysis Pipeline (Lead Analyst)

The Lead Analyst uses a **sequential meta-analysis pipeline** to detect blind spots and challenge consensus:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    META-ANALYSIS PIPELINE FLOW                      │
└─────────────────────────────────────────────────────────────────────┘

LAYER 1: Domain Analysis (Parallel)
┌──────────────────────────────────────────────────────────┐
│  Domain Specialist #1  │  Domain Specialist #2  │ ...   │
│  (e.g., Realist IR)    │  (e.g., ASEAN Security)│       │
│  ┌──────────────────┐  │  ┌──────────────────┐  │       │
│  │ • Key findings   │  │  │ • Key findings   │  │       │
│  │ • Evidence cited │  │  │ • Evidence cited │  │       │
│  │ • Predictions    │  │  │ • Predictions    │  │       │
│  │ • Limitations    │  │  │ • Limitations    │  │       │
│  └──────────────────┘  │  └──────────────────┘  │       │
└──────────────────────────────────────────────────────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │    AGGREGATION      │  Synthesizes domain analyses:
              │   (LLM Synthesis)   │  • Convergent points
              │                     │  • Divergent points
              └──────────┬──────────┘  • Complementary insights
                         │
                         │ aggregated_consensus
                         ▼
─────────────────────────────────────────────────────────────────────
LAYER 2: Peripheral Scan (Sequential)
┌─────────────────────────────────────────────────────────────────┐
│              PERIPHERAL SCANNER (L2)                            │
│                                                                 │
│  Inputs:                                                        │
│  • Original documents (raw intelligence)                       │
│  • Domain specialist summaries (what was analyzed)            │
│  • Key questions (what should be answered)                     │
│                                                                 │
│  Detection Methodology:                                         │
│  ┌────────────────────────────────────────────────────┐       │
│  │ 1. Uncited Intelligence Scan                       │       │
│  │    → Find relevant intel NO domain specialist cited│       │
│  │                                                     │       │
│  │ 2. Weak Signal Detection                           │       │
│  │    → Identify anomalies & early warnings          │       │
│  │                                                     │       │
│  │ 3. Cross-Domain Connection Mapping                 │       │
│  │    → Link insights across specialist boundaries    │       │
│  │                                                     │       │
│  │ 4. Framework Blind Spot Analysis                   │       │
│  │    → Identify what frameworks can't see            │       │
│  │                                                     │       │
│  │ 5. Question Coverage Gap Analysis                  │       │
│  │    → Find key questions not fully addressed        │       │
│  └────────────────────────────────────────────────────┘       │
│                                                                 │
│  Output → peripheral_findings (what domain missed)             │
└─────────────────────────────────────────────────────────────────┘
                         │
                         │ peripheral_findings
                         ▼
─────────────────────────────────────────────────────────────────────
LAYER 3: ACH Red Team (Sequential)
┌─────────────────────────────────────────────────────────────────┐
│              ACH RED TEAM CHALLENGER (L3)                       │
│          Analysis of Competing Hypotheses + Pre-Mortem          │
│                                                                 │
│  Inputs:                                                        │
│  • aggregated_consensus (what domain specialists believe)      │
│  • peripheral_findings (what was missed)                       │
│  • key_questions (what decision-makers asked)                  │
│                                                                 │
│  Challenge Methodology:                                         │
│  ┌────────────────────────────────────────────────────┐       │
│  │ 1. Identify Consensus Hypothesis (H1)              │       │
│  │    → Extract core claim from aggregated consensus  │       │
│  │                                                     │       │
│  │ 2. Generate Alternative Hypotheses (H2, H3, H4)    │       │
│  │    → Create 3-4 plausible competing explanations  │       │
│  │                                                     │       │
│  │ 3. Disconfirming Evidence Analysis                 │       │
│  │    → What evidence contradicts H1?                 │       │
│  │                                                     │       │
│  │ 4. Peripheral Signal Integration                   │       │
│  │    → Do weak signals support alternatives?         │       │
│  │                                                     │       │
│  │ 5. Question Framing Challenge                      │       │
│  │    → Are we asking the RIGHT questions?            │       │
│  │                                                     │       │
│  │ 6. Pre-Mortem: "If H1 is wrong, what did we miss?"│       │
│  │    → Assume failure, work backwards               │       │
│  └────────────────────────────────────────────────────┘       │
│                                                                 │
│  Output → ach_analysis (red team challenges)                   │
└─────────────────────────────────────────────────────────────────┘
                         │
                         │ ach_analysis
                         ▼
─────────────────────────────────────────────────────────────────────
FINAL SYNTHESIS (LLM Integration)
┌─────────────────────────────────────────────────────────────────┐
│  Inputs: aggregated_consensus + ach_analysis                    │
│                                                                 │
│  Balanced Assessment Structure:                                 │
│  ┌────────────────────────────────────────────────────┐       │
│  │ • Executive Summary (2-3 sentences)                │       │
│  │ • Primary Assessment (consensus view, where solid) │       │
│  │ • Alternative Hypotheses Worth Monitoring (from ACH)│      │
│  │ • Key Uncertainties & Disconfirming Evidence       │       │
│  │ • Recommended Actions (acknowledging alternatives) │       │
│  └────────────────────────────────────────────────────┘       │
│                                                                 │
│  Tone: Balanced, acknowledges uncertainty, action-oriented     │
│                                                                 │
│  Output → final JSON report with both consensus & alternatives │
└─────────────────────────────────────────────────────────────────┘
```

**Key Principles:**

1. **Parallel Domain Analysis** — Speed: Get diverse perspectives concurrently
2. **Sequential Meta-Analysis** — Depth: Each layer builds on previous outputs
3. **Epistemic Humility** — No single framework has monopoly on truth
4. **Intellectual Honesty** — Present both consensus AND credible alternatives
5. **Actionability** — Decision-makers need clarity, not just debate

**Why Sequential Meta-Analysis?**

- **Peripheral Scanner (L2)** needs domain analyses to identify what's missing
- **ACH Red Team (L3)** needs consensus + peripheral findings to generate alternatives
- **Final Synthesis** integrates all layers into balanced assessment

This architecture prevents "groupthink" by systematically challenging consensus while maintaining analytical rigor.

### 5. Load Balancing

```
┌─────────────────────────────────────────────────────────────────┐
│                      REGISTRY LOAD BALANCER                     │
└─────────────────────────────────────────────────────────────────┘

Task arrives for type_id: "echo-agent"
              │
              ▼
     ┌────────────────┐
     │  Query registry│
     │  for instances │
     └────────┬───────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│  Found 3 instances:                                     │
│                                                         │
│  echo-001  http://localhost:8001  active_tasks: 2      │
│  echo-002  http://localhost:8002  active_tasks: 5      │
│  echo-003  http://localhost:8003  active_tasks: 1  ← SELECTED
│                                                         │
│  Strategy: Least active tasks                          │
└─────────────────────────────────────────────────────────┘
              │
              ▼
     ┌────────────────┐
     │ Route to       │
     │ echo-003       │
     │ Increment count│
     └────────┬───────┘
              │
              ▼
     ┌────────────────┐
     │ A2A message    │
     │ POST /execute  │
     └────────────────┘
```

## Key Features

### A2A Protocol Compliance
- **JSON-RPC 2.0** message format
- Standard `message/send` method for task submission
- `tasks/cancel` for mid-run cancellation
- Agent cards at `/.well-known/agent-card.json`
- Streaming support via Server-Sent Events (SSE)
- Cross-agent communication via control plane routing

### Async Task Execution
- Tasks return 202 Accepted immediately
- Background execution via asyncio
- Non-blocking agent operations

### Dynamic Agent Discovery
- Self-registration on startup
- Health monitoring (30s intervals)
- Auto-removal on failure
- Manual registration via `AGENT_URLS`

### Real-time Updates
- WebSocket subscriptions per task
- Pub/sub via in-memory queues or Redis
- TaskStatusUpdateEvent at each graph node

### Horizontal Scaling
- Multiple instances per agent type
- Least-active-tasks load balancing
- Stateless agent design

### Task Cancellation
- Mid-run cancellation support
- Asyncio event-based signaling
- Graceful cleanup in graph nodes

### Observability
- **Langfuse integration** for LLM tracing with span nesting
- **OpenAI instrumentation** via LangchainCallbackHandler
- Structured logging with configurable `LOG_LEVEL`
- Graph topology introspection via `/graph` endpoints
- Per-node status updates via TaskStatusUpdateEvent
- WebSocket live streaming for real-time monitoring

## Agent Details

| Agent | Port | Type ID | Description |
|-------|------|---------|-------------|
| **Echo** | 8001 | `echo-agent` | Reference implementation, uppercases input, optional forwarding |
| **Summarizer** | 8002 | `summarizer` | OpenAI-powered text summarization |
| **Relevancy** | 8003 | `relevancy` | Assesses relevance to a question, returns JSON verdict |
| **Extraction** | 8004 | `extraction` | Extracts entities, events, relationships from text |
| **Lead Analyst** | 8005 | per-YAML | Multi-instance orchestrator with 3-tier meta-analysis: (L1) Parallel domain specialists → (L2) Peripheral scanner → (L3) ACH red team → Final synthesis |
| **Specialist** | 8006 | per-YAML | Hosts 16 geopolitical specialists: 14 domain (L1) + 2 meta-specialists (L2/L3) for blind spot detection & consensus challenging |
| **Probability** | 8007 | `probability-forecaster` | Equal-weighted aggregation, disagreement detection, peripheral scanning, tail-risk reserves |

See each agent's README for detailed documentation.

## Environment Variables

### Control Plane

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_URLS` | `http://localhost:8001` | Comma-separated agent URLs (`name@url` format supported) |
| `DATABASE_URL` | None | PostgreSQL DSN for persistent task storage |
| `REDIS_URL` | None | Redis URL for multi-instance WebSocket pub/sub |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

### Agents

Each agent has its own URL variable (e.g., `ECHO_AGENT_URL`, `SUMMARIZER_AGENT_URL`), falling back to `AGENT_URL`, then `http://localhost:<port>`.

**Shared variables:**
- `CONTROL_PLANE_URL` - For self-registration (all agents)
- `OPENAI_API_KEY` - Required for LLM-based agents (summarizer, relevancy, extraction, lead analyst, specialist, probability)
- `OPENAI_BASE_URL` - Custom OpenAI-compatible endpoint
- `OPENAI_MODEL` - Default: `gpt-4o-mini`
- `LANGFUSE_PUBLIC_KEY` - Optional, for LLM tracing
- `LANGFUSE_SECRET_KEY` - Optional, for LLM tracing
- `LANGFUSE_HOST` - Optional, Langfuse server URL

**Echo Agent specific:**
- `DOWNSTREAM_AGENT_URL` - Optional URL to forward output to another agent

## API Examples

### Submit a Task

```bash
curl -X POST http://localhost:8000/agents/echo-agent/tasks \
  -H "Content-Type: application/json" \
  -d '{"input": "hello world"}'

# Response: 202 Accepted
{
  "task_id": "task-123",
  "state": "submitted"
}
```

### Get Task Status

```bash
curl http://localhost:8000/tasks/task-123

# Response:
{
  "task_id": "task-123",
  "state": "completed",
  "output": "HELLO WORLD",
  "created_at": "2026-03-23T12:00:00Z",
  "updated_at": "2026-03-23T12:00:05Z"
}
```

### WebSocket Updates

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/tasks/task-123');
ws.onmessage = (event) => {
  const update = JSON.parse(event.data);
  console.log(`State: ${update.state}, Node: ${update.current_node}`);
};
```

### List Agents

```bash
curl http://localhost:8000/agents

# Response:
[
  {
    "agent_id": "echo-001",
    "type_id": "echo-agent",
    "url": "http://localhost:8001",
    "active_tasks": 2,
    "last_health_check": "2026-03-23T12:00:00Z"
  }
]
```

## How Components Interact

### Example: Full Intelligence Analysis Flow

```
1. CLIENT submits task to Control Plane
   POST /agents/lead-analyst-c/tasks
   {
     "text": "Analyze South China Sea tensions...",
     "baselines": "Current assessment: escalation low...",
     "key_questions": "What weak signals indicate change?"
   }

2. CONTROL PLANE routes to Lead Analyst C (dynamic discovery)
   - Creates task_id, state: submitted
   - Returns 202 Accepted
   - Dispatches background asyncio task

3. LEAD ANALYST C executes graph
   a) discover_and_select:
      - GET /agents from control plane
      - Filters to L1 domain specialists only (excludes L2/L3)
      - LLM selects 5 relevant: [realist-ir, asean-security,
        military-strategy, climate-security, economic-statecraft]

   b) call_specialist (parallel):
      - 5 concurrent A2A calls to Specialist Agent (:8006)
      - Each specialist analyzes via their framework
      - Results gathered in state.results

   c) aggregate:
      - LLM synthesizes 5 domain analyses
      - Identifies convergent/divergent points
      - Output → state.aggregated_consensus

   d) call_peripheral_scan (L2):
      - A2A call to peripheral-scan specialist
      - Input: raw docs + domain summaries + key questions
      - Detects uncited intel & collective blind spots
      - Output → state.peripheral_findings

   e) call_ach_red_team (L3):
      - A2A call to ach-red-team specialist
      - Input: consensus + peripheral findings
      - Generates alternative hypotheses (H2, H3, H4)
      - Identifies disconfirming evidence
      - Output → state.ach_analysis

   f) final_synthesis:
      - LLM integrates consensus + ACH challenges
      - Produces balanced assessment with alternatives
      - Output → state.output (final JSON)

   g) respond:
      - Returns final output to control plane

4. CONTROL PLANE updates task
   - state: completed
   - output_text: final JSON report
   - WebSocket subscribers receive update

5. CLIENT polls or receives WebSocket notification
   GET /tasks/task-123
   {
     "state": "completed",
     "output": {
       "synthesis": "...",
       "perspective_comparison": {...},
       "key_takeaways": [...],
       "alternative_hypotheses": [...],
       "recommended_actions": [...]
     }
   }
```

**Key Observations:**

- **L1 Domain Specialists**: Selected dynamically, run in parallel (speed)
- **L2 Peripheral Scanner**: Always called, runs sequentially (needs domain results)
- **L3 ACH Red Team**: Always called, runs sequentially (needs consensus + peripheral)
- **All communication**: Via A2A JSON-RPC (standardized, traceable)
- **State machine**: submitted → working → completed (WebSocket updates at each node)

## Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_task_lifecycle.py -v

# Run single test
pytest tests/test_task_lifecycle.py::test_task_submission -v
```

Tests use `pytest-httpx` to mock A2A HTTP calls. See `tests/conftest.py` for fixtures.

## Development

### Adding a New Agent

1. **Create graph** in `agents/<name>/graph.py` with `check_cancelled()` in each node
2. **Create executor** in `agents/<name>/executor.py` (subclass `LangGraphA2AExecutor`)
3. **Create server** in `agents/<name>/server.py` with:
   - A2A HTTP server on new port
   - Lifespan events for register/deregister
   - `/graph` endpoint with `INPUT_FIELDS`
4. **Document** in `agents/<name>/README.md`
5. **Add Docker** config in `Dockerfile.<name>` and `docker-compose.yml`
6. **Update** `run-local.sh`

### Project Structure

```
mission-control/
├── control_plane/          # FastAPI orchestration layer
│   ├── server.py           # Main server + routes
│   ├── registry.py         # Agent registry + load balancer
│   ├── task_store.py       # Task persistence (in-memory/PostgreSQL)
│   ├── pubsub.py           # WebSocket pub/sub (in-memory/Redis)
│   └── a2a_client.py       # A2A JSON-RPC client
├── agents/
│   ├── base/               # Shared base classes
│   │   ├── executor.py     # LangGraphA2AExecutor
│   │   ├── cancellation.py # CancellableMixin
│   │   └── registration.py # Self-registration helpers
│   ├── echo/               # Reference agent
│   ├── summarizer/         # LLM summarization
│   ├── relevancy/          # Relevance assessment
│   ├── extraction_agent/   # Entity extraction
│   ├── lead_analyst/       # Multi-analyst orchestrator
│   ├── specialist_agent/   # 16 LLM specialists
│   └── probability_agent/  # Probability aggregation
├── dashboard/              # React SPA
│   ├── src/
│   │   ├── components/     # UI components
│   │   ├── hooks/          # useApi, useWebSocket
│   │   └── pages/          # TaskList, AgentGraph
│   └── vite.config.js      # Proxy config
├── tests/                  # pytest tests
├── docker-compose.yml      # Full stack deployment
└── run-local.sh            # Local development script
```

## License

MIT

## Contributing

See [CLAUDE.md](CLAUDE.md) for development guidelines and architecture details.
