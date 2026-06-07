#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Mapping


REQUIRED_FIELDS = ("agent_type", "fork_context")
CONFIG_FILENAME = "subagent-guard.toml"
CONFIG_UNSET = object()


class ConfigError(Exception):
    pass


class AgentConfig:
    def __init__(
        self,
        name: str,
        description: str,
        model: str | None,
        reasoning_effort: str | None,
        source: Path | None,
    ) -> None:
        self.name = name
        self.description = description
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.source = source


class GuardConfig:
    def __init__(self, fork_context_value: object = CONFIG_UNSET) -> None:
        self.fork_context_value = fork_context_value


BUILT_IN_AGENTS: tuple[AgentConfig, ...] = (
    AgentConfig(
        name="default",
        description="General-purpose fallback subagent.",
        model=None,
        reasoning_effort=None,
        source=None,
    ),
    AgentConfig(
        name="worker",
        description="Execution-focused subagent for implementation and fixes.",
        model=None,
        reasoning_effort=None,
        source=None,
    ),
    AgentConfig(
        name="explorer",
        description="Read-heavy codebase exploration subagent.",
        model=None,
        reasoning_effort=None,
        source=None,
    ),
)


def evaluate_event(
    event: Mapping[str, object],
    env: Mapping[str, str] | None = None,
) -> dict[str, object] | None:
    active_env = os.environ if env is None else env
    tool_name = _optional_string(event.get("tool_name") or event.get("toolName"))
    if tool_name != "spawn_agent":
        return None

    tool_input = event.get("tool_input")
    if tool_input is None:
        tool_input = event.get("toolInput")
    if not isinstance(tool_input, dict):
        return _deny("spawn_agent input must be a JSON object.")

    updated = dict(tool_input)
    message_text = _message_text(updated)
    if not message_text:
        return _deny("spawn_agent requires a message so subagent routing can be resolved.")

    cwd = _event_cwd(event)
    try:
        config = load_guard_config(cwd, active_env)
    except ConfigError as exc:
        return _deny(str(exc))

    agents = discover_agents(cwd, active_env)
    agent_name = _optional_string(updated.get("agent_type"))
    if agent_name and agent_name not in agents:
        return _deny(_unknown_agent_reason(agent_name))

    if _effective_fork_context_true(updated, config):
        _prepare_full_history_fork(updated)
        return _allow(updated)

    if not agent_name:
        candidates = infer_agent_names(message_text, agents)
        if not candidates:
            return _deny(_unresolved_reason(agents))
        if len(candidates) > 1:
            return _deny(
                "spawn_agent agent_type is ambiguous; matched agents: "
                + ", ".join(candidates)
                + ". Pass agent_type explicitly."
            )
        agent_name = candidates[0]
        updated["agent_type"] = agent_name

    agent = agents.get(agent_name)
    if agent is None:
        return _deny(_unknown_agent_reason(agent_name))

    _repair_optional_string_field(updated, "model", agent.model)
    _repair_optional_string_field(updated, "reasoning_effort", agent.reasoning_effort)
    if not isinstance(updated.get("fork_context"), bool):
        updated["fork_context"] = False
    _apply_fork_context_config(updated, config)

    still_missing = _missing_or_invalid_routing_fields(updated)
    if still_missing:
        return _deny(
            "spawn_agent is missing required routing fields after resolution: "
            + ", ".join(still_missing)
        )

    return _allow(updated)


def load_guard_config(cwd: Path, env: Mapping[str, str]) -> GuardConfig:
    config = GuardConfig()
    for path in _config_paths(cwd, env):
        file_config = _read_guard_config(path)
        if file_config.fork_context_value is not CONFIG_UNSET:
            config.fork_context_value = file_config.fork_context_value
    return config


def discover_agents(cwd: Path, env: Mapping[str, str]) -> dict[str, AgentConfig]:
    agents = {agent.name: agent for agent in BUILT_IN_AGENTS}
    for directory in _agent_dirs(cwd, env):
        for path in sorted(directory.glob("*.toml")):
            agent = _read_agent(path)
            if agent is not None:
                agents[agent.name] = agent
    return agents


def _config_paths(cwd: Path, env: Mapping[str, str]) -> list[Path]:
    paths: list[Path] = []
    codex_home = _codex_home(env)
    user_config = codex_home / CONFIG_FILENAME
    if user_config.is_file():
        paths.append(user_config)

    global_config_dirs = _global_codex_dirs(env)
    project_paths: list[Path] = []
    for current in (cwd, *cwd.parents):
        candidate = current / ".codex" / CONFIG_FILENAME
        if candidate.is_file() and _normalized_path(candidate.parent) not in global_config_dirs:
            project_paths.append(candidate)
    paths.extend(reversed(project_paths))
    return paths


def _codex_home(env: Mapping[str, str]) -> Path:
    return Path(env.get("CODEX_HOME", str(_home_dir(env) / ".codex")))


def _home_dir(env: Mapping[str, str]) -> Path:
    return Path(env.get("HOME", str(Path.home())))


def _global_codex_dirs(env: Mapping[str, str]) -> set[Path]:
    return {
        _normalized_path(_codex_home(env)),
        _normalized_path(_home_dir(env) / ".codex"),
    }


def _normalized_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _read_guard_config(path: Path) -> GuardConfig:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"Could not read subagent guard config {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"Could not parse subagent guard config {path}: {exc}"
        ) from exc

    value = _nested_config_value(data, ("field", "fork_context", "value"))
    if value is CONFIG_UNSET:
        return GuardConfig()
    return GuardConfig(fork_context_value=_parse_fork_context_value(value, path))


def _nested_config_value(data: object, path: tuple[str, ...]) -> object:
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return CONFIG_UNSET
        current = current[key]
    return current


