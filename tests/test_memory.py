from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MEMORY = REPO_ROOT / "skill" / "obsidian-context-memory" / "scripts" / "obsidian_memory.py"


class MemoryCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vault = self.root / "Vault with space"
        self.vault.mkdir()
        self.state = self.root / "state"
        self.cwd = self.root / "project"
        self.cwd.mkdir()
        self.config = self.root / "config.json"
        self.config.write_text(
            json.dumps(
                {
                    "vault_path": str(self.vault),
                    "managed_root": "Codex",
                    "state_dir": str(self.state),
                    "shared_roots": [],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str, input_value: dict | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(MEMORY), "--config", str(self.config), *args],
            input=json.dumps(input_value) if input_value is not None else None,
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(f"Command failed: {result.args}\nstdout={result.stdout}\nstderr={result.stderr}")
        return result

    def test_bootstrap_archive_and_recall_redact_secrets(self) -> None:
        self.run_cli("bootstrap")
        packet = self.root / "packet.json"
        packet.write_text(
            json.dumps(
                {
                    "title": "Add durable memory",
                    "status": "completed",
                    "summary": "Configured api_key=should-never-persist for a deployment.",
                    "knowledge": [
                        {
                            "title": "Deployment memory",
                            "domain": "operations",
                            "summary": "Use bounded, verified context.",
                            "confidence": "verified",
                        }
                    ],
                    "confidence": "verified",
                    "sensitivity": "normal",
                }
            ),
            encoding="utf-8",
        )
        archive = self.run_cli("archive", "--cwd", str(self.cwd), "--input", str(packet))
        archived = json.loads(archive.stdout)
        self.assertTrue(archived["ok"])
        recall = self.run_cli("recall", "--cwd", str(self.cwd), "--query", "deployment", "--format", "json")
        recalled = json.loads(recall.stdout)
        self.assertGreaterEqual(len(recalled["results"]), 1)
        markdown = "\n".join(path.read_text(encoding="utf-8") for path in (self.vault / "Codex").rglob("*.md"))
        self.assertNotIn("should-never-persist", markdown)
        self.assertIn("[REDACTED]", markdown)

    def test_prompt_and_stop_hooks_store_fingerprints_not_raw_text(self) -> None:
        self.run_cli("bootstrap")
        prompt_event = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "cwd": str(self.cwd),
            "prompt": "password=hunter2 deploy the service",
        }
        prompt = self.run_cli("hook", input_value=prompt_event)
        output = json.loads(prompt.stdout)
        self.assertTrue(output["continue"])
        self.assertIn("OBSIDIAN_MEMORY_CONTEXT", output["hookSpecificOutput"]["additionalContext"])
        state_files = list((self.state / "turns").rglob("*.json"))
        self.assertEqual(len(state_files), 1)
        self.assertNotIn("hunter2", state_files[0].read_text(encoding="utf-8"))

        stop_event = {
            "hook_event_name": "Stop",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "cwd": str(self.cwd),
            "last_assistant_message": "private assistant output",
        }
        self.run_cli("hook", input_value=stop_event)
        checkpoints = list((self.vault / "Codex").rglob("Checkpoints/By-Turn/**/*.md"))
        self.assertEqual(len(checkpoints), 1)
        checkpoint = checkpoints[0].read_text(encoding="utf-8")
        self.assertNotIn("hunter2", checkpoint)
        self.assertNotIn("private assistant output", checkpoint)
        self.assertIn("codex_request_fingerprint", checkpoint)
        self.assertFalse(state_files[0].exists())

    def test_managed_root_symlink_escape_is_rejected(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (self.vault / "Codex").symlink_to(outside, target_is_directory=True)
        result = self.run_cli("bootstrap", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside", result.stderr)


if __name__ == "__main__":
    unittest.main()
