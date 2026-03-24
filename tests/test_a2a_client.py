# tests/test_a2a_client.py
from __future__ import annotations
import json
import httpx
import pytest
from control_plane.a2a_client import A2AClient


async def test_stream_message_includes_baselines_in_metadata(httpx_mock):
    captured = {}

    def capture(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=b"", headers={"content-type": "text/event-stream"})

    httpx_mock.add_callback(capture, url="http://agent:8001/")
    client = A2AClient("http://agent:8001")
    gen = client.stream_message("hello", baselines="some baseline")
    try:
        async for _ in gen:
            pass
    except Exception:
        pass
    finally:
        await gen.aclose()
        await client.close()

    metadata = captured.get("params", {}).get("message", {}).get("metadata", {})
    assert metadata.get("baselines") == "some baseline"


async def test_stream_message_omits_empty_baselines(httpx_mock):
    captured = {}

    def capture(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=b"", headers={"content-type": "text/event-stream"})

    httpx_mock.add_callback(capture, url="http://agent:8001/")
    client = A2AClient("http://agent:8001")
    gen = client.stream_message("hello", baselines="")
    try:
        async for _ in gen:
            pass
    except Exception:
        pass
    finally:
        await gen.aclose()
        await client.close()

    metadata = captured.get("params", {}).get("message", {}).get("metadata", {})
    assert "baselines" not in metadata


async def test_stream_message_supports_aclose():
    client = A2AClient("http://agent:8001")
    gen = client.stream_message("hello")
    assert hasattr(gen, "aclose"), "must return AsyncGenerator"
    await gen.aclose()
    await client.close()
