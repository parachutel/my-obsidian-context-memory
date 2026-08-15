from __future__ import annotations

import concurrent.futures
import json
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
MEMORY = REPO_ROOT / "scripts" / "obsidian_memory.py"


class MemoryCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vault = self.root / "Vault with space"
        self.vault.mkdir()
        self.state = self.root / "state"
        self.codex_home = self.root / "codex-home"
        self.codex_home.mkdir()
        self.cwd = self.root / "project"
        self.cwd.mkdir()
        self.config = self.root / "config.json"
        self.config.write_text(
            json.dumps(
                {
                    "vault_path": str(self.vault),
                    "managed_root": "Codex",
                    "state_dir": str(self.state),
                    "codex_home": str(self.codex_home),
                    "skill_path": str(REPO_ROOT),
                    "shared_roots": [],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(
        self,
        *args: str,
        input_value: Optional[dict] = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
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

    def packet_path(self, name: str, value: dict) -> Path:
        path = self.root / f"{name}.json"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def archive(self, name: str, value: dict, *extra: str) -> dict:
        packet = self.packet_path(name, value)
        result = self.run_cli("archive", "--cwd", str(self.cwd), "--input", str(packet), *extra)
        return json.loads(result.stdout)

    def test_bootstrap_archive_recall_and_redaction(self) -> None:
        self.run_cli("bootstrap")
        archived = self.archive(
            "packet",
            {
                "title": "Add durable memory",
                "status": "completed",
                "summary": "Configured api_key=should-never-persist for a deployment.",
                "knowledge": [
                    {
                        "title": "Deployment memory",
                        "domain": "operations",
                        "summary": "Use bounded, verified deployment context.",
                        "confidence": "verified",
                        "evidence": ["tests/test_memory.py"],
                    }
                ],
                "confidence": "verified",
                "sensitivity": "normal",
            },
        )
        self.assertTrue(archived["ok"])
        recall = self.run_cli(
            "recall", "--cwd", str(self.cwd), "--query", "deployment", "--format", "json", "--explain"
        )
        recalled = json.loads(recall.stdout)
        self.assertGreaterEqual(len(recalled["results"]), 1)
        self.assertIn("score_components", recalled["results"][0])
        self.assertGreaterEqual(recalled["stats"]["scanned_notes"], 1)
        markdown = "\n".join(
            path.read_text(encoding="utf-8") for path in (self.vault / "Codex").rglob("*.md")
        )
        self.assertNotIn("should-never-persist", markdown)
        self.assertIn("[REDACTED]", markdown)

    def test_strict_validation_and_validate_only(self) -> None:
        self.run_cli("bootstrap")
        missing = self.packet_path("missing", {"title": "No summary", "status": "completed"})
        result = self.run_cli(
            "archive", "--cwd", str(self.cwd), "--input", str(missing), check=False
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Missing required field: summary", result.stderr)

        unknown = self.packet_path(
            "unknown",
            {"title": "Unknown", "status": "completed", "summary": "Done.", "mystery": True},
        )
        result = self.run_cli(
            "archive", "--cwd", str(self.cwd), "--input", str(unknown), check=False
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown archive packet keys", result.stderr)

        valid = self.packet_path(
            "valid", {"title": "Validate", "status": "completed", "summary": "Validated."}
        )
        output = self.run_cli(
            "archive", "--cwd", str(self.cwd), "--input", str(valid), "--validate"
        )
        self.assertTrue(json.loads(output.stdout)["valid"])
        self.assertFalse(list((self.vault / "Codex" / "Projects").rglob("Tasks/**/*.md")))

    def test_stop_enforces_once_suppresses_success_and_falls_back_without_fingerprints(self) -> None:
        self.run_cli("bootstrap")
        prompt_event = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "cwd": str(self.cwd),
            "prompt": "password=hunter2 deploy the service",
        }
        prompt = json.loads(self.run_cli("hook", input_value=prompt_event).stdout)
        context = prompt["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("excerpt_json", context)
        match = re.search(r"turn_key=([a-f0-9]+)", context)
        self.assertIsNotNone(match)
        turn_key = match.group(1)
        state_files = list((self.state / "turns").rglob("*.json"))
        self.assertEqual(len(state_files), 1)
        state_text = state_files[0].read_text(encoding="utf-8")
        self.assertNotIn("hunter2", state_text)
        self.assertNotIn("sha256", state_text)

        stop_event = {
            "hook_event_name": "Stop",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "cwd": str(self.cwd),
            "stop_hook_active": False,
            "last_assistant_message": "private assistant output",
        }
        first_stop = json.loads(self.run_cli("hook", input_value=stop_event).stdout)
        self.assertEqual(first_stop["decision"], "block")
        self.assertIn(turn_key, first_stop["reason"])
        self.assertFalse(list((self.vault / "Codex").rglob("Checkpoints/By-Turn/**/*.md")))

        self.archive(
            "archived-turn",
            {"title": "Archive turn", "status": "completed", "summary": "Archived safely."},
            "--turn-key",
            turn_key,
        )
        after_archive = json.loads(self.run_cli("hook", input_value=stop_event).stdout)
        self.assertTrue(after_archive["continue"])
        self.assertFalse(state_files[0].exists())
        self.assertFalse(list((self.vault / "Codex").rglob("Checkpoints/By-Turn/**/*.md")))

        unresolved_prompt = dict(prompt_event, turn_id="turn-2", prompt="another private request")
        self.run_cli("hook", input_value=unresolved_prompt)
        unresolved_stop = dict(stop_event, turn_id="turn-2")
        self.assertEqual(
            json.loads(self.run_cli("hook", input_value=unresolved_stop).stdout)["decision"],
            "block",
        )
        unresolved_stop["stop_hook_active"] = True
        second_stop = json.loads(self.run_cli("hook", input_value=unresolved_stop).stdout)
        self.assertTrue(second_stop["continue"])
        checkpoints = list((self.vault / "Codex").rglob("Checkpoints/By-Turn/**/*.md"))
        self.assertEqual(len(checkpoints), 1)
        checkpoint = checkpoints[0].read_text(encoding="utf-8")
        self.assertIn("codex_status: \"partial\"", checkpoint)
        self.assertNotIn("fingerprint", checkpoint.lower())
        self.assertNotIn("private", checkpoint.lower())
        self.run_cli("hook", input_value=unresolved_stop)
        self.assertEqual(len(list((self.vault / "Codex").rglob("Checkpoints/By-Turn/**/*.md"))), 1)

        skipped_prompt = dict(prompt_event, turn_id="turn-3", prompt="no durable value")
        skipped_context = json.loads(self.run_cli("hook", input_value=skipped_prompt).stdout)[
            "hookSpecificOutput"
        ]["additionalContext"]
        skipped_key = re.search(r"turn_key=([a-f0-9]+)", skipped_context).group(1)
        self.run_cli(
            "skip",
            "--cwd",
            str(self.cwd),
            "--reason",
            "No durable value",
            "--turn-key",
            skipped_key,
        )
        skipped_stop = dict(stop_event, turn_id="turn-3")
        self.assertTrue(json.loads(self.run_cli("hook", input_value=skipped_stop).stdout)["continue"])
        self.assertEqual(len(list((self.vault / "Codex").rglob("Checkpoints/By-Turn/**/*.md"))), 1)

    def test_project_bind_explicitly_merges_identities(self) -> None:
        other = self.root / "other-project"
        other.mkdir()
        first = json.loads(
            self.run_cli(
                "project",
                "bind",
                "stable-project",
                "--cwd",
                str(self.cwd),
                "--display",
                "Stable Project",
            ).stdout
        )
        second = json.loads(
            self.run_cli(
                "project",
                "bind",
                "stable-project",
                "--cwd",
                str(other),
                "--display",
                "Stable Project",
            ).stdout
        )
        self.assertEqual(first["project"]["key"], "stable-project")
        self.assertEqual(second["project"]["key"], "stable-project")
        shown = json.loads(self.run_cli("project", "show", "--cwd", str(other)).stdout)
        self.assertEqual(shown["identity_kind"], "explicit-binding")

    def test_chinese_bm25_ranking_is_explainable(self) -> None:
        self.run_cli("bootstrap")
        relevant = self.archive(
            "relevant-zh",
            {
                "title": "量化选股新闻排序",
                "status": "completed",
                "summary": "使用新闻催化对量化选股候选池做短期排序。",
                "confidence": "verified",
            },
        )
        self.archive(
            "generic-zh",
            {
                "title": "Skill 配置整理",
                "status": "completed",
                "summary": "整理通用 Skill 配置与安装说明。",
                "confidence": "verified",
            },
        )
        recalled = json.loads(
            self.run_cli(
                "recall",
                "--cwd",
                str(self.cwd),
                "--query",
                "量化选股 新闻催化",
                "--format",
                "json",
                "--explain",
            ).stdout
        )
        self.assertEqual(recalled["results"][0]["path"], relevant["task"])
        self.assertGreater(recalled["results"][0]["score_components"]["bm25"], 0)

    def test_item_quality_gates_and_supersession(self) -> None:
        self.run_cli("bootstrap")
        partial = self.archive(
            "partial",
            {
                "title": "Partial research",
                "status": "partial",
                "summary": "Work remains.",
                "confidence": "high",
                "decisions": [
                    {"title": "Tentative choice", "decision": "Try option A.", "status": "active"}
                ],
                "knowledge": [
                    {
                        "title": "Unproven fact",
                        "summary": "Cobalt falcon uses option A.",
                        "confidence": "verified",
                        "status": "active",
                    }
                ],
            },
        )
        self.assertGreaterEqual(len(partial["warnings"]), 2)
        decision_path = next(path for path in partial["created"] if "/Decisions/" in path)
        knowledge_path = next(path for path in partial["created"] if "/Knowledge/" in path)
        decision_text = (self.vault / decision_path).read_text(encoding="utf-8")
        knowledge_text = (self.vault / knowledge_path).read_text(encoding="utf-8")
        self.assertIn("codex_status: \"candidate\"", decision_text)
        self.assertIn("codex_status: \"candidate\"", knowledge_text)
        self.assertIn("codex_confidence: \"medium\"", knowledge_text)

        replacement = self.archive(
            "replacement",
            {
                "title": "Verify fact",
                "status": "completed",
                "summary": "Verified the replacement.",
                "confidence": "verified",
                "knowledge": [
                    {
                        "title": "Verified cobalt falcon",
                        "summary": "Cobalt falcon uses option B.",
                        "confidence": "verified",
                        "evidence": ["tests/test_memory.py"],
                        "supersedes": [knowledge_path],
                    }
                ],
            },
        )
        replacement_path = next(path for path in replacement["created"] if "/Knowledge/" in path)
        replacement_text = (self.vault / replacement_path).read_text(encoding="utf-8")
        self.assertIn("codex_supersedes:", replacement_text)
        recall = json.loads(
            self.run_cli(
                "recall",
                "--cwd",
                str(self.cwd),
                "--query",
                "cobalt falcon",
                "--format",
                "json",
                "--explain",
            ).stdout
        )
        self.assertEqual(recall["results"][0]["path"], replacement_path)
        self.assertNotIn(knowledge_path, [item["path"] for item in recall["results"]])

    def test_concurrent_archive_is_idempotent(self) -> None:
        self.run_cli("bootstrap")
        packet = self.packet_path(
            "concurrent",
            {"title": "Concurrent archive", "status": "completed", "summary": "One durable result."},
        )
        command = [
            sys.executable,
            str(MEMORY),
            "--config",
            str(self.config),
            "archive",
            "--cwd",
            str(self.cwd),
            "--input",
            str(packet),
            "--turn-key",
            "same-turn-key",
        ]

        def invoke() -> subprocess.CompletedProcess:
            return subprocess.run(command, text=True, capture_output=True, check=False)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _value: invoke(), range(2)))
        self.assertTrue(all(result.returncode == 0 for result in results))
        payloads = [json.loads(result.stdout) for result in results]
        self.assertEqual(sum(bool(payload.get("idempotent_replay")) for payload in payloads), 1)
        tasks = list((self.vault / "Codex").rglob("*--*.md"))
        matching = [path for path in tasks if "concurrent-archive" in path.name]
        self.assertEqual(len(matching), 1)

    def test_doctor_checks_exact_hooks_and_native_memories(self) -> None:
        self.run_cli("bootstrap")
        command = (
            f"/usr/bin/env python3 {shlex.quote(str(MEMORY))} "
            f"--config {shlex.quote(str(self.config))} hook"
        )
        hooks = {"hooks": {}}
        for event in ("SessionStart", "UserPromptSubmit", "Stop"):
            group = {
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "timeout": 8,
                    }
                ]
            }
            if event == "SessionStart":
                group["matcher"] = "startup|resume|clear|compact"
            hooks["hooks"][event] = [group]
        (self.codex_home / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")
        (self.codex_home / "AGENTS.md").write_text(
            "<!-- obsidian-context-memory:start -->\n"
            "Use $obsidian-context-memory.\n"
            "<!-- obsidian-context-memory:end -->\n",
            encoding="utf-8",
        )
        (self.codex_home / "config.toml").write_text(
            "[sandbox_workspace_write]\n"
            f"writable_roots = [{json.dumps(str((self.vault / 'Codex').resolve()))}, {json.dumps(str(self.state.resolve()))}]\n"
            "[features]\nmemories = true\n"
            "[memories]\ngenerate_memories = true\nuse_memories = true\n",
            encoding="utf-8",
        )
        healthy = json.loads(self.run_cli("doctor").stdout)
        self.assertTrue(healthy["ok"])
        self.assertTrue(healthy["native_memories"]["enabled"])
        self.assertTrue(any("Codex local Memories generation" in item for item in healthy["warnings"]))
        trust = next(item for item in healthy["checks"] if item["name"] == "hook_trust")
        self.assertIsNone(trust["ok"])

        hooks["hooks"]["Stop"].append(hooks["hooks"]["Stop"][0])
        (self.codex_home / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")
        unhealthy = json.loads(self.run_cli("doctor").stdout)
        self.assertFalse(unhealthy["ok"])
        stop_check = next(item for item in unhealthy["checks"] if item["name"] == "hook_Stop_exact")
        self.assertEqual(stop_check["details"]["count"], 2)

    def test_managed_root_symlink_escape_is_rejected(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (self.vault / "Codex").symlink_to(outside, target_is_directory=True)
        result = self.run_cli("bootstrap", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside", result.stderr)


if __name__ == "__main__":
    unittest.main()
