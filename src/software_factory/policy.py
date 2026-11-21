from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


POLICY_FIELDS = {
    "schema_version",
    "phase",
    "approved_plan_digest",
    "repository_root",
    "writable_paths",
    "read_only_paths",
    "denied_paths",
    "allowed_tools",
    "allowed_agents",
    "allowed_commands",
}
NATIVE_TASK_TOOLS = {"list_agents", "task"}
READ_ONLY_TASK_TYPES = {"code-review", "engineer", "code-reviewer"}
ALLOWED_TOOLS = {
    "view",
    "read",
    "glob",
    "grep",
    "create",
    "edit",
    "apply_patch",
    "powershell",
}
WRITE_TOOLS = {"create", "edit", "apply_patch"}
READ_TOOLS = {"view", "read", "glob", "grep"}
SAFE_ENVIRONMENT_KEYS = {
    "appdata",
    "comspec",
    "homedrive",
    "homepath",
    "localappdata",
    "path",
    "pathext",
    "programfiles",
    "programfiles(x86)",
    "systemdrive",
    "systemroot",
    "temp",
    "tmp",
    "userprofile",
    "windir",
}


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class HostedAuthorization:
    provider: str
    content_categories: tuple[str, ...]
    authorized: bool
    authorized_at: str


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    permission_decision: str = "allow"


def authorize_hosted_use(
    provider: str, content_categories: list[str] | tuple[str, ...], *, accepted: bool
) -> HostedAuthorization:
    provider_name = provider.strip() if isinstance(provider, str) else ""
    categories = tuple(
        item.strip()
        for item in content_categories
        if isinstance(item, str) and item.strip()
    )
    if not provider_name:
        raise PolicyError("Hosted provider identity is unavailable")
    if not categories:
        raise PolicyError("Hosted-use content disclosure is empty")
    if accepted is not True:
        raise PolicyError("Hosted use was not authorized for this run")
    return HostedAuthorization(
        provider=provider_name,
        content_categories=categories,
        authorized=True,
        authorized_at=datetime.now(timezone.utc).isoformat(),
    )


def build_sanitized_environment(
    source: Mapping[str, str],
    *,
    factory_home: str | os.PathLike[str] | None = None,
    credential_store_env_keys: tuple[str, ...] = (),
) -> dict[str, str]:
    permitted = SAFE_ENVIRONMENT_KEYS | {
        key.casefold() for key in credential_store_env_keys
    }
    environment = {
        key: value
        for key, value in source.items()
        if key.casefold() in permitted
        and isinstance(value, str)
        and not _is_sensitive_env_key(key)
    }
    if factory_home is not None:
        environment["COPILOT_HOME"] = os.fspath(factory_home)
    environment["SPECKIT_COPILOT_ALLOW_ALL_TOOLS"] = "0"
    environment["SPECKIT_ALLOW_ALL_TOOLS"] = "0"
    environment["COPILOT_ALLOW_ALL"] = "false"
    return environment


def create_policy(
    *,
    phase: str,
    repository_root: str | os.PathLike[str],
    writable_paths: list[str | os.PathLike[str]],
    read_only_paths: list[str | os.PathLike[str]],
    denied_paths: list[str | os.PathLike[str]],
    allowed_tools: list[str],
    allowed_agents: list[str] | None = None,
    allowed_commands: list[Mapping[str, str]],
    approved_plan_digest: str | None = None,
    feature_directory: str | os.PathLike[str] | None = None,
    allow_native_tools: bool = False,
) -> dict[str, Any]:
    root = _canonical_path(repository_root)
    policy = {
        "schema_version": 1,
        "phase": phase,
        "approved_plan_digest": approved_plan_digest,
        "repository_root": str(root),
        "writable_paths": [str(_canonical_path(path)) for path in writable_paths],
        "read_only_paths": [str(_canonical_path(path)) for path in read_only_paths],
        "denied_paths": [str(_canonical_path(path)) for path in denied_paths],
        "allowed_tools": list(allowed_tools),
        "allowed_agents": [] if allowed_agents is None else list(allowed_agents),
        "allowed_commands": [
            {
                "command": item.get("command"),
                "working_directory": str(_canonical_path(item.get("working_directory", ""))),
            }
            for item in allowed_commands
        ],
    }
    if phase == "planning":
        if feature_directory is None:
            raise PolicyError("Planning policies require the feature directory")
        feature_root = _canonical_path(feature_directory)
        if not _is_within(feature_root, root):
            raise PolicyError("Planning feature directory is outside the repository")
        try:
            feature_relative = feature_root.relative_to(root)
        except ValueError as error:
            raise PolicyError("Planning feature directory is outside the repository") from error
        if len(feature_relative.parts) != 2 or feature_relative.parts[0].casefold() != "specs":
            raise PolicyError("Planning feature directory must be under specs/<feature>")
        policy["writable_paths"] = [
            str(_canonical_path(path, root=feature_root)) for path in writable_paths
        ]
        if any(
            not _is_within(Path(path), feature_root)
            for path in policy["writable_paths"]
        ):
            raise PolicyError("Planning policies may write only inside the current feature directory")
    validate_policy(policy, expected_root=root, allow_native_tools=allow_native_tools)
    return policy


