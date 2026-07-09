from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skill" / "obsidian-context-memory"


class RepositoryTests(unittest.TestCase):
    def test_skill_shape_and_frontmatter(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("\nname: obsidian-context-memory\n", text)
        self.assertIn("\ndescription:", text)
        self.assertTrue((SKILL / "agents" / "openai.yaml").is_file())
        self.assertTrue((SKILL / "references" / "schema.md").is_file())
        self.assertTrue((SKILL / "scripts" / "obsidian_memory.py").is_file())

    def test_examples_are_valid_json(self) -> None:
        for path in (REPO_ROOT / "config").glob("*.json"):
            json.loads(path.read_text(encoding="utf-8"))

    def test_repository_has_no_machine_specific_paths_or_cache_files(self) -> None:
        forbidden = ["/" + "Users" + "/", "sheng" + "li", "Sheng" + "‘s Space"]
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            self.assertNotIn(path.suffix, {".pyc", ".pyo"})
            if path.suffix in {".md", ".py", ".json", ".toml", ".yaml", ".yml"}:
                text = path.read_text(encoding="utf-8")
                for value in forbidden:
                    self.assertNotIn(value, text, f"Found machine-specific value in {path}")


if __name__ == "__main__":
    unittest.main()
