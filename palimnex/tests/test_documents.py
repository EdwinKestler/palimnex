from __future__ import annotations

import unittest

from palimnex import core, documents


class DocumentGraphTests(unittest.TestCase):
    def test_markdown_extracts_hierarchy_links_relations_tables_and_fences(self) -> None:
        text = """# Decision Record

Decision: use docs/target.md
Supersedes: docs/old.md
[Runbook](runbook.md#restore)

| key | value |
| --- | --- |
| mode | held |

```sh
status --check
```
"""
        graph = documents.extract_document_graph(
            "docs/decision.md",
            text,
            schema=core.GRAPH_SCHEMA,
            symbol_id=core._symbol_id,
        )
        kinds = {item["kind"] for item in graph["symbols"]}
        edges = {item["kind"] for item in graph["edges"]}
        self.assertTrue({"document", "heading", "decision", "supersedes", "table", "code_fence"} <= kinds)
        self.assertTrue({"contains", "documents", "supersedes", "links_to"} <= edges)

    def test_table_before_next_heading_remains_contained_by_start_heading(self) -> None:
        graph = documents.extract_document_graph(
            "docs/table-owner.md",
            "# Heading A\n\n"
            "| key | value |\n"
            "| --- | --- |\n"
            "| mode | held |\n"
            "# Heading B\n\n"
            "Later prose.\n",
            schema=core.GRAPH_SCHEMA,
            symbol_id=core._symbol_id,
        )
        symbols = {item["qualified_name"]: item for item in graph["symbols"]}
        table_name = "document:docs/table-owner.md#table-3"
        heading_a = symbols["document:docs/table-owner.md#heading-a"]
        heading_b = symbols["document:docs/table-owner.md#heading-b"]
        containment = next(
            edge
            for edge in graph["edges"]
            if edge["kind"] == "contains" and edge["target"] == table_name
        )
        self.assertEqual(containment["source_id"], heading_a["id"])
        self.assertNotEqual(containment["source_id"], heading_b["id"])
        self.assertEqual(containment["line"], 3)

    def test_generic_json_extracts_only_config_key_structure(self) -> None:
        graph = documents.extract_document_graph(
            "config/settings.json",
            '{"alpha": "prose is not copied", "beta": 2}',
            schema=core.GRAPH_SCHEMA,
            symbol_id=core._symbol_id,
        )
        names = {item["name"] for item in graph["symbols"]}
        self.assertIn("alpha", names)
        self.assertIn("beta", names)
        self.assertNotIn("prose is not copied", repr(graph))

    def test_repeated_commit_on_one_line_does_not_duplicate_symbol_identity(self) -> None:
        graph = documents.extract_document_graph(
            "docs/repeated.md",
            "# Evidence\n\nCommit 4b5a689 supersedes 4b5a689.\n",
            schema=core.GRAPH_SCHEMA,
            symbol_id=core._symbol_id,
        )
        identities = [item["id"] for item in graph["symbols"]]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertTrue(core._valid_graphs({"docs/repeated.md": graph}, ["docs/repeated.md"]))

    def test_known_root_links_win_before_markdown_relative_fallback(self) -> None:
        known_paths = frozenset({"docs/decision.md", "docs/target.md"})
        decision = documents.extract_document_graph(
            "docs/decision.md",
            "# Decision\n\n"
            "[Root target](docs/target.md)\n"
            "[Relative target](target.md)\n"
            "[Unknown root-looking target](docs/missing.md)\n",
            schema=core.GRAPH_SCHEMA,
            symbol_id=core._symbol_id,
            known_paths=known_paths,
        )
        target = documents.extract_document_graph(
            "docs/target.md",
            "# Target\n",
            schema=core.GRAPH_SCHEMA,
            symbol_id=core._symbol_id,
            known_paths=known_paths,
        )
        links = {
            edge["line"]: edge
            for edge in decision["edges"]
            if edge["kind"] == "links_to"
        }
        self.assertEqual(links[3]["target"], "document:docs/target.md")
        self.assertEqual(links[4]["target"], "document:docs/target.md")
        self.assertEqual(links[5]["target"], "document:docs/docs/missing.md")

        graphs = {
            "docs/decision.md": decision,
            "docs/target.md": target,
        }
        core._resolve_graph(graphs)
        self.assertEqual(links[3]["resolution"]["status"], "exact_qualified")
        self.assertEqual(links[4]["resolution"]["status"], "exact_qualified")
        self.assertEqual(links[5]["resolution"]["status"], "unresolved")
        self.assertIsNone(links[5]["resolution"]["target_id"])


if __name__ == "__main__":
    unittest.main()
