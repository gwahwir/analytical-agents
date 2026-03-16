"""Self-registration helper for agents.

On startup, agents call ``register_with_control_plane()`` to announce
themselves.  If ``CONTROL_PLANE_URL`` is not set the call is a no-op,
preserving backward compatibility with manual ``AGENT_URLS`` config.
"""

from __future__ import annotations

import asyncio
import os

import httpx


async def register_with_control_plane(type_name: str, agent_url: str) -> None:
    """POST to the control plane to register this agent instance.

    Retries with exponential backoff so agents that start before the
    control plane still get registered once it comes up.
    """
    cp_url = os.getenv("CONTROL_PLANE_URL", "").rstrip("/")
    if not cp_url:
        return

    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(
                    f"{cp_url}/agents/register",
                    json={"type_name": type_name, "agent_url": agent_url},
                )
                r.raise_for_status()
                print(f"[registration] Registered with control plane: {r.json()}")
                return
        except Exception as e:
            wait = 2 ** attempt
            print(f"[registration] Attempt {attempt + 1} failed ({e}), retrying in {wait}s...")
            await asyncio.sleep(wait)

    print("[registration] WARNING: Failed to register after 5 attempts")