def validate_policy(
    policy: Mapping[str, Any],
    *,
    approved_plan_digest: str | None = None,
    expected_root: str | os.PathLike[str] | None = None,
    allow_native_tools: bool = False,
) -> None:
    if not isinstance(policy, Mapping) or set(policy) != POLICY_FIELDS:
        raise PolicyError("Policy fields are missing or unknown")
    if type(policy["schema_version"]) is not int or policy["schema_version"] != 1:
        raise PolicyError("Unsupported policy schema version")
    phase = policy["phase"]
    if phase not in {"planning", "implementation"}:
        raise PolicyError("Unknown policy phase")

    root = _canonical_path(policy["repository_root"])
    if expected_root is not None and not _same_path(root, _canonical_path(expected_root)):
        raise PolicyError("Policy repository root does not match the current repository")

    path_fields = ("writable_paths", "read_only_paths", "denied_paths")
    paths: dict[str, list[Path]] = {}
    for field in path_fields:
        values = policy[field]
        if not isinstance(values, list):
            raise PolicyError(f"{field} must be a list")
        paths[field] = []
        for value in values:
            path = _canonical_path(value)
            if not _is_within(path, root):
                raise PolicyError(f"{field} contains a path outside the repository")
            paths[field].append(path)

    if phase == "planning":
        if policy["approved_plan_digest"] is not None:
            raise PolicyError("Planning policies must have a null approved-plan digest")
        _validate_planning_writes(paths["writable_paths"], root)
    else:
        digest = policy["approved_plan_digest"]
        if not isinstance(digest, str) or not digest.strip():
            raise PolicyError("Implementation policies require an approved-plan digest")
        if approved_plan_digest is not None and digest != approved_plan_digest:
            raise PolicyError("Implementation policy digest does not match the approved plan")

    tools = policy["allowed_tools"]
    if not isinstance(tools, list) or any(
        not isinstance(tool, str)
        or (
            tool not in ALLOWED_TOOLS
            and not (allow_native_tools and tool in NATIVE_TASK_TOOLS)
        )
        for tool in tools
    ):
        raise PolicyError("Policy contains an unknown tool")
    if len(set(tools)) != len(tools):
        raise PolicyError("Policy contains duplicate tools")

    agents = policy["allowed_agents"]
    if not isinstance(agents, list) or any(
        not isinstance(agent, str) or agent.strip().casefold() not in READ_ONLY_TASK_TYPES
        for agent in agents
    ):
        raise PolicyError("Policy contains an unknown allowed agent")
    normalized_agents = [agent.strip().casefold() for agent in agents]
    if len(set(normalized_agents)) != len(normalized_agents):
        raise PolicyError("Policy contains duplicate allowed agents")

    commands = policy["allowed_commands"]
    if not isinstance(commands, list):
        raise PolicyError("allowed_commands must be a list")
    for item in commands:
        if not isinstance(item, Mapping) or set(item) != {"command", "working_directory"}:
            raise PolicyError("Allowed command entry is malformed")
        if not isinstance(item["command"], str) or not item["command"].strip():
            raise PolicyError("Allowed command text must not be empty")
        working_directory = _canonical_path(item["working_directory"])
        if not _is_within(working_directory, root):
            raise PolicyError("Allowed command directory is outside the repository")


