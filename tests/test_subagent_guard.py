import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "plugins" / "codex-subagent-guard" / "hooks" / "subagent_guard.py"


def load_hook_module():
    spec = importlib.util.spec_from_file_location("subagent_guard", HOOK_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load hook module from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SubagentGuardTests(unittest.TestCase):
    def setUp(self):
        self._home_tmp = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        home = Path(self._home_tmp.name) / "home"
        home.mkdir()
        os.environ["HOME"] = str(home)

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self._home_tmp.cleanup()

    def test_fills_missing_spawn_fields_from_project_agent_toml(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            agents_dir = cwd / ".codex" / "agents"
            agents_dir.mkdir(parents=True)
            (agents_dir / "reviewer.toml").write_text(
                '\n'.join(
                    [
                        'name = "reviewer"',
                        'description = "Reviews correctness and tests."',
                        'model = "gpt-5.4"',
                        'model_reasoning_effort = "high"',
                        'developer_instructions = "Review like an owner."',
                    ]
                ),
                encoding="utf-8",
            )

            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the reviewer role for this bounded review.",
                },
            }

            output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "allow",
        )
        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["agent_type"], "reviewer")
        self.assertEqual(updated["model"], "gpt-5.4")
        self.assertEqual(updated["reasoning_effort"], "high")
        self.assertIs(updated["fork_context"], False)
        self.assertEqual(
            updated["message"],
            "Use the reviewer role for this bounded review.",
        )

    def test_omits_model_and_reasoning_when_project_agent_toml_omits_them(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            agents_dir = cwd / ".codex" / "agents"
            agents_dir.mkdir(parents=True)
            (agents_dir / "reviewer.toml").write_text(
                '\n'.join(
                    [
                        'name = "reviewer"',
                        'description = "Reviews correctness and tests."',
                        'developer_instructions = "Review like an owner."',
                    ]
                ),
                encoding="utf-8",
            )

            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the reviewer role for this bounded review.",
                },
            }

            output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "allow",
        )
        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["agent_type"], "reviewer")
        self.assertIs(updated["fork_context"], False)
        self.assertNotIn("model", updated)
        self.assertNotIn("reasoning_effort", updated)

    def test_builtin_agent_omits_model_and_reasoning_when_not_configured(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": tmp,
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                },
            }

            output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "allow",
        )
        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["agent_type"], "explorer")
        self.assertIs(updated["fork_context"], False)
        self.assertNotIn("model", updated)
        self.assertNotIn("reasoning_effort", updated)

    def test_project_config_can_configure_builtin_agent_defaults(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config_dir = cwd / ".codex"
            config_dir.mkdir()
            (config_dir / "subagent-guard.toml").write_text(
                "\n".join(
                    [
                        "[agent.default]",
                        'model = "gpt-5.5"',
                        'model_reasoning_effort = "medium"',
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the default role for a bounded task.",
                },
            }

            output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "allow",
        )
        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["agent_type"], "default")
        self.assertEqual(updated["model"], "gpt-5.5")
        self.assertEqual(updated["reasoning_effort"], "medium")
        self.assertIs(updated["fork_context"], False)

    def test_inherited_optional_fields_are_repaired_from_builtin_config(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config_dir = cwd / ".codex"
            config_dir.mkdir()
            (config_dir / "subagent-guard.toml").write_text(
                "\n".join(
                    [
                        "[agent.explorer]",
                        'model = "gpt-5.4-mini"',
                        'model_reasoning_effort = "medium"',
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                    "agent_type": "explorer",
                    "model": "inherited",
                    "reasoning_effort": "inherited",
                    "fork_context": False,
                },
            }

            output = hook.evaluate_event(event, env={})

        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["agent_type"], "explorer")
        self.assertEqual(updated["model"], "gpt-5.4-mini")
        self.assertEqual(updated["reasoning_effort"], "medium")
        self.assertIs(updated["fork_context"], False)

    def test_custom_agent_toml_can_configure_builtin_agent_routing(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            agents_dir = cwd / ".codex" / "agents"
            agents_dir.mkdir(parents=True)
            (agents_dir / "explorer.toml").write_text(
                '\n'.join(
                    [
                        'name = "explorer"',
                        'description = "Project explorer."',
                        'model = "gpt-5.5"',
                        'model_reasoning_effort = "high"',
                        'developer_instructions = "Explore this project."',
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                },
            }

            output = hook.evaluate_event(event, env={})

        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["agent_type"], "explorer")
        self.assertEqual(updated["model"], "gpt-5.5")
        self.assertEqual(updated["reasoning_effort"], "high")
        self.assertIs(updated["fork_context"], False)

    def test_leaves_complete_spawn_input_unchanged(self):
        hook = load_hook_module()
        original = {
            "message": "Do the bounded task.",
            "agent_type": "explorer",
            "model": "gpt-5.4-mini",
            "reasoning_effort": "medium",
            "fork_context": False,
        }
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_input": dict(original),
        }

        output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "allow",
        )
        self.assertEqual(output["hookSpecificOutput"]["updatedInput"], original)

    def test_supplied_fork_context_true_removes_explicit_routing(self):
        hook = load_hook_module()
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_input": {
                "message": "Run this bounded task with parent context.",
                "agent_type": "explorer",
                "model": "gpt-5.4-mini",
                "reasoning_effort": "medium",
                "fork_context": True,
            },
        }

        output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "allow",
        )
        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["message"], "Run this bounded task with parent context.")
        self.assertIs(updated["fork_context"], True)
        self.assertNotIn("agent_type", updated)
        self.assertNotIn("model", updated)
        self.assertNotIn("reasoning_effort", updated)

    def test_supplied_fork_context_true_denies_unknown_agent_type(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": tmp,
                "tool_input": {
                    "message": "Run this bounded task with parent context.",
                    "agent_type": "not-real",
                    "model": "gpt-5.4-mini",
                    "reasoning_effort": "medium",
                    "fork_context": True,
                },
            }

            output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        self.assertIn(
            "not-real",
            output["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_repairs_invalid_present_routing_values(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": tmp,
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                    "agent_type": "explorer",
                    "model": "",
                    "reasoning_effort": None,
                    "fork_context": None,
                },
            }

            output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "allow",
        )
        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["agent_type"], "explorer")
        self.assertIs(updated["fork_context"], False)
        self.assertNotIn("model", updated)
        self.assertNotIn("reasoning_effort", updated)

    def test_project_config_forces_fork_context_false(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config_dir = cwd / ".codex"
            config_dir.mkdir()
            (config_dir / "subagent-guard.toml").write_text(
                '\n'.join(
                    [
                        "[field.fork_context]",
                        "value = false",
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                    "agent_type": "explorer",
                    "model": "gpt-5.4-mini",
                    "reasoning_effort": "medium",
                    "fork_context": True,
                },
            }

            output = hook.evaluate_event(event, env={})

        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertIs(updated["fork_context"], False)

    def test_project_config_forces_fork_context_true(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config_dir = cwd / ".codex"
            config_dir.mkdir()
            (config_dir / "subagent-guard.toml").write_text(
                '\n'.join(
                    [
                        "[field.fork_context]",
                        "value = true",
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                    "agent_type": "explorer",
                    "model": "gpt-5.4-mini",
                    "reasoning_effort": "medium",
                    "fork_context": False,
                },
            }

            output = hook.evaluate_event(event, env={})

        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertIs(updated["fork_context"], True)
        self.assertNotIn("agent_type", updated)
        self.assertNotIn("model", updated)
        self.assertNotIn("reasoning_effort", updated)

    def test_project_config_fork_context_true_allows_unresolved_message(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config_dir = cwd / ".codex"
            config_dir.mkdir()
            (config_dir / "subagent-guard.toml").write_text(
                '\n'.join(
                    [
                        "[field.fork_context]",
                        "value = true",
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Delegate this work with parent context.",
                    "fork_context": False,
                },
            }

            output = hook.evaluate_event(event, env={})

        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["message"], "Delegate this work with parent context.")
        self.assertIs(updated["fork_context"], True)
        self.assertNotIn("agent_type", updated)

    def test_project_config_fork_context_none_preserves_default_behavior(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config_dir = cwd / ".codex"
            config_dir.mkdir()
            (config_dir / "subagent-guard.toml").write_text(
                '\n'.join(
                    [
                        "[field.fork_context]",
                        'value = "none"',
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                    "agent_type": "explorer",
                    "model": "gpt-5.4-mini",
                    "reasoning_effort": "medium",
                    "fork_context": True,
                },
            }

            output = hook.evaluate_event(event, env={})

        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["message"], "Use the explorer role for a bounded scan.")
        self.assertIs(updated["fork_context"], True)
        self.assertNotIn("agent_type", updated)
        self.assertNotIn("model", updated)
        self.assertNotIn("reasoning_effort", updated)

    def test_user_config_applies_when_project_config_is_absent(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            codex_home = Path(tmp) / "codex-home"
            cwd.mkdir()
            codex_home.mkdir()
            (codex_home / "subagent-guard.toml").write_text(
                '\n'.join(
                    [
                        "[field.fork_context]",
                        "value = true",
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                    "agent_type": "explorer",
                    "model": "gpt-5.4-mini",
                    "reasoning_effort": "medium",
                    "fork_context": False,
                },
            }

            output = hook.evaluate_event(
                event,
                env={"CODEX_HOME": str(codex_home)},
            )

        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertIs(updated["fork_context"], True)

    def test_project_builtin_defaults_merge_per_field_with_user_config(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            codex_home = Path(tmp) / "codex-home"
            config_dir = cwd / ".codex"
            config_dir.mkdir(parents=True)
            codex_home.mkdir()
            (codex_home / "subagent-guard.toml").write_text(
                "\n".join(
                    [
                        "[agent.worker]",
                        'model = "gpt-5.4-mini"',
                        'model_reasoning_effort = "medium"',
                    ]
                ),
                encoding="utf-8",
            )
            (config_dir / "subagent-guard.toml").write_text(
                "\n".join(
                    [
                        "[agent.worker]",
                        'model = "gpt-5.4"',
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the worker role for a bounded task.",
                },
            }

            output = hook.evaluate_event(
                event,
                env={"CODEX_HOME": str(codex_home)},
            )

        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["agent_type"], "worker")
        self.assertEqual(updated["model"], "gpt-5.4")
        self.assertEqual(updated["reasoning_effort"], "medium")

    def test_project_config_overrides_user_config(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            codex_home = Path(tmp) / "codex-home"
            config_dir = cwd / ".codex"
            config_dir.mkdir(parents=True)
            codex_home.mkdir()
            (codex_home / "subagent-guard.toml").write_text(
                '\n'.join(
                    [
                        "[field.fork_context]",
                        "value = true",
                    ]
                ),
                encoding="utf-8",
            )
            (config_dir / "subagent-guard.toml").write_text(
                '\n'.join(
                    [
                        "[field.fork_context]",
                        "value = false",
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                    "agent_type": "explorer",
                    "model": "gpt-5.4-mini",
                    "reasoning_effort": "medium",
                    "fork_context": True,
                },
            }

            output = hook.evaluate_event(
                event,
                env={"CODEX_HOME": str(codex_home)},
            )

        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertIs(updated["fork_context"], False)

    def test_project_none_config_overrides_user_force(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            codex_home = Path(tmp) / "codex-home"
            config_dir = cwd / ".codex"
            config_dir.mkdir(parents=True)
            codex_home.mkdir()
            (codex_home / "subagent-guard.toml").write_text(
                '\n'.join(
                    [
                        "[field.fork_context]",
                        "value = true",
                    ]
                ),
                encoding="utf-8",
            )
            (config_dir / "subagent-guard.toml").write_text(
                '\n'.join(
                    [
                        "[field.fork_context]",
                        'value = "none"',
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                    "agent_type": "explorer",
                    "model": "gpt-5.4-mini",
                    "reasoning_effort": "medium",
                    "fork_context": False,
                },
            }

            output = hook.evaluate_event(
                event,
                env={"CODEX_HOME": str(codex_home)},
            )

        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertIs(updated["fork_context"], False)

    def test_home_codex_config_does_not_override_custom_codex_home(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            cwd = home / "project"
            codex_home = tmp_path / "codex-home"
            home_config_dir = home / ".codex"
            cwd.mkdir(parents=True)
            codex_home.mkdir()
            home_config_dir.mkdir()
            (codex_home / "subagent-guard.toml").write_text(
                '\n'.join(
                    [
                        "[field.fork_context]",
                        "value = true",
                    ]
                ),
                encoding="utf-8",
            )
            (home_config_dir / "subagent-guard.toml").write_text(
                '\n'.join(
                    [
                        "[field.fork_context]",
                        "value = false",
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                    "agent_type": "explorer",
                    "model": "gpt-5.4-mini",
                    "reasoning_effort": "medium",
                    "fork_context": False,
                },
            }

            output = hook.evaluate_event(
                event,
                env={
                    "CODEX_HOME": str(codex_home),
                    "HOME": str(home),
                },
            )

        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertIs(updated["fork_context"], True)

    def test_home_codex_agents_do_not_override_custom_codex_home_agents(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            cwd = home / "project"
            codex_home = tmp_path / "codex-home"
            home_agents_dir = home / ".codex" / "agents"
            user_agents_dir = codex_home / "agents"
            cwd.mkdir(parents=True)
            home_agents_dir.mkdir(parents=True)
            user_agents_dir.mkdir(parents=True)
            (user_agents_dir / "explorer.toml").write_text(
                '\n'.join(
                    [
                        'name = "explorer"',
                        'description = "Custom CODEX_HOME explorer."',
                        'developer_instructions = "Use custom home."',
                        'model = "gpt-5.5"',
                        'model_reasoning_effort = "high"',
                    ]
                ),
                encoding="utf-8",
            )
            (home_agents_dir / "explorer.toml").write_text(
                '\n'.join(
                    [
                        'name = "explorer"',
                        'description = "Default home explorer."',
                        'developer_instructions = "Use default home."',
                        'model = "gpt-5.4-mini"',
                        'model_reasoning_effort = "low"',
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                },
            }

            output = hook.evaluate_event(
                event,
                env={
                    "CODEX_HOME": str(codex_home),
                    "HOME": str(home),
                },
            )

        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["agent_type"], "explorer")
        self.assertEqual(updated["model"], "gpt-5.5")
        self.assertEqual(updated["reasoning_effort"], "high")

    def test_invalid_fork_context_config_is_denied_with_hint(self):
        hook = load_hook_module()

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config_dir = cwd / ".codex"
            config_dir.mkdir()
            (config_dir / "subagent-guard.toml").write_text(
                '\n'.join(
                    [
                        "[field.fork_context]",
                        'value = "maybe"',
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the explorer role for a bounded scan.",
                    "agent_type": "explorer",
                    "model": "gpt-5.4-mini",
                    "reasoning_effort": "medium",
                    "fork_context": False,
                },
            }

            output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("field.fork_context.value", reason)
        self.assertIn("false, true, or \"none\"", reason)

    def test_denies_when_agent_cannot_be_resolved(self):
        hook = load_hook_module()
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_input": {
                "message": "Delegate this work.",
            },
        }

        output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("agent_type", reason)
        self.assertIn(".codex/agents", reason)

    def test_denies_unknown_agent_type_when_fields_need_repair(self):
        hook = load_hook_module()
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_input": {
                "message": "Use the not-real role for this bounded task.",
                "agent_type": "not-real",
                "model": "",
                "reasoning_effort": "medium",
                "fork_context": False,
            },
        }

        output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("not-real", reason)
        self.assertIn("was not found", reason)

    def test_denies_unknown_agent_type_even_when_complete(self):
        hook = load_hook_module()
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_input": {
                "message": "Run this bounded task.",
                "agent_type": "not-real",
                "model": "gpt-5.4-mini",
                "reasoning_effort": "medium",
                "fork_context": False,
            },
        }

        output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        self.assertIn(
            "not-real",
            output["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_denies_when_message_is_missing(self):
        hook = load_hook_module()
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_input": {},
        }

        output = hook.evaluate_event(event, env={})

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        self.assertIn(
            "message",
            output["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_ignores_other_tools(self):
        hook = load_hook_module()
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"cmd": "ls"},
        }

        self.assertIsNone(hook.evaluate_event(event, env={}))

    def test_cli_reads_json_from_stdin_and_writes_json_to_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            agents_dir = cwd / ".codex" / "agents"
            agents_dir.mkdir(parents=True)
            (agents_dir / "explorer.toml").write_text(
                '\n'.join(
                    [
                        'name = "explorer"',
                        'description = "Read-only exploration."',
                        'model = "gpt-5.4-mini"',
                        'model_reasoning_effort = "medium"',
                        'developer_instructions = "Explore only."',
                    ]
                ),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "cwd": str(cwd),
                "tool_input": {
                    "message": "Use the explorer role and report findings.",
                },
            }

            result = subprocess.run(
                [sys.executable, str(HOOK_PATH)],
                input=json.dumps(event),
                text=True,
                capture_output=True,
                check=True,
                env={**os.environ, "CODEX_HOME": str(cwd / "codex-home")},
            )

        payload = json.loads(result.stdout)
        updated = payload["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["agent_type"], "explorer")
        self.assertEqual(updated["model"], "gpt-5.4-mini")
        self.assertEqual(updated["reasoning_effort"], "medium")


if __name__ == "__main__":
    unittest.main()
