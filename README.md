# Codex Subagent Guard

Codex Subagent Guard is a Codex plugin that validates `spawn_agent` calls before delegation.

When a `spawn_agent` call is missing routing fields, the hook tries to resolve the intended subagent from Codex agent TOML files or built-in agent names and fills:

- `agent_type`
- `fork_context`

If the resolved agent TOML specifies `model` or `model_reasoning_effort`, the hook fills those too. If those fields are not configured, the hook omits them and lets Codex choose its normal defaults.

If it cannot resolve the subagent safely, it rejects the call with a hint instead of allowing an under-specified delegation.

## Live-Test Behavior

Current live-test situations:

| Situation | Behavior |
| --- | --- |
| Message says `Use the reviewer role` and a matching TOML exists | Fills `agent_type`, `fork_context`, and configured `model`/`reasoning_effort`. |
| Message says `Use the reviewer role` and TOML omits `model` and reasoning | Fills `agent_type` and `fork_context`; omits `model` and `reasoning_effort`. |
| Message names built-in `default`, `worker`, or `explorer` | Recognized by name only; no hardcoded `model` or reasoning is added. |
| Same-name TOML exists for a built-in | TOML overrides the built-in entry and can configure `model` and reasoning. |
| Optional fields are blank, `null`, or invalid by type | Blank `model`/`reasoning_effort` are removed unless TOML supplies replacements; non-boolean `fork_context` is repaired to `false` before config is applied. |
| `field.fork_context.value = false` | Forces `fork_context = false`, even when the call supplied `true`. |
| `field.fork_context.value = true` | Forces full-history fork mode. The hook sets `fork_context = true` and removes explicit `agent_type`, `model`, and `reasoning_effort`, because Codex full-history forks inherit parent routing. |
| `field.fork_context.value = "none"` | Does not force a value; preserves a valid supplied boolean or the default repair value. |
| User config and project config both exist | Project config is applied after user config, so project config wins. |
| `CODEX_HOME` is set | User config and user agents are read from `$CODEX_HOME`; default `~/.codex` config and agents are outside that boundary. |
| Message does not identify an agent | Denied with a hint to mention an agent, pass routing fields directly, or add a matching TOML file, unless effective `fork_context = true` makes the call a full-history fork that inherits parent routing. |
| `agent_type` names an unknown agent | Denied, even if `model`, reasoning, and `fork_context` are present. |
| Config has an invalid `fork_context` value | Denied with a hint that the value must be `false`, `true`, or `"none"`. |
| Hook input has no message text | Denied because routing cannot be resolved. |
| Custom agent TOML is created after session start | The hook can see the file immediately, but Codex does not reload new custom agent types during the running session. Create custom agent TOML before starting the live-test session. |

## Resolution Rules

The hook reads agent files from:

- `$CODEX_HOME/agents/*.toml`, or `~/.codex/agents/*.toml` when `CODEX_HOME` is unset
- `.codex/agents/*.toml` from the current project path and parent paths

The TOML `name` field is the agent identifier. `model_reasoning_effort` is mapped to the `spawn_agent` field `reasoning_effort` when present.

Built-in fallback agents are also recognized:

- `default`
- `worker`
- `explorer`

Built-ins are recognized by name only. The hook does not assign model or reasoning defaults for them. Define an agent TOML with the same `name` to configure a built-in:

```toml
name = "explorer"
description = "Project-specific explorer."
developer_instructions = "Explore this project and report concise findings."
model = "gpt-5.4-mini"
model_reasoning_effort = "medium"
```

Codex loads custom agent types when a session starts. This plugin scans agent TOML files on every hook invocation, so it can notice files created mid-session, but Codex itself will still reject a newly created agent type as `unknown agent_type` until you restart Codex. Create or update custom agent TOML before launching the live-test session. This repository commits `.codex/agents/explorer.toml` and `.codex/agents/minimal.toml` as active live-test fixtures for sessions started from the repo root.

## Agent Inference

When `agent_type` is missing, the hook can infer it from explicit message patterns:

- `Use the explorer role`
- `Use the explorer agent`
- `agent_type: explorer`
- `agent = explorer`
- `subagent: explorer`
- `spawn explorer`
- `` `explorer` ``

For names with separators, variants like `code reviewer`, `code-reviewer`, and `code_reviewer` match the same agent name.

## Configuration

The hook reads optional config from:

- `$CODEX_HOME/subagent-guard.toml`, or `~/.codex/subagent-guard.toml` when `CODEX_HOME` is unset
- `.codex/subagent-guard.toml` from the current project path and parent paths

Project config is applied after user config, so the nearest project setting wins.

Configure `fork_context` with:

```toml
[field.fork_context]
value = false
```

Allowed values:

- `false`: always set `fork_context` to `false`
- `true`: always set `fork_context` to `true`
- `"none"`: do not force a value; keep the default repair behavior

## Copy-Paste Full Live Test Prompt

After install, create this setup in a scratch project directory before starting Codex. This matters because Codex does not reload new custom agent types during a running session:

```bash
mkdir -p .codex/agents
cat > .codex/agents/explorer.toml <<'EOF'
name = "explorer"
description = "Configured explorer for live tests."
developer_instructions = "Reply exactly as requested."
model = "gpt-5.5"
model_reasoning_effort = "high"
EOF

cat > .codex/agents/minimal.toml <<'EOF'
name = "minimal"
description = "Minimal agent for live tests."
developer_instructions = "Reply exactly as requested."
EOF
```

