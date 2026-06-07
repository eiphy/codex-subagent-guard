# Live Test Prompt

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

3. Built-in defaults from subagent-guard.toml
Write `.codex/subagent-guard.toml`:
[agent.default]
model = "gpt-5.5"
model_reasoning_effort = "medium"

[agent.worker]
model = "gpt-5.4"
model_reasoning_effort = "high"

Call spawn_agent with only:
message = "Use the default role. Reply exactly BUILTIN_DEFAULT_CONFIG_OK."
Expected: allowed. The subagent replies BUILTIN_DEFAULT_CONFIG_OK. If the UI shows routing, it should show `agent_type=default`, `model=gpt-5.5`, `reasoning_effort=medium`, and `fork_context=false`.

Call spawn_agent with only:
message = "Use the worker role. Reply exactly BUILTIN_CONFIG_OK."
Expected: allowed. The subagent replies BUILTIN_CONFIG_OK. If the UI shows routing, it should show `agent_type=worker`, `model=gpt-5.4`, `reasoning_effort=high`, and `fork_context=false` without needing `.codex/agents/worker.toml`.

4. Unknown agent_type denial
Call spawn_agent with:
agent_type = "not-real"
model = "gpt-5.4-mini"
reasoning_effort = "medium"
fork_context = false
message = "Run this bounded task."
Expected: blocked because `not-real` is not a known built-in or configured agent.

5. Same-name TOML config for a built-in
Call spawn_agent with only:
message = "Use the explorer role. Reply exactly CONFIGURED_EXPLORER_OK."
Expected: allowed. The subagent replies CONFIGURED_EXPLORER_OK. If the UI shows routing, it should show the configured explorer routing from the pre-session `.codex/agents/explorer.toml`.

6. TOML without model/reasoning
Call spawn_agent with only:
message = "Use the minimal role. Reply exactly MINIMAL_AGENT_OK."
Expected: allowed. The subagent replies MINIMAL_AGENT_OK. Missing model/reasoning in the pre-session `.codex/agents/minimal.toml` should not be rejected.

7. Invalid and inherited optional fields repaired or omitted
Call spawn_agent with:
agent_type = "minimal"
model = ""
reasoning_effort = null
fork_context = null
message = "Reply exactly OPTIONAL_REPAIR_OK."
Expected: allowed. The subagent replies OPTIONAL_REPAIR_OK. Blank model/reasoning should not force a rejection.

Call spawn_agent with:
agent_type = "worker"
model = "inherited"
reasoning_effort = "inherited"
fork_context = false
message = "Use the worker role. Reply exactly INHERITED_REPAIR_OK."
Expected: allowed. The subagent replies INHERITED_REPAIR_OK. If the UI shows routing, it should show the configured worker routing from probe 3, not `model=inherited`.

8. Force fork_context=false
Replace `.codex/subagent-guard.toml` with:
[field.fork_context]
value = false

Use parent-only marker: LIVE_FORK_CONTEXT_FALSE_MARKER. Do not include that marker in the spawn_agent message.
Call spawn_agent with:
agent_type = "explorer"
fork_context = true
message = "If you can see the exact parent-only marker, reply with only that marker. Otherwise reply exactly NO_MARKER_FALSE_FORCE."
Expected: allowed. The subagent replies NO_MARKER_FALSE_FORCE.

9. Force fork_context=true
Replace `.codex/subagent-guard.toml` with:
[field.fork_context]
value = true

Use parent-only marker: LIVE_FORK_CONTEXT_TRUE_MARKER. Do not include that marker in the spawn_agent message.
Call spawn_agent with:
agent_type = "explorer"
fork_context = false
message = "If you can see the exact parent-only marker, reply with only that marker. Otherwise reply exactly NO_MARKER_TRUE_FORCE."
Expected: allowed. The hook strips explicit routing because Codex rejects full-history forks that also request `agent_type`, `model`, or `reasoning_effort`. The subagent should inherit parent context and parent routing, then reply LIVE_FORK_CONTEXT_TRUE_MARKER.

10. Preserve fork_context with value="none"
Replace `.codex/subagent-guard.toml` with:
[field.fork_context]
value = "none"

Use parent-only marker: LIVE_FORK_CONTEXT_NONE_MARKER. Do not include that marker in the spawn_agent message.
Call spawn_agent with:
agent_type = "explorer"
fork_context = false
message = "If you can see the exact parent-only marker, reply with only that marker. Otherwise reply exactly NO_MARKER_NONE_FALSE."
Expected: allowed. The subagent replies NO_MARKER_NONE_FALSE because the supplied false value is preserved.

11. Invalid fork_context config denial
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
