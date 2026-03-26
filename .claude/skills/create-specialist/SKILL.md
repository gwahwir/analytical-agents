---
name: create-specialist
description: Generate a new specialist agent by creating a YAML config and system prompt file
user_invocable: true
---

# Create a New Specialist Agent

You are generating a new specialist agent for the Mission Control platform. The user will describe the analytical framework, persona, or domain expertise they want. You will create two files:

1. A YAML config in `agents/specialist_agent/agent_cards/<type_id>.yaml`
2. A system prompt in `agents/specialist_agent/prompts/<type_id>.md`

## Step 1: Gather Requirements

Ask the user (if not already provided):
- What analytical framework, persona, or domain should the agent embody?
- Any specific methodologies, theories, or mental models it should apply?
- Any particular tone or personality? (e.g., adversarial, diplomatic, clinical)

If the user gave a clear description, proceed without asking.

## Step 2: Derive the type_id

Convert the agent concept to a snake_case filename. Examples:
- "game theory analyst" → `game_theory.yaml` / `game_theory.md`
- "Marxist political economy" → `marxist_political_economy.yaml` / `marxist_political_economy.md`

The `type_id` is auto-derived from the filename: underscores become hyphens, lowercased. So `game_theory.yaml` → type_id `game-theory`.

## Step 3: Write the System Prompt (.md file)

Create `agents/specialist_agent/prompts/<name>.md` following this structure. Study the examples below carefully — the quality of the prompt is critical.

### Required Sections

```markdown
# Agent Configuration: <Persona Title> (<Short Code>)

## 1. Core Identity & Philosophy

You are **<Persona Name>**, a <role description>.

**Identity:**
- <2-3 bullet points defining who this agent is, its intellectual tradition, and core beliefs>

## 2. Analytical Pillars (The <Framework> Framework)

When analyzing any scenario, apply these filters:

| Filter | Description | Concept |
|--------|-------------|---------|
| **<Filter 1>** | <description> | <source concept/quote> |
| **<Filter 2>** | <description> | <source concept/quote> |
| ... | ... | ... |

## 3. Response Heuristics (How You Think and Speak)

**Tone:** <describe the analytical tone>

**Key Phrases to Use:**
- "<characteristic phrase 1>"
- "<characteristic phrase 2>"
- ...

**Decision Logic:**
- <key decision rules the agent follows>

## 4. Analytical Protocol

For every document/scenario, evaluate:

1. **<Step 1 Name>**: <what to assess>
2. **<Step 2 Name>**: <what to assess>
3. ...

## 5. Confidence & Limitations

**Confidence:** <what the agent is confident about>

**Limitations:** You acknowledge that:
- <limitation 1>
- <limitation 2>
- <limitation 3>

---

**Remember:** <one-line closing directive>
```

### Quality Guidelines

- **Be deeply specific.** Don't write generic "analyze the situation" instructions. Ground every section in the actual intellectual framework — cite real concepts, real thinkers, real methodologies.
- **Give the agent a voice.** The key phrases and tone section should make the agent sound distinctive, not like a generic assistant.
- **Include decision logic.** The agent should have clear rules for how it makes judgments, not just "analyze carefully."
- **Aim for 50-100 lines.** Enough depth to be useful, not so long it dilutes focus.
- **The prompt should teach the framework.** An LLM reading this prompt should be able to apply the framework correctly even if it has never seen it before.

## Step 4: Write the YAML Config

Create `agents/specialist_agent/agent_cards/<name>.yaml` with this exact structure:

```yaml
name: <Agent Display Name>
description: <One-line description of what this agent does>
version: "0.1.0"

system_prompt_file: <name>.md

output_format: |
  Provide your analysis as JSON with this structure:
  {
    "framework_name": "your framework name",
    "summary": "2-3 sentence executive summary",
    "key_findings": ["finding 1", "finding 2", ...],
    "evidence": ["evidence 1", "evidence 2", ...],
    "predictions": ["prediction 1", "prediction 2", ...],
    "limitations": "acknowledged limitations of this lens",
    "confidence_level": "High/Medium/Low"
  }
  Apply your theoretical framework rigorously. Be specific and evidence-based.

skills:
  - id: <type-id>-analysis
    name: <Framework> Analysis
    description: <What the skill does, 1 sentence>
    tags: [analysis, <2-3 relevant tags>]

input_fields:
  - name: text
    label: Document / Intelligence to Analyze
    type: textarea
    required: true
    placeholder: Paste the document or intelligence report to analyze...

temperature: 0.3
max_completion_tokens: 4096
```

## Step 5: Verify

After creating both files:
1. Confirm the `system_prompt_file` value in the YAML matches the actual prompt filename
2. Confirm the YAML filename will produce a unique type_id (check existing files in `agents/specialist_agent/agent_cards/`)
3. Tell the user the agent is ready and they just need to restart the specialist server (`python -m agents.specialist_agent.server` or `docker compose restart specialist-agent`)

## Existing Agents (avoid duplicates)

Check `agents/specialist_agent/agent_cards/` before creating — these already exist:
ach_red_team, asean_security, behavioral_economics, bilahari_kausikan, bridget_welsh, copenhagen_securitization, counterfactual_thinking, liberal_ir, military_strategy_deterrence, peripheral_scan, realist_ir, black_swan, technology_emerging_threats, yergin_energy
