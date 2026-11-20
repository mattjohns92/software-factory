from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from software_factory.policy import (
    ALLOWED_TOOLS,
    HostedAuthorization,
    PolicyError,
    build_sanitized_environment,
    validate_policy,
)
from software_factory.preflight import PreflightReport


REVIEWED_HOOK = ".github/hooks/factory-policy.json"


class RunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class DispatchBoundary:
    inventory_complete: bool
    sandbox_enabled: bool
    available_tools: tuple[str, ...]
    builtin_mcps_disabled: bool
    configured_mcp_servers: tuple[str, ...]
    disabled_mcp_servers: tuple[str, ...]
    plugin_sources: tuple[str, ...]
    hook_sources: tuple[str, ...]
    denied_with_hook: bool
    denied_without_hook: bool
    probe_produced_no_diff: bool
    approved_checks_usable: bool
    runtime_fingerprint: str
    security_probe_fingerprint: str | None


@dataclass(frozen=True)
class NativeRunState:
    run_id: str
    status: str
    current_step: str
    workflow_id: str
    step_results: tuple[Mapping[str, object], ...] = ()
    error: str | None = None
    request: str = ""


def parse_native_run_result(
    result: subprocess.CompletedProcess[str],
    *,
    default_workflow_id: str = "",
) -> NativeRunState:
    if result.returncode != 0:
        raise RunnerError(f"Native workflow exited with status {result.returncode}")
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise RunnerError("Native workflow output is not valid JSON") from error
    return _parse_native_run_payload(payload, default_workflow_id=default_workflow_id)


