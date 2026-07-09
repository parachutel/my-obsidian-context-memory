from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "install.py"


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vault = self.root / "Vault with space"
        self.vault.mkdir()
        self.codex_home = self.root / "codex home"
        self.codex_home.mkdir()
        (self.codex_home / "hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {
                                "hooks": [
                                    {"type": "command", "command": "echo preserve-me", "timeout": 1}
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        (self.codex_home / "AGENTS.md").write_text("# Existing guidance\n", encoding="utf-8")
        (self.codex_home / "config.toml").write_text(
            "model = \"example\"\n\n[sandbox_workspace_write]\nwritable_roots = [\n  \"/existing/root\",\n]\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def install(self) -> dict:
        result = subprocess.run(
            [
                sys.executable,
                str(INSTALLER),
                "--vault",
                str(self.vault),
                "--codex-home",
                str(self.codex_home),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"Installer failed\nstdout={result.stdout}\nstderr={result.stderr}")
        return json.loads(result.stdout)

    def test_install_is_idempotent_and_preserves_existing_configuration(self) -> None:
        first = self.install()
        second = self.install()
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])

        skill = self.codex_home / "skills" / "obsidian-context-memory"
        self.assertTrue((skill / "SKILL.md").is_file())
        self.assertFalse(any(skill.rglob("*.pyc")))
        self.assertTrue((self.vault / "Codex" / "_System" / "Policy.md").is_file())

        hooks = json.loads((self.codex_home / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        for event in ("SessionStart", "UserPromptSubmit", "Stop"):
            memory_handlers = [
                handler
                for group in hooks[event]
                if isinstance(group, dict)
                for handler in group.get("hooks", [])
                if "obsidian_memory.py" in str(handler.get("command"))
            ]
            self.assertEqual(len(memory_handlers), 1)
        self.assertIn("echo preserve-me", json.dumps(hooks))

        agents = (self.codex_home / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("# Existing guidance", agents)
        self.assertEqual(agents.count("<!-- obsidian-context-memory:start -->"), 1)

        config = (self.codex_home / "config.toml").read_text(encoding="utf-8")
        self.assertIn("/existing/root", config)
        self.assertEqual(config.count(str(self.vault / "Codex")), 1)
        self.assertEqual(config.count(str(self.codex_home / "obsidian-context-memory")), 1)
        self.assertTrue(any((self.codex_home / "obsidian-context-memory" / "backups").iterdir()))

    def test_dry_run_does_not_write(self) -> None:
        fresh_home = self.root / "dry-codex"
        result = subprocess.run(
            [
                sys.executable,
                str(INSTALLER),
                "--vault",
                str(self.vault),
                "--codex-home",
                str(fresh_home),
                "--dry-run",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(fresh_home.exists())


if __name__ == "__main__":
    unittest.main()
