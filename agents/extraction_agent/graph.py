"""Relevancy agent built with LangGraph.

Takes a blob of text and a question, checks with an LLM whether the
text is relevant to the question, and returns a structured JSON result.

Nodes:
1. ``parse_input``       – extract text and question from JSON input
2. ``check_relevancy``   – call LLM to assess relevancy
3. ``format_response``   – parse LLM output into structured JSON
"""

from __future__ import annotations

import json
import os
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.types import RetryPolicy


class ExtractionState(TypedDict):
    text: str
    input: str
    llm_response: str
    output: str


async def parse_input(state: ExtractionState, config: RunnableConfig) -> dict[str, Any]:
    """Extract text and question from the JSON input."""
    executor = config["configurable"]["executor"]
    task_id = config["configurable"]["task_id"]
    executor.check_cancelled(task_id)

    try:
        data = json.loads(state["input"])
        print(data)
        return {
            "text": data.get("text", "")
        }
    except json.JSONDecodeError:
        return {"text": state["input"]}


async def extract_using_llm(state: ExtractionState, config: RunnableConfig) -> dict[str, Any]:
    """Call LLM to determine if the text is relevant to the question."""
    executor = config["configurable"]["executor"]
    task_id = config["configurable"]["task_id"]
    executor.check_cancelled(task_id)

    from openai import AsyncOpenAI

    openai_kwargs: dict[str, Any] = {}
    base_url = os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")
    if base_url:
        openai_kwargs["base_url"] = base_url
    client = AsyncOpenAI(api_key=api_key, **openai_kwargs)

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    print("Processing new job")
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        """
    You are a precise information extraction engine. Given a blob of text (typically a news article or informational
        content), extract all key information into a structured JSON object.

        You MUST respond with ONLY a valid JSON object — no commentary, no markdown fences, no explanation outside the JSON.

        Extract the following fields:

        {
        "title": "Inferred or extracted title/headline of the article",
        "summary": "2-3 sentence summary of the core content",
        "entities": {
            "persons": [
            {"name": "Full Name", "role": "Their role/title if mentioned", "sentiment": "positive|negative|neutral"}
            ],
            "organizations": [
            {"name": "Org Name", "type": "company|government|ngo|media|educational|other"}
            ],
            "locations": [
            {"name": "Place Name", "type": "city|country|region|address|landmark"}
            ],
            "products": [
            {"name": "Product/Service Name", "owner": "Owning entity if known"}
            ]
        },
        "temporal": {
            "publication_date": "YYYY-MM-DD or null if unknown",
            "events": [
            {"description": "What happened", "date": "YYYY-MM-DD or approximate", "is_future": false}
            ]
        },
        "financials": [
            {"amount": "Numeric value", "currency": "USD/EUR/etc", "context": "What the amount refers to"}
        ],
        "topics": ["tag1", "tag2"],
        "categories":
        ["politics|business|technology|science|health|sports|entertainment|environment|legal|conflict|other"],
        "claims": [
            {"statement": "A factual claim made in the text", "attribution": "Who said/claimed it", "verifiable": true}
        ],
        "relationships": [
            {"subject": "Entity A", "predicate": "acquired|partnered_with|sued|appointed|etc", "object": "Entity B"}
        ],
        "metadata": {
            "language": "en",
            "word_count": 0,
            "tone": "formal|informal|urgent|analytical|opinion",
            "confidence": 0.0
        }
        }

        Rules:
        - Omit array fields that have no matches (use empty arrays, not null).
        - Never fabricate information not present or clearly implied in the text.
        - For ambiguous dates, use the most specific format possible ("2026-03" if only month/year is known).
        - Normalize entity names (e.g., "President Biden" and "Joe Biden" → one entry with full name).
        - The confidence field in metadata (0.0–1.0) reflects your overall confidence in extraction accuracy.
        - If financial figures use shorthand (e.g., "$2.5B"), expand to full numeric strings ("2500000000").
        - Extract implicit relationships (e.g., "CEO of Acme Corp" → relationship: person → leads → Acme Corp).
    """
                    ),
                },
                {
                    "role": "user",
                    "content": f"Text:\n{state['text']}",
                },
            ],
            temperature=0.1,
            max_completion_tokens=60000,
            timeout=300,
        )
        raw = response.choices[0].message.content
        print(raw)
        try:
            parsed = json.loads(raw)
            result = parsed
        except (json.JSONDecodeError, ValueError):
            result = {}

        return {"output": json.dumps(result, indent=2)}
    except Exception as e:
        print(e)
        return e


# async def format_response(state: RelevancyState, config: RunnableConfig) -> dict[str, Any]:
#     """Parse the LLM response into structured JSON output."""
#     executor = config["configurable"]["executor"]
#     task_id = config["configurable"]["task_id"]
#     executor.check_cancelled(task_id)

#     raw = state["llm_response"].strip()

#     # Try to parse JSON from the LLM response
#     try:
#         parsed = json.loads(raw)
#         result = {
#             "relevant": bool(parsed.get("relevant", False)),
#             "confidence": float(parsed.get("confidence", 0.0)),
#             "reasoning": str(parsed.get("reasoning", "")),
#             "error": False
#         }
#     except (json.JSONDecodeError, ValueError):
#         result = {
#             "relevant": False,
#             "confidence": 0.0,
#             "reasoning": f"Failed to parse LLM response: {raw}",
#             "error": True
#         }

#     return {"output": json.dumps(result, indent=2)}


def build_extraction_graph() -> StateGraph:
    graph = StateGraph(ExtractionState)
    graph.add_node("parse_input", parse_input)
    graph.add_node("extract_using_llm", extract_using_llm, retry_policy=RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0))
    graph.set_entry_point("parse_input")
    graph.add_edge("parse_input", "extract_using_llm")
    graph.add_edge("extract_using_llm", END)
    return graph.compile()