def get_native_workflow_status(
    run_id: str,
    repository_root: str | os.PathLike[str],
    *,
    source_environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> NativeRunState:
    if not isinstance(run_id, str) or not run_id.strip():
        raise RunnerError("A native run ID is required")
    root = Path(repository_root).resolve()
    specify_executable = (which or shutil.which)("specify")
    if specify_executable is None:
        raise RunnerError("Specify executable is unavailable")
    source = os.environ if source_environment is None else source_environment
    environment = build_sanitized_environment(source)
    run_process = run or subprocess.run
    try:
        result = run_process(
            [specify_executable, "workflow", "status", run_id, "--json"],
            cwd=root,
            env=environment,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise RunnerError(f"Native workflow status command could not start: {error}") from error
    state = parse_native_run_result(result)
    if state.run_id != run_id or state.workflow_id != "speckit":
        raise RunnerError("Native status does not identify the requested speckit run")
    return state


def resume_native_workflow(
    run_id: str,
    gate: str,
    decision: str,
    repository_root: str | os.PathLike[str],
    policy: Mapping[str, object],
    *,
    authorization: HostedAuthorization | None,
    preflight: PreflightReport,
    boundary: DispatchBoundary,
    policy_path: str | os.PathLike[str],
    factory_home: str | os.PathLike[str],
    expected_plan_digest: str | None = None,
    source_environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> subprocess.CompletedProcess[str]:
    if not isinstance(run_id, str) or not run_id.strip():
        raise RunnerError("A native run ID is required")
    gate_inputs = {
        "spec": ("review-spec", "speckit_review_spec_verdict"),
        "plan": ("review-plan", "speckit_review_plan_verdict"),
    }
    if gate not in gate_inputs or decision not in {"approve", "reject"}:
        raise RunnerError("A matching review gate and explicit decision are required")
    if authorization is None or not authorization.authorized or not authorization.provider:
        raise RunnerError("Hosted-use authorization is required before resume")
    if not preflight.ready:
        raise RunnerError("Static preflight has blockers")

    root = Path(repository_root).resolve()
    try:
        validate_policy(
            policy,
            approved_plan_digest=expected_plan_digest,
            expected_root=root,
        )
    except (PolicyError, TypeError, ValueError, OSError) as error:
        raise RunnerError(f"Execution policy is invalid: {error}") from error
    if gate == "plan" and decision == "approve":
        if policy["phase"] != "implementation" or not expected_plan_digest:
            raise RunnerError("Plan approval requires a digest-bound implementation policy")
    elif policy["phase"] != "planning":
        raise RunnerError("This gate decision requires the planning policy")
    _validate_boundary(policy, root, boundary)

    find_executable = which or shutil.which
    specify_executable = find_executable("specify")
    if specify_executable is None:
        raise RunnerError("Specify executable is unavailable")
    copilot_arguments = _copilot_arguments(policy, boundary)
    source = os.environ if source_environment is None else source_environment
    environment = build_sanitized_environment(source, factory_home=factory_home)
    _write_factory_profile(factory_home, policy_path, policy)
    environment["SPECKIT_INTEGRATION_COPILOT_EXTRA_ARGS"] = subprocess.list2cmdline(
        copilot_arguments
    )
    environment["FACTORY_POLICY_PATH"] = str(Path(policy_path).resolve())
    environment["FACTORY_REPOSITORY_ROOT"] = str(root)

    run_process = run or subprocess.run
    try:
        status_result = run_process(
            [specify_executable, "workflow", "status", run_id, "--json"],
            cwd=root,
            env=environment,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
        state = parse_native_run_result(status_result)
        expected_step, verdict_input = gate_inputs[gate]
        if (
            state.run_id != run_id
            or state.workflow_id != "speckit"
            or state.status != "paused"
            or state.current_step != expected_step
        ):
            raise RunnerError("Native run is not paused at the matching approval gate")
        result = run_process(
            [
                specify_executable,
                "workflow",
                "resume",
                run_id,
                "--json",
                "--input",
                f"{verdict_input}={decision}",
            ],
            cwd=root,
            env=environment,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            resumed_state = parse_native_run_result(result, default_workflow_id="speckit")
            if resumed_state.run_id != run_id:
                raise RunnerError("Native resume returned a different run identity")
            if decision == "reject":
                rejected_state = parse_native_run_result(
                    run_process(
                        [specify_executable, "workflow", "status", run_id, "--json"],
                        cwd=root,
                        env=environment,
                        shell=False,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                )
                if (
                    rejected_state.run_id != run_id
                    or rejected_state.workflow_id != "speckit"
                    or rejected_state.status != "paused"
                    or rejected_state.current_step != expected_step
                ):
                    raise RunnerError("Rejected native run did not remain paused at its gate")
        return result
    except OSError as error:
        raise RunnerError(f"Native workflow resume command could not start: {error}") from error


def compute_security_fingerprint(
    policy: Mapping[str, object],
    repository_root: str | os.PathLike[str],
    boundary: DispatchBoundary,
) -> str:
    payload = {
        "repository_root": str(Path(repository_root).resolve()),
        "policy": policy,
        "runtime_fingerprint": boundary.runtime_fingerprint,
        "platform": platform.platform(),
        "toolchain": {
            "specify": "1.0.6",
            "speckit": "1.0.2",
            "copilot": "1.0.114",
        },
        "copilot_arguments": _copilot_arguments(policy, boundary),
        "sandbox_settings": _sandbox_settings(policy),
        "inventory": {
            "sandbox_enabled": boundary.sandbox_enabled,
            "available_tools": sorted(boundary.available_tools),
            "builtin_mcps_disabled": boundary.builtin_mcps_disabled,
            "configured_mcp_servers": sorted(boundary.configured_mcp_servers),
            "disabled_mcp_servers": sorted(boundary.disabled_mcp_servers),
            "plugin_sources": sorted(boundary.plugin_sources),
            "hook_sources": sorted(boundary.hook_sources),
        },
        "probe_results": {
            "denied_with_hook": boundary.denied_with_hook,
            "denied_without_hook": boundary.denied_without_hook,
            "probe_produced_no_diff": boundary.probe_produced_no_diff,
            "approved_checks_usable": boundary.approved_checks_usable,
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def run_native_workflow(
    request: str,
    repository_root: str | os.PathLike[str],
    policy: Mapping[str, object],
    *,
    authorization: HostedAuthorization | None,
    preflight: PreflightReport,
    boundary: DispatchBoundary,
    policy_path: str | os.PathLike[str],
    factory_home: str | os.PathLike[str],
    expected_plan_digest: str | None = None,
    source_environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> subprocess.CompletedProcess[str]:
    root = Path(repository_root).resolve()
    if not isinstance(request, str) or not request.strip():
        raise RunnerError("A non-empty feature request is required")
    if authorization is None or not authorization.authorized or not authorization.provider:
        raise RunnerError("Hosted-use authorization is required before dispatch")
    if not preflight.ready:
        raise RunnerError("Static preflight has blockers")

    try:
        validate_policy(
            policy,
            approved_plan_digest=expected_plan_digest,
            expected_root=root,
        )
    except (PolicyError, TypeError, ValueError, OSError) as error:
        raise RunnerError(f"Execution policy is invalid: {error}") from error

    if policy["phase"] == "implementation" and not expected_plan_digest:
        raise RunnerError("Implementation dispatch requires the approved plan digest")
    if expected_plan_digest is not None and policy["phase"] != "implementation":
        raise RunnerError("Planning dispatch cannot include an approved plan digest")
    _validate_boundary(policy, root, boundary)

    find_executable = which or shutil.which
    specify_executable = find_executable("specify")
    if specify_executable is None:
        raise RunnerError("Specify executable is unavailable")

    copilot_arguments = _copilot_arguments(policy, boundary)

    source = os.environ if source_environment is None else source_environment
    environment = build_sanitized_environment(source, factory_home=factory_home)
    _write_factory_profile(
        factory_home,
        policy_path,
        policy,
    )
    environment["SPECKIT_INTEGRATION_COPILOT_EXTRA_ARGS"] = subprocess.list2cmdline(
        copilot_arguments
    )
    environment["FACTORY_POLICY_PATH"] = str(Path(policy_path).resolve())
    environment["FACTORY_REPOSITORY_ROOT"] = str(root)

    arguments = [
        specify_executable,
        "workflow",
        "run",
        "speckit",
        "--json",
        "--input",
        f"spec={request}",
    ]
    run_process = run or subprocess.run
    try:
        return run_process(
            arguments,
            cwd=root,
            env=environment,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise RunnerError(f"Native workflow command could not start: {error}") from error


def _validate_boundary(
    policy: Mapping[str, object], root: Path, boundary: DispatchBoundary
) -> None:
    boolean_fields = (
        "inventory_complete",
        "sandbox_enabled",
        "builtin_mcps_disabled",
        "denied_with_hook",
        "denied_without_hook",
        "probe_produced_no_diff",
        "approved_checks_usable",
    )
    if any(type(getattr(boundary, field)) is not bool for field in boolean_fields):
        raise RunnerError("Sandbox probe contains malformed boolean evidence")
    string_fields = (
        "available_tools",
        "configured_mcp_servers",
        "disabled_mcp_servers",
        "plugin_sources",
        "hook_sources",
    )
    if any(
        not isinstance(getattr(boundary, field), tuple)
        or any(not isinstance(item, str) for item in getattr(boundary, field))
        for field in string_fields
    ):
        raise RunnerError("Sandbox probe contains malformed inventory evidence")
    if not isinstance(boundary.runtime_fingerprint, str) or not isinstance(
        boundary.security_probe_fingerprint, (str, type(None))
    ):
        raise RunnerError("Sandbox probe fingerprints are malformed")
    if not boundary.inventory_complete:
        raise RunnerError("Hook, MCP, or plugin inventory is incomplete")
    if not boundary.runtime_fingerprint.strip():
        raise RunnerError("Runtime identity is unavailable for security-probe matching")
    if not boundary.sandbox_enabled:
        raise RunnerError("Explicit Copilot sandbox configuration is required")
    tools = policy["allowed_tools"]
    if not isinstance(tools, list) or set(boundary.available_tools) != set(tools):
        raise RunnerError("Available Copilot tools do not match the execution policy")
    if any(tool not in ALLOWED_TOOLS for tool in boundary.available_tools):
        raise RunnerError("Boundary inventory contains an unknown Copilot tool")
    if not boundary.builtin_mcps_disabled:
        raise RunnerError("Built-in Copilot MCP servers must be disabled")
    if set(boundary.configured_mcp_servers) != set(boundary.disabled_mcp_servers):
        raise RunnerError("Every configured MCP server must be enumerated and disabled")
    if len(set(boundary.configured_mcp_servers)) != len(boundary.configured_mcp_servers):
        raise RunnerError("Configured MCP server inventory contains duplicates")
    if boundary.plugin_sources:
        raise RunnerError("Copilot plugins are not permitted")
    if boundary.hook_sources != (REVIEWED_HOOK,):
        raise RunnerError("Hook inventory contains an unknown or unreviewed source")
    if not (
        boundary.denied_with_hook
        and boundary.denied_without_hook
        and boundary.probe_produced_no_diff
        and boundary.approved_checks_usable
    ):
        raise RunnerError("The disposable sandbox probe has not proved the required behavior")
    expected_fingerprint = compute_security_fingerprint(policy, root, boundary)
    if boundary.security_probe_fingerprint != expected_fingerprint:
        raise RunnerError("Security probe does not match the current runtime policy fingerprint")


def _parse_native_run_payload(
    payload: object, *, default_workflow_id: str = ""
) -> NativeRunState:
    if not isinstance(payload, dict):
        raise RunnerError("Native workflow output must be a JSON object")
    run = payload.get("run", payload)
    if not isinstance(run, dict):
        raise RunnerError("Native workflow run state is malformed")
    run_id = run.get("run_id", run.get("id"))
    status = run.get("status", "")
    current_step = run.get("current_step", run.get("currentStep", ""))
    workflow_id = run.get("workflow_id", run.get("workflowId", default_workflow_id))
    raw_step_results = run.get("step_results", run.get("stepResults", []))
    error = run.get("error")
    inputs = run.get("inputs", {})
    if not isinstance(raw_step_results, list) or any(
        not isinstance(item, Mapping) for item in raw_step_results
    ):
        raise RunnerError("Native workflow step results are malformed")
    if error is not None and not isinstance(error, str):
        raise RunnerError("Native workflow error state is malformed")
    if not isinstance(inputs, Mapping):
        raise RunnerError("Native workflow inputs are malformed")
    request = inputs.get("spec", "")
    if not isinstance(request, str):
        request = ""
    if not isinstance(run_id, str) or not run_id.strip():
        raise RunnerError("Native workflow output does not contain a run ID")
    if not all(isinstance(value, str) for value in (status, current_step, workflow_id)):
        raise RunnerError("Native workflow state fields are malformed")
    return NativeRunState(
        run_id,
        status,
        current_step,
        workflow_id,
        tuple(raw_step_results),
        error,
        request,
    )


def _write_factory_profile(
    factory_home: str | os.PathLike[str],
    policy_path: str | os.PathLike[str],
    policy: Mapping[str, object],
) -> None:
    home = Path(factory_home).resolve()
    policy_file = Path(policy_path).resolve()
    if not policy_file.is_relative_to(home):
        raise RunnerError("Factory policy file must be inside the dedicated Copilot home")

    settings = _sandbox_settings(policy)
    _create_or_verify_file(
        home / "settings.json",
        json.dumps(settings, indent=2, sort_keys=True) + "\n",
    )
    _create_or_verify_file(
        policy_file,
        json.dumps(policy, indent=2, sort_keys=True) + "\n",
    )


def _sandbox_settings(policy: Mapping[str, object]) -> dict[str, object]:
    return {
        "sandbox": {
            "enabled": True,
            "addCurrentWorkingDirectory": False,
            "allowDevToolAccess": False,
            "allowBypass": False,
            "sandboxMcpServers": True,
            "sandboxLspServers": True,
            "sandboxExtensions": True,
            "userPolicy": {
                "filesystem": {
                    "readwritePaths": policy["writable_paths"],
                    "readonlyPaths": policy["read_only_paths"],
                    "deniedPaths": policy["denied_paths"],
                },
                "network": {
                    "allowOutbound": False,
                    "allowLocalNetwork": False,
                },
            },
        }
    }


def _copilot_arguments(
    policy: Mapping[str, object], boundary: DispatchBoundary
) -> list[str]:
    tools = policy["allowed_tools"]
    if not isinstance(tools, list):
        raise RunnerError("Policy tool list is malformed")
    arguments = [
        "--sandbox",
        "--available-tools",
        *tools,
        "--disable-builtin-mcps",
        "--no-auto-update",
    ]
    arguments.extend(
        argument
        for server in sorted(boundary.configured_mcp_servers)
        for argument in ("--disable-mcp-server", server)
    )
    return arguments


def _create_or_verify_file(path: Path, expected_content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(expected_content)
    except FileExistsError:
        try:
            actual_content = path.read_text(encoding="utf-8")
        except OSError as error:
            raise RunnerError(f"Existing factory configuration cannot be read: {path}") from error
        if actual_content != expected_content:
            raise RunnerError(f"Refusing to overwrite differing factory configuration: {path}")