# Relevancy Agent

Assesses whether a given text is relevant to a specific question. Uses an OpenAI-compatible LLM to evaluate relevancy and returns a structured JSON result with a verdict, confidence score, and reasoning.

## Graph

```
parse_input → check_relevancy
```

- **parse_input** — extracts `text` and `question` fields from the JSON input
- **check_relevancy** — calls the LLM to assess relevancy and returns structured JSON (has retry policy: 3 attempts with exponential backoff)

## Running

```bash
OPENAI_API_KEY=sk-... python -m agents.relevancy.server
```

Default port: **8003**

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | API key for the OpenAI-compatible endpoint |
| `OPENAI_BASE_URL` | No | OpenAI default | Custom base URL (e.g. OpenRouter, local model) |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Model to use for relevancy assessment |
| `RELEVANCY_AGENT_URL` | No | `http://localhost:8003` | This agent's externally-reachable URL (used for self-registration) |
| `CONTROL_PLANE_URL` | No | — | Control plane URL for self-registration/deregistration |

Falls back to the generic `AGENT_URL` env var if `RELEVANCY_AGENT_URL` is not set.

## Input

Two fields (sent as JSON):

- **text** (textarea) — the article or text to evaluate
- **question** (text) — the question the text should be relevant to

## Output

JSON object:

```json
{
  "relevant": true,
  "confidence": 0.92,
  "reasoning": "The text directly addresses the question by...",
  "error": false
}
```