Then start a new Codex session in that scratch project directory, trust the hook with `/hooks`, and paste:

```text
Live-test codex-subagent-guard in this new session.

Do not bypass hook trust. If Codex asks to trust the hook, stop and report the exact prompt.
Do not edit source files. The custom agent TOML files already existed before this session started. You may create, replace, and remove only `.codex/subagent-guard.toml` during this test.

Run these probes and report PASS/FAIL for each with the exact observed result:

1. Unresolved inference denial
Call spawn_agent with only:
message = "Delegate this work."
Expected: blocked by the PreToolUse hook with an unresolved-agent hint. No subagent should remain running.

2. Built-in inference without hardcoded model/reasoning
Call spawn_agent with only:
message = "Use the worker role. Reply exactly BUILTIN_INFER_OK."
Expected: allowed. The subagent replies BUILTIN_INFER_OK. The hook may fill agent_type and fork_context, but should not need project TOML or hardcoded model/reasoning. This uses `worker` so the pre-created `explorer.toml` does not shadow the built-in probe.

3. Unknown agent_type denial
Call spawn_agent with:
agent_type = "not-real"
model = "gpt-5.4-mini"
reasoning_effort = "medium"
fork_context = false
message = "Run this bounded task."
Expected: blocked because `not-real` is not a known built-in or configured agent.

4. Same-name TOML config for a built-in
Call spawn_agent with only:
message = "Use the explorer role. Reply exactly CONFIGURED_EXPLORER_OK."
Expected: allowed. The subagent replies CONFIGURED_EXPLORER_OK. If the UI shows routing, it should show the configured explorer routing from the pre-session `.codex/agents/explorer.toml`.

5. TOML without model/reasoning
Call spawn_agent with only:
message = "Use the minimal role. Reply exactly MINIMAL_AGENT_OK."
Expected: allowed. The subagent replies MINIMAL_AGENT_OK. Missing model/reasoning in the pre-session `.codex/agents/minimal.toml` should not be rejected.

6. Invalid optional fields repaired or omitted
Call spawn_agent with:
agent_type = "minimal"
model = ""
reasoning_effort = null
fork_context = null
message = "Reply exactly OPTIONAL_REPAIR_OK."
Expected: allowed. The subagent replies OPTIONAL_REPAIR_OK. Blank model/reasoning should not force a rejection.

7. Force fork_context=false
Write `.codex/subagent-guard.toml`:
[field.fork_context]
value = false

Use parent-only marker: LIVE_FORK_CONTEXT_FALSE_MARKER. Do not include that marker in the spawn_agent message.
Call spawn_agent with:
agent_type = "explorer"
fork_context = true
message = "If you can see the exact parent-only marker, reply with only that marker. Otherwise reply exactly NO_MARKER_FALSE_FORCE."
Expected: allowed. The subagent replies NO_MARKER_FALSE_FORCE.

8. Force fork_context=true
Replace `.codex/subagent-guard.toml` with:
[field.fork_context]
value = true

Use parent-only marker: LIVE_FORK_CONTEXT_TRUE_MARKER. Do not include that marker in the spawn_agent message.
Call spawn_agent with:
agent_type = "explorer"
fork_context = false
message = "If you can see the exact parent-only marker, reply with only that marker. Otherwise reply exactly NO_MARKER_TRUE_FORCE."
Expected: allowed. The hook strips explicit routing because full-history forks inherit parent routing. The subagent should see parent context and reply LIVE_FORK_CONTEXT_TRUE_MARKER.

9. Preserve fork_context with value="none"
Replace `.codex/subagent-guard.toml` with:
[field.fork_context]
value = "none"

Use parent-only marker: LIVE_FORK_CONTEXT_NONE_MARKER. Do not include that marker in the spawn_agent message.
Call spawn_agent with:
agent_type = "explorer"
fork_context = false
message = "If you can see the exact parent-only marker, reply with only that marker. Otherwise reply exactly NO_MARKER_NONE_FALSE."
Expected: allowed. The subagent replies NO_MARKER_NONE_FALSE because the supplied false value is preserved.

10. Invalid fork_context config denial
Replace `.codex/subagent-guard.toml` with:
[field.fork_context]
value = "maybe"

Call spawn_agent with:
agent_type = "explorer"
fork_context = false
message = "Reply exactly INVALID_CONFIG_SHOULD_NOT_RUN."
Expected: blocked with a hint that `field.fork_context.value` must be false, true, or "none".

After the probes, remove the temporary `.codex/subagent-guard.toml`. Close any spawned agents that are still open.
```

For `CODEX_HOME` precedence and installed-cache field-level checks, use the unit tests in `tests/test_subagent_guard.py`; those are easier to verify deterministically than through the live UI stream.

## Install

Add this repository as a Codex plugin marketplace:

```bash
codex plugin marketplace add eiphy/codex-subagent-guard --ref v0.1.0
codex plugin add codex-subagent-guard --marketplace subagent-guard
```

During local development from this checkout:

```bash
codex plugin marketplace add /absolute/path/to/codex-subagent-guard
codex plugin add codex-subagent-guard --marketplace subagent-guard
```

After installing, start a new Codex session and review/trust the plugin hook with `/hooks`.

## Test

```bash
python3 -m unittest tests.test_subagent_guard
```

## Notes

`spawn_agent` hook mutation is supported by the current Codex hook path in tested local builds, but this plugin depends on Codex preserving `PreToolUse` coverage and `updatedInput` behavior for `spawn_agent`.
