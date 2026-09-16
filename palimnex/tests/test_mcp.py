"""Optional transport integration: run with palimnex[mcp,test] installed."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from palimnex import Event, Palimnex
from palimnex.locators import repository_locator
from palimnex.tests.support import write_project


@unittest.skipUnless(importlib.util.find_spec("mcp"), "install palimnex[mcp] for transport integration")
class MCPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); write_project(self.root)
        self.client = Palimnex(self.root, writable=True)
        self.client.initialize()
        self.sid = self.client.start_session("MCP session")["session_id"]
        self.client.record(Event(self.sid, "fact", "cobalt current", {"state": "cobalt current"}, retention="durable"))

    async def test_tools_use_public_sdk_and_default_transport_is_read_only(self):
        from palimnex.mcp_server import create_server
        server = create_server(Palimnex(self.root))
        tools = await server.list_tools()
        self.assertEqual({tool.name for tool in tools}, {"recall", "plan_erasure", "verify_erasure"})
        self.assertTrue(all(tool.annotations.readOnlyHint for tool in tools))
        result = await server.call_tool("recall", {"query": "cobalt"})
        self.assertIn("cobalt current", str(result))
        with self.assertRaises(Exception):
            await server.call_tool("record_evidence", {})

    async def test_record_tool_is_bound_to_operator_session_and_repo_sources(self):
        from palimnex.mcp_server import create_server
        server = create_server(self.client, write_session=self.sid)
        self.assertEqual(len(await server.list_tools()), 4)
        locator = repository_locator(self.root, "docs/alpha.md:1-3").to_dict()
        result = await server.call_tool("record_evidence", {"subject": "cobalt evidence", "locator": locator})
        self.assertIn(self.sid, str(result))
        with self.assertRaises(Exception):
            await server.call_tool("record_evidence", {"subject": "bad", "locator": {**locator, "scheme": "https"}})
        with self.assertRaises(Exception):
            await server.call_tool("record_evidence", {"subject": "bad", "locator": locator, "session_id": "f" * 32})
        private = self.root / ".private" / "note.txt"
        private.write_text("private non-secret note", encoding="utf-8")
        private_locator = repository_locator(self.root, ".private/note.txt:1").to_dict()
        with self.assertRaises(Exception):
            await server.call_tool("record_evidence", {"subject": "bad", "locator": private_locator})

    async def test_real_stdio_handshake_list_and_call(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=sys.executable,
            args=["-m", "palimnex.mcp_server", "--root", str(self.root)],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                self.assertEqual(initialized.serverInfo.name, "Palimnex")
                listed = await session.list_tools()
                self.assertEqual(len(listed.tools), 3)
                result = await session.call_tool("recall", {"query": "cobalt"})
                self.assertFalse(result.isError)
                self.assertIn("cobalt current", json.dumps(result.model_dump()))
                failed = await session.call_tool("apply_erasure", {})
                self.assertTrue(failed.isError)


if __name__ == "__main__":
    unittest.main()