def evaluate_hook_event(policy: Mapping[str, Any], event: Any) -> PolicyDecision:
    try:
        validate_policy(policy, allow_native_tools=True)
        if not isinstance(event, Mapping):
            raise PolicyError("Hook event must be an object")
        tool = event.get("toolName", event.get("tool_name"))
        arguments = event.get("toolArgs", event.get("tool_input", event.get("arguments")))
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(tool, str) or not isinstance(arguments, Mapping):
            raise PolicyError("Hook event is missing a tool name or argument object")
        policy_tool = "read" if tool == "view" else tool
        if policy_tool not in policy["allowed_tools"]:
            raise PolicyError("Tool is not allowlisted")
        agent_id = event.get("agentId", event.get("agent_id"))
        agent_type = event.get("agentType", event.get("agent_type"))
        has_agent_context = any(
            key in event
            for key in ("agentId", "agent_id", "agentType", "agent_type")
        )
        if has_agent_context:
            if not isinstance(agent_id, str) or not agent_id.strip():
                raise PolicyError("Subagent identity is missing or malformed")
            if (
                not isinstance(agent_type, str)
                or agent_type.strip().casefold()
                not in {agent.casefold() for agent in policy["allowed_agents"]}
            ):
                raise PolicyError("Subagent type is not allowlisted")
            if tool not in READ_TOOLS:
                raise PolicyError("Subagents are limited to read-only tools")
        if tool == "list_agents":
            return PolicyDecision(True, "Allowed by the explicit native-task policy")
        if tool == "task":
            task_type_keys = [
                key for key in arguments
                if isinstance(key, str)
                and key.casefold() in {"agent_type", "agenttype"}
            ]
            allowed_task_keys = {
                "agent_type", "agenttype", "prompt", "description", "mode", "name"
            }
            if (
                any(not isinstance(key, str) for key in arguments)
                or any(key.casefold() not in allowed_task_keys for key in arguments)
                or len(task_type_keys) != 1
            ):
                raise PolicyError("Task payload is malformed")
            task_type = arguments[task_type_keys[0]]
            prompt = arguments.get("prompt")
            description_present = any(
                isinstance(key, str) and key.casefold() == "description"
                for key in arguments
            )
            description = next(
                (
                    value
                    for key, value in arguments.items()
                    if isinstance(key, str) and key.casefold() == "description"
                ),
                None,
            )
            mode = arguments.get("mode")
            name = arguments.get("name")
            mode_present = any(
                isinstance(key, str) and key.casefold() == "mode"
                for key in arguments
            )
            name_present = any(
                isinstance(key, str) and key.casefold() == "name"
                for key in arguments
            )
            if (
                not isinstance(task_type, str)
                or not task_type.strip()
                or not isinstance(prompt, str)
                or not prompt.strip()
                or (
                    description_present
                    and (not isinstance(description, str) or not description.strip())
                )
                or (mode_present and (not isinstance(mode, str) or mode.casefold() != "sync"))
                or (name_present and (not isinstance(name, str) or not name.strip()))
            ):
                raise PolicyError("Task payload requires an agent type and non-empty prompt")
            if task_type.strip().casefold() not in {
                agent.casefold() for agent in policy["allowed_agents"]
            }:
                raise PolicyError("Task agent type is not allowlisted")
            return PolicyDecision(
                True,
                "Allowed by the explicit read-only task policy; user approval is required",
                "ask",
            )
        if tool == "powershell":
            return _evaluate_command(policy, arguments)

        targets = _extract_targets(tool, arguments, Path(policy["repository_root"]))
        if not targets:
            raise PolicyError("Tool request does not identify a target path")
        writable = [Path(path) for path in policy["writable_paths"]]
        readable = writable + [Path(path) for path in policy["read_only_paths"]]
        denied = [Path(path) for path in policy["denied_paths"]]

        for target in targets:
            if any(_path_conflicts(target, blocked) for blocked in denied):
                raise PolicyError("Target path is denied")
            scopes = writable if tool in WRITE_TOOLS else readable
            if not any(_is_within(target, scope) for scope in scopes):
                raise PolicyError("Target path is outside the allowed paths")
        return PolicyDecision(True, "Allowed by the execution policy")
    except (PolicyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
        return PolicyDecision(False, str(error) or "Malformed hook event", "deny")


def _evaluate_command(
    policy: Mapping[str, Any], arguments: Mapping[str, Any]
) -> PolicyDecision:
    command = arguments.get("command", arguments.get("script"))
    directory = arguments.get(
        "working_directory", arguments.get("workingDirectory", arguments.get("cwd"))
    )
    if not isinstance(command, str) or not isinstance(directory, str):
        raise PolicyError("PowerShell requests require exact command text and working directory")
    canonical_directory = _canonical_path(directory)
    for allowed in policy["allowed_commands"]:
        if (
            command == allowed["command"]
            and _same_path(canonical_directory, Path(allowed["working_directory"]))
        ):
            return PolicyDecision(True, "Exact command is allowlisted")
    raise PolicyError("PowerShell command or working directory is not allowlisted")


def _extract_targets(
    tool: str, arguments: Mapping[str, Any], repository_root: Path
) -> list[Path]:
    values: list[str] = []
    path_keys = {"path", "filepath", "file_path", "target", "directory", "directories"}

    def visit(value: Any, key: str = "") -> None:
        normalized_key = key.casefold().replace("-", "_")
        if normalized_key in {"path", "filepath", "file_path", "target", "directory"}:
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, list):
                values.extend(item for item in value if isinstance(item, str))
            return
        if isinstance(value, Mapping):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for item in value:
                visit(item, key)

    for key, value in arguments.items():
        if str(key).casefold() in path_keys:
            visit(value, str(key))

    if tool == "apply_patch":
        patch_text = arguments.get("patch")
        if isinstance(patch_text, str):
            values.extend(
                match.group(1).strip()
                for match in re.finditer(
                    r"^\*\*\* (?:Update|Add|Delete) File: (.+)$",
                    patch_text,
                    re.MULTILINE,
                )
            )
    if tool == "glob" and not values and isinstance(arguments.get("pattern"), str):
        pattern = arguments["pattern"]
        prefix = re.split(r"[*?\[]", pattern, maxsplit=1)[0].rstrip("/\\")
        values.append(prefix or ".")

    targets = []
    for value in values:
        targets.append(_canonical_path(value, root=repository_root))
    return targets