def _parse_fork_context_value(value: object, path: Path) -> object:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "none":
            return None
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ConfigError(
        f"{path}: field.fork_context.value must be false, true, or \"none\"."
    )


def _apply_fork_context_config(
    updated_input: dict[object, object],
    config: GuardConfig,
) -> None:
    if isinstance(config.fork_context_value, bool):
        updated_input["fork_context"] = config.fork_context_value


def _effective_fork_context_true(
    tool_input: Mapping[object, object],
    config: GuardConfig,
) -> bool:
    if isinstance(config.fork_context_value, bool):
        return config.fork_context_value
    return tool_input.get("fork_context") is True


def _prepare_full_history_fork(updated_input: dict[object, object]) -> None:
    updated_input["fork_context"] = True
    for field_name in ("agent_type", "model", "reasoning_effort"):
        updated_input.pop(field_name, None)


def _repair_optional_string_field(
    updated_input: dict[object, object],
    field_name: str,
    configured_value: str | None,
) -> None:
    if _optional_string(updated_input.get(field_name)):
        return
    updated_input.pop(field_name, None)
    if configured_value:
        updated_input[field_name] = configured_value


def infer_agent_names(
    message: str,
    agents: Mapping[str, AgentConfig],
) -> list[str]:
    matches: list[str] = []
    for name in sorted(agents):
        if _message_mentions_agent(message, name):
            matches.append(name)
    return matches


def _missing_or_invalid_routing_fields(tool_input: Mapping[object, object]) -> list[str]:
    missing: list[str] = []
    if not _optional_string(tool_input.get("agent_type")):
        missing.append("agent_type")
    if not isinstance(tool_input.get("fork_context"), bool):
        missing.append("fork_context")
    return missing


def main() -> int:
    raw_input = sys.stdin.read()
    try:
        event = json.loads(raw_input)
    except json.JSONDecodeError as exc:
        print(
            json.dumps(
                _deny(f"subagent guard expected JSON hook input: {exc.msg}"),
                sort_keys=True,
            )
        )
        return 0

    if not isinstance(event, dict):
        print(json.dumps(_deny("subagent guard expected a JSON object."), sort_keys=True))
        return 0

    output = evaluate_event(event)
    if output is not None:
        print(json.dumps(output, sort_keys=True))
    return 0


def _agent_dirs(cwd: Path, env: Mapping[str, str]) -> list[Path]:
    directories: list[Path] = []
    codex_home = _codex_home(env)
    user_agents = codex_home / "agents"
    if user_agents.is_dir():
        directories.append(user_agents)

    global_config_dirs = _global_codex_dirs(env)
    project_dirs: list[Path] = []
    for current in (cwd, *cwd.parents):
        candidate = current / ".codex" / "agents"
        if candidate.is_dir() and _normalized_path(candidate.parent) not in global_config_dirs:
            project_dirs.append(candidate)
    directories.extend(reversed(project_dirs))
    return directories


def _read_agent(path: Path) -> AgentConfig | None:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None

    name = _optional_string(data.get("name"))
    if not name:
        return None

    return AgentConfig(
        name=name,
        description=_optional_string(data.get("description")) or "",
        model=_optional_string(data.get("model")),
        reasoning_effort=(
            _optional_string(data.get("reasoning_effort"))
            or _optional_string(data.get("model_reasoning_effort"))
        ),
        source=path,
    )


def _message_text(tool_input: Mapping[object, object]) -> str:
    message = _optional_string(tool_input.get("message"))
    if message:
        return message

    items = tool_input.get("items")
    if not isinstance(items, list):
        return ""

    parts: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("type") == "text":
            text = _optional_string(item.get("text"))
            if text:
                parts.append(text)
    return "\n".join(parts)


def _event_cwd(event: Mapping[str, object]) -> Path:
    cwd = _optional_string(event.get("cwd"))
    if cwd:
        return Path(cwd)
    return Path.cwd()


def _message_mentions_agent(message: str, name: str) -> bool:
    name_pattern = _agent_name_pattern(name)
    patterns = (
        rf"\buse\s+(?:the\s+)?{name_pattern}\s+(?:role|agent)\b",
        rf"\b(?:agent_type|agent|subagent)\s*[:=]\s*{name_pattern}\b",
        rf"\bspawn\s+(?:a\s+|an\s+|the\s+)?{name_pattern}\b",
        rf"`{re.escape(name)}`",
    )
    return any(re.search(pattern, message, flags=re.IGNORECASE) for pattern in patterns)


def _agent_name_pattern(name: str) -> str:
    parts = re.split(r"[-_\s]+", name)
    return r"[-_\s]+".join(re.escape(part) for part in parts if part)


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _allow(updated_input: Mapping[object, object]) -> dict[str, object]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": dict(updated_input),
        }
    }


def _deny(reason: str) -> dict[str, object]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _unresolved_reason(agents: Mapping[str, AgentConfig]) -> str:
    known_agents = ", ".join(sorted(agents)) or "none"
    return (
        "spawn_agent is missing agent_type and no corresponding subagent could "
        "be resolved from the message. Mention an agent explicitly, for example "
        "'Use the reviewer role', pass agent_type/model/reasoning_effort/"
        "fork_context directly, or add a matching TOML file under "
        "~/.codex/agents or project .codex/agents. Known agents: "
        + known_agents
    )


def _unknown_agent_reason(agent_name: str) -> str:
    return (
        f"spawn_agent agent_type '{agent_name}' was not found in built-ins, "
        "~/.codex/agents, or project .codex/agents. Pass a known agent_type "
        "or add a matching agent TOML."
    )


if __name__ == "__main__":
    raise SystemExit(main())
