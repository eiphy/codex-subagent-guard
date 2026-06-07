# Subagent Guard

Bundled Codex plugin package for `codex-subagent-guard`.

The lifecycle hook lives at `hooks/subagent_guard.py` and is enabled by the default `hooks/hooks.json` file.

Built-in agents `default`, `worker`, and `explorer` are recognized by name only.
The hook omits `model` and `reasoning_effort` unless those fields are configured in a matching agent TOML file.

Agent TOML files live under `$CODEX_HOME/agents` or project `.codex/agents`.
When `CODEX_HOME` is set, the default `~/.codex` config and agents are outside the user-config boundary.
A same-name TOML file can configure a built-in agent.
TOML without `model` or reasoning leaves those fields omitted from `spawn_agent`.
Create custom agent TOML before starting a live Codex session. The hook can scan new TOML files mid-session, but Codex does not reload new custom agent types during that running session and will reject them as `unknown agent_type` until restart.

Optional config lives at `$CODEX_HOME/subagent-guard.toml` or project `.codex/subagent-guard.toml`.
Project config is applied after user config, so project config wins.
Use this shape to force or preserve `fork_context` behavior:

```toml
[field.fork_context]
value = false
```

Allowed values are `false`, `true`, and `"none"`.

Live behavior summary:

- Explicit message patterns such as `Use the explorer role`, `Use the explorer agent`, `agent_type: explorer`, `agent = explorer`, `subagent: explorer`, `spawn explorer`, and `` `explorer` `` can infer `agent_type`.
- Agent names with spaces, hyphens, or underscores match the same configured name.
- Missing or invalid `fork_context` is repaired to `false` unless config forces `true`, forces `false`, or uses `"none"` to preserve the repaired or supplied value.
- Effective `fork_context = true` strips `agent_type`, `model`, and `reasoning_effort`, because Codex rejects full-history forks that also request explicit routing. The subagent inherits the parent agent type, model, and reasoning effort. Use `fork_context=false` when subagent TOML routing must be enforced.
- Blank `model` and `reasoning_effort` are removed unless the resolved TOML supplies replacements.
- Unknown `agent_type`, missing message text, invalid config, or unresolved agent inference is denied with an actionable hint. Unresolved inference is allowed only when effective `fork_context = true` makes the call a pure full-history fork that inherits parent routing.
- After install or hook trust changes, start a new Codex session before live testing.

See https://github.com/eiphy/codex-subagent-guard/blob/v0.1.2/docs/live_test.md for a copy-paste full live test prompt covering denial, inference, built-ins, TOML overrides, optional field repair, and `fork_context` config.