def _validate_planning_writes(paths: list[Path], root: Path) -> None:
    feature_roots: set[str] = set()
    for path in paths:
        if not _is_within(path, root):
            raise PolicyError("Planning write path is outside the repository")
        try:
            relative = path.relative_to(root)
        except ValueError as error:
            raise PolicyError("Planning write path is outside the repository") from error
        if len(relative.parts) < 2 or relative.parts[0].casefold() != "specs":
            raise PolicyError("Planning policies may write only designated feature artifacts")
        feature_roots.add(os.path.normcase(str(root / relative.parts[0] / relative.parts[1])))
    if len(feature_roots) > 1:
        raise PolicyError("Planning policy cannot write across multiple feature directories")


def _canonical_path(value: Any, *, root: Path | None = None) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise PolicyError("Policy path must be a string")
    raw = os.fspath(value)
    if not raw or "\0" in raw:
        raise PolicyError("Policy path is empty or malformed")
    normalized = raw.replace("/", "\\")
    if normalized.startswith("\\\\") or normalized.startswith("\\\\?\\") or normalized.startswith("\\\\.\\"):
        raise PolicyError("UNC and device paths are not permitted")
    if ".." in re.split(r"[\\/]+", raw):
        raise PolicyError("Path traversal is not permitted")
    path = Path(raw)
    if not path.is_absolute():
        if root is None:
            raise PolicyError("Policy paths must be absolute")
        path = root / path
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise PolicyError("Path cannot be canonicalized") from error


def _is_within(path: Path, parent: Path) -> bool:
    try:
        common = os.path.commonpath((str(path), str(parent)))
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(str(parent))


def _path_conflicts(path: Path, blocked: Path) -> bool:
    return _is_within(path, blocked) or _is_within(blocked, path)


def _is_sensitive_env_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(
        marker in normalized
        for marker in ("token", "secret", "password", "api_key", "apikey", "private_key")
    )


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(str(first)) == os.path.normcase(str(second))