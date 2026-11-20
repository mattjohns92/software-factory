from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from software_factory.policy import HostedAuthorization, PolicyError, authorize_hosted_use
from software_factory.preflight import PreflightReport, run_static_preflight
from software_factory.report import write_delivery_report
from software_factory.runner import (
    DispatchBoundary,
    RunnerError,
    get_native_workflow_status,
    parse_native_run_result,
    run_native_workflow,
    resume_native_workflow,
)


CONTENT_CATEGORIES = (
    "feature request",
    "relevant repository content",
    "selected tool output",
)
FEATURE_VERBS = ("add", "build", "create", "implement", "introduce", "support")
BUG_TERMS = ("bug", "broken", "fix", "regression", "repair")


def load_policy(
    repository_root: str | os.PathLike[str] | None = None,
    *,
    implementation: bool = False,
) -> dict[str, Any]:
    root = Path.cwd() if repository_root is None else Path(repository_root)
    configured_path = None if implementation else os.environ.get("FACTORY_POLICY_CONFIG")
    default_name = "implementation-policy.json" if implementation else "policy.json"
    path = Path(configured_path) if configured_path else root / ".factory" / default_name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError(f"Execution policy configuration is unavailable: {path}") from error
    if not isinstance(value, dict):
        raise PolicyError("Execution policy configuration must be a JSON object")
    return value


def load_security_probe(
    repository_root: str | os.PathLike[str] | None = None,
    *,
    phase: str = "planning",
) -> DispatchBoundary:
    if phase not in {"planning", "implementation"}:
        raise RunnerError("Unknown security-probe policy phase")
    root = Path.cwd() if repository_root is None else Path(repository_root)
    path = root / ".factory" / f"security-probe-{phase}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunnerError(f"Disposable sandbox probe evidence is unavailable: {path}") from error
    if not isinstance(value, dict):
        raise RunnerError("Disposable sandbox probe evidence must be a JSON object")
    expected = set(DispatchBoundary.__dataclass_fields__)
    if set(value) != expected:
        raise RunnerError("Disposable sandbox probe evidence has missing or unknown fields")
    for field in (
        "available_tools",
        "configured_mcp_servers",
        "disabled_mcp_servers",
        "plugin_sources",
        "hook_sources",
    ):
        if not isinstance(value[field], list):
            raise RunnerError(f"Disposable sandbox probe field {field} must be a list")
        if any(not isinstance(item, str) for item in value[field]):
            raise RunnerError(f"Disposable sandbox probe field {field} must contain strings")
        value[field] = tuple(value[field])
    for field in (
        "inventory_complete",
        "sandbox_enabled",
        "builtin_mcps_disabled",
        "denied_with_hook",
        "denied_without_hook",
        "probe_produced_no_diff",
        "approved_checks_usable",
    ):
        if type(value[field]) is not bool:
            raise RunnerError(f"Disposable sandbox probe field {field} must be boolean")
    if not isinstance(value["runtime_fingerprint"], str) or not value["runtime_fingerprint"].strip():
        raise RunnerError("Disposable sandbox runtime fingerprint is unavailable")
    if value["security_probe_fingerprint"] is not None and not isinstance(
        value["security_probe_fingerprint"], str
    ):
        raise RunnerError("Disposable sandbox probe fingerprint is malformed")
    return DispatchBoundary(**value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="factory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="check static local prerequisites")
    run_parser = commands.add_parser("run", help="start a native feature workflow")
    run_parser.add_argument("--type", choices=("feature",), required=True)
    run_parser.add_argument("--authorize-hosted-agent", action="store_true")
    run_parser.add_argument("request")
    status_parser = commands.add_parser("status", help="inspect a native workflow run")
    status_parser.add_argument("run_id")
    resume_parser = commands.add_parser("resume", help="continue a paused native workflow run")
    resume_parser.add_argument("run_id")
    resume_parser.add_argument("--gate", choices=("spec", "plan"), required=True)
    resume_parser.add_argument("--decision", choices=("approve", "reject"), required=True)
    arguments = parser.parse_args(argv)

    root = Path.cwd().resolve()
    if arguments.command == "doctor":
        return _doctor(root)
    if arguments.command == "run":
        return _run_feature(arguments, root)
    if arguments.command == "status":
        return _status(arguments.run_id, root)
    return _resume(arguments, root)


def _doctor(root: Path) -> int:
    try:
        policy = load_policy(root)
    except PolicyError as error:
        report = PreflightReport((), (str(error),))
    else:
        report = run_static_preflight(root, policy)
    for check in report.checks:
        print(f"PASS: {check}")
    for blocker in report.blockers:
        print(f"BLOCKED: {blocker}")
    print("Unverified: " + ", ".join(report.unverified))
    return 0 if report.ready else 1


def _run_feature(arguments: argparse.Namespace, root: Path) -> int:
    request = arguments.request.strip()
    route_error = _feature_request_error(request)
    if route_error:
        print(route_error)
        return 2

    provider = os.environ.get("FACTORY_HOSTED_PROVIDER", "").strip()
    if not provider:
        print("BLOCKED: Hosted inference provider is not configured or identifiable.")
        return 2

    try:
        policy = load_policy(root)
        if policy.get("phase") != "planning":
            raise PolicyError("Initial feature runs require the planning policy")
        boundary = load_security_probe(root, phase="planning")
    except (PolicyError, RunnerError) as error:
        print(f"BLOCKED: {error}")
        return 2

    preflight = run_static_preflight(root, policy)
    if not preflight.ready:
        for blocker in preflight.blockers:
            print(f"BLOCKED: {blocker}")
        return 2

    print(f"Provider: {provider}")
    print("May transmit: feature request, relevant repository content, and selected tool output.")
    print("Hosted inference may consume subscription quota or credits.")
    if arguments.authorize_hosted_agent:
        accepted = True
    elif not sys.stdin.isatty():
        print("BLOCKED: Non-interactive runs require --authorize-hosted-agent after reviewing this disclosure.")
        return 2
    else:
        accepted = input("Authorize hosted use for this run? [yes/no] ").strip().casefold() == "yes"
    if not accepted:
        print("BLOCKED: Hosted use was not authorized; no workflow was invoked.")
        return 2

    try:
        authorization = authorize_hosted_use(
            provider, list(CONTENT_CATEGORIES), accepted=True
        )
    except PolicyError as error:
        print(f"BLOCKED: {error}")
        return 2

    print("Route: feature -> speckit")
    print(f"Scope: {request}")
    pre_existing_snapshot = _git_status_snapshot(root)
    factory_home = root / ".factory" / "copilot-home"
    policy_path = factory_home / "policy.json"
    try:
        result = run_native_workflow(
            request,
            root,
            policy,
            authorization=authorization,
            preflight=preflight,
            boundary=boundary,
            policy_path=policy_path,
            factory_home=factory_home,
        )
    except RunnerError as error:
        print(f"BLOCKED: {error}")
        return 2
    if result.returncode != 0:
        print(f"FAILED: Native workflow exited with status {result.returncode}.")
        return 1

    try:
        native_run = parse_native_run_result(result, default_workflow_id="speckit")
    except RunnerError:
        print("BLOCKED: Native workflow output did not confirm a run ID; native state is unconfirmed.")
        return 1
    print(f"Native run: {native_run.run_id} ({native_run.status or 'status unavailable'})")
    try:
        _store_authorization(
            root, native_run.run_id, authorization, request, pre_existing_snapshot
        )
    except (OSError, ValueError) as error:
        print(f"BLOCKED: Native run exists, but its authorization record could not be stored: {error}")
        return 1
    post_run_snapshot = _git_status_snapshot(root)
    changed_paths = _changed_since_baseline(pre_existing_snapshot, post_run_snapshot)
    if native_run.current_step == "review-spec":
        decisions = ("spec: pending", "plan: not reached")
        next_action = "Review the generated specification."
    else:
        decisions = ("Approval decisions require native-state reconciliation.",)
        next_action = "Inspect native workflow status and the current approval gate."
    outcome = (
        "failed"
        if native_run.status.casefold() in {"failed", "error"}
        else "blocked"
        if native_run.status.casefold() == "paused"
        else "completed-with-limitations"
    )
    limitations = [
        "Implementation, required checks, and final scope review have not run yet."
    ]
    if changed_paths is None:
        limitations.append("Git path evidence was unavailable; changed paths are not measured.")
    try:
        report_path = write_delivery_report(
            root,
            native_run,
            request=request,
            authorization=authorization,
            route="feature -> speckit",
            approval_decisions=decisions,
            pre_existing_paths=sorted(pre_existing_snapshot or ()),
            changed_paths=changed_paths,
            scope_review="Implementation has not begun; scope review is pending plan approval.",
            required_checks=(),
            known_issues=("Not yet evaluated.",),
            limitations=tuple(limitations),
            next_action=next_action,
            outcome=outcome,
        )
    except (OSError, ValueError) as error:
        print(f"BLOCKED: Native run exists, but its delivery report could not be written: {error}")
        return 1
    print(f"Delivery report: {report_path}")
    return 0


def _status(run_id: str, root: Path) -> int:
    try:
        state = get_native_workflow_status(run_id, root)
    except RunnerError as error:
        print(f"BLOCKED: {error}")
        return 2
    print(f"Run: {state.run_id}")
    print(f"Status: {state.status or 'unknown'}")
    print(f"Current step: {state.current_step or 'unknown'}")
    try:
        report_path = _refresh_delivery_report(root, state)
    except (OSError, PolicyError, ValueError) as error:
        print(f"Report not updated: {error}")
    else:
        if report_path is not None:
            print(f"Delivery report: {report_path}")
    return 0


def _resume(arguments: argparse.Namespace, root: Path) -> int:
    try:
        authorization = _load_authorization(root, arguments.run_id)
        implementation = arguments.gate == "plan" and arguments.decision == "approve"
        expected_digest = None
        if implementation:
            planning_policy = load_policy(root)
            expected_digest = _approved_plan_digest(planning_policy)
        policy = load_policy(root, implementation=implementation)
        if implementation and policy.get("approved_plan_digest") != expected_digest:
            raise PolicyError("Implementation policy does not match the approved plan")
        boundary = load_security_probe(
            root, phase="implementation" if implementation else "planning"
        )
    except (OSError, PolicyError, RunnerError, ValueError) as error:
        print(f"BLOCKED: {error}")
        return 2

    preflight = run_static_preflight(root, policy)
    if not preflight.ready:
        for blocker in preflight.blockers:
            print(f"BLOCKED: {blocker}")
        return 2

    factory_home = root / ".factory" / "copilot-home"
    try:
        result = resume_native_workflow(
            arguments.run_id,
            arguments.gate,
            arguments.decision,
            root,
            policy,
            authorization=authorization,
            preflight=preflight,
            boundary=boundary,
            policy_path=factory_home / "policy.json",
            factory_home=factory_home,
            expected_plan_digest=expected_digest,
        )
    except RunnerError as error:
        print(f"BLOCKED: {error}")
        return 2
    if result.returncode != 0:
        try:
            state = get_native_workflow_status(arguments.run_id, root)
            _refresh_delivery_report(
                root,
                state,
                extra_known_issues=(
                    f"Native workflow resume exited with status {result.returncode}.",
                ),
            )
        except (OSError, PolicyError, RunnerError, ValueError):
            pass
        print(f"FAILED: Native workflow resume exited with status {result.returncode}.")
        return 1
    try:
        resumed = parse_native_run_result(result, default_workflow_id="speckit")
        if resumed.run_id != arguments.run_id:
            raise RunnerError("Native resume returned a different run identity")
        state = get_native_workflow_status(arguments.run_id, root)
        report_path = _refresh_delivery_report(root, state)
    except (OSError, PolicyError, RunnerError, ValueError):
        print("BLOCKED: Resume completed, but native status or report refresh is unavailable.")
        return 1
    print(f"Native run: {state.run_id} ({state.status or 'status unavailable'})")
    if report_path is not None:
        print(f"Delivery report: {report_path}")
    return 0


def _store_authorization(
    root: Path,
    run_id: str,
    authorization: HostedAuthorization,
    request: str,
    pre_existing_snapshot: dict[str, str] | None,
) -> None:
    run_directory = _native_run_directory(root, run_id)
    if not run_directory.is_dir():
        raise ValueError("native run directory is unavailable")
    path = run_directory / "hosted-authorization.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(
            {
                **asdict(authorization),
                "request": request,
                "pre_existing_snapshot": pre_existing_snapshot,
            },
            stream,
            indent=2,
            sort_keys=True,
        )
        stream.write("\n")


def _load_authorization(root: Path, run_id: str) -> HostedAuthorization:
    path = _native_run_directory(root, run_id) / "hosted-authorization.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError("The run has no valid recorded hosted-use authorization") from error
    if not isinstance(value, dict) or not {
        "provider",
        "content_categories",
        "authorized",
        "authorized_at",
    }.issubset(value) or set(value) - {
        "provider",
        "content_categories",
        "authorized",
        "authorized_at",
        "request",
        "pre_existing_snapshot",
    }:
        raise PolicyError("The run's hosted-use authorization record is malformed")
    categories = value["content_categories"]
    if (
        not isinstance(value["provider"], str)
        or not isinstance(categories, list)
        or any(not isinstance(item, str) for item in categories)
        or value["authorized"] is not True
        or not isinstance(value["authorized_at"], str)
    ):
        raise PolicyError("The run's hosted-use authorization record is malformed")
    return HostedAuthorization(
        value["provider"], tuple(categories), True, value["authorized_at"]
    )


def _load_run_metadata(root: Path, run_id: str) -> dict[str, Any]:
    path = _native_run_directory(root, run_id) / "hosted-authorization.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError("The run metadata is unavailable") from error
    if not isinstance(value, dict):
        raise PolicyError("The run metadata is malformed")
    request = value.get("request")
    pre_existing_snapshot = value.get("pre_existing_snapshot")
    if not isinstance(request, str) or (
        pre_existing_snapshot is not None
        and (
            not isinstance(pre_existing_snapshot, dict)
            or any(
                not isinstance(path, str) or not isinstance(digest, str)
                for path, digest in pre_existing_snapshot.items()
            )
        )
    ):
        raise PolicyError("The run metadata is malformed")
    return {"request": request, "pre_existing_snapshot": pre_existing_snapshot}


def _refresh_delivery_report(
    root: Path,
    native_run,
    *,
    extra_known_issues: tuple[str, ...] = (),
) -> Path | None:
    try:
        metadata = _load_run_metadata(root, native_run.run_id)
        authorization = _load_authorization(root, native_run.run_id)
    except PolicyError:
        return None

    baseline = metadata["pre_existing_snapshot"]
    current = _git_status_snapshot(root)
    changed = _changed_since_baseline(baseline, current)
    pre_existing = sorted(baseline or ())
    decisions = _observed_approval_decisions(native_run)
    check_results = _observed_check_results(native_run)
    violations = _observed_scope_violations(root, changed or ()) if changed is not None else ()
    limitations = []
    if changed is None:
        limitations.append("Git path evidence was unavailable; changed paths are not measured.")
    elif changed:
        limitations.append(
            "Git path comparison does not attribute writes to planning versus implementation phases."
        )
    if not check_results:
        limitations.append("Native required-check results are unavailable or incomplete.")
    if not {item.split(":", 1)[0] for item in decisions if ":" in item}.issuperset(
        {"spec", "plan"}
    ):
        limitations.append("Native approval decisions are not fully reconciled.")
    if native_run.status.casefold() == "completed":
        limitations.append("Owner-supplied branch-protection checks were not available to the report.")

    known_issues = list(extra_known_issues)
    if native_run.error:
        known_issues.append(native_run.error)
    if not known_issues:
        known_issues.append("None observed in the available native state.")
    review_findings = (
        ("Final requirements and scope review is not evidenced in native run state.",)
        if native_run.status.casefold() == "completed"
        else ()
    )
    if violations:
        scope_review = "Potential out-of-scope paths were observed."
    elif changed is None:
        scope_review = "Scope comparison is unavailable because Git path evidence is missing."
    else:
        scope_review = (
            "Changed paths were compared with configured write roots; per-action phase timing is unavailable."
        )
    if native_run.current_step in {"review-spec", "review-plan"}:
        next_action = f"Owner decision required at {native_run.current_step}."
    elif native_run.status.casefold() == "completed":
        next_action = "Resolve report limitations and complete the requirements review."
    elif native_run.status.casefold() in {"failed", "error"}:
        next_action = "Inspect the native error and decide whether to resume or stop."
    else:
        next_action = "Inspect native workflow status and the current step."

    return write_delivery_report(
        root,
        native_run,
        request=native_run.request or metadata["request"],
        authorization=authorization,
        route="feature -> speckit",
        approval_decisions=decisions,
        pre_existing_paths=pre_existing,
        changed_paths=changed,
        scope_review=scope_review,
        required_checks=check_results,
        known_issues=tuple(known_issues),
        limitations=tuple(limitations),
        next_action=next_action,
        approved_plan_checks=_approved_plan_checks(root),
        branch_protection_checks=None,
        scope_violations=violations,
        provenance=(
            "Specify CLI 1.0.6",
            "speckit workflow 1.0.2",
            "Copilot CLI 1.0.114",
        ),
        roles_skills=None,
        review_findings=review_findings,
        reviewer_type="self-review",
    )


def _observed_approval_decisions(native_run) -> tuple[str, ...]:
    decisions: dict[str, str] = {}
    for step in native_run.step_results:
        step_id = str(step.get("step_id", step.get("step", step.get("id", "")))).casefold()
        gate = "spec" if "review-spec" in step_id else "plan" if "review-plan" in step_id else None
        if gate is None:
            continue
        evidence = [step]
        for field in ("result", "output", "data"):
            nested = step.get(field)
            if isinstance(nested, dict):
                evidence.append(nested)
        decision = next(
            (
                str(item.get(key)).casefold()
                for item in evidence
                for key in ("decision", "verdict", "choice")
                if item.get(key) in {"approve", "reject"}
            ),
            None,
        )
        if decision is not None:
            decisions[gate] = decision
    if "spec" not in decisions:
        decisions["spec"] = "pending" if native_run.current_step == "review-spec" else "unknown"
    if "plan" not in decisions:
        decisions["plan"] = "pending" if native_run.current_step == "review-plan" else "not reached"
    return tuple(f"{gate}: {decisions[gate]}" for gate in ("spec", "plan"))


def _observed_check_results(native_run) -> tuple[dict[str, Any], ...]:
    results = []
    for step in native_run.step_results:
        command = step.get("command")
        exit_code = step.get("exit_code")
        if not isinstance(command, str) or not isinstance(exit_code, int):
            continue
        results.append(
            {
                "command": command,
                "name": str(step.get("name", command)),
                "source": "native step result",
                "exit_code": exit_code,
                "status": "passed" if exit_code == 0 else "failed",
            }
        )
    return tuple(results)


def _approved_plan_checks(root: Path) -> tuple[str, ...]:
    try:
        policy = load_policy(root)
    except PolicyError:
        return ()
    plan_paths = [
        Path(path)
        for path in policy.get("writable_paths", [])
        if isinstance(path, str) and Path(path).name.casefold() == "plan.md"
    ]
    if len(plan_paths) != 1:
        return ()
    try:
        content = plan_paths[0].read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ()
    commands = set()
    for match in re.finditer(r"`([^`]+)`", content):
        command = " ".join(match.group(1).split())
        if any(word in command.casefold() for word in ("test", "check", "lint", "build", "verify")):
            commands.add(command)
    return tuple(sorted(commands))


def _observed_scope_violations(root: Path, changed_paths: set[str] | tuple[str, ...]) -> tuple[str, ...]:
    from software_factory.policy import validate_policy

    writable: list[Path] = []
    denied: list[Path] = []
    found_policy = False
    for path in (root / ".factory" / "policy.json", root / ".factory" / "implementation-policy.json"):
        try:
            policy = json.loads(path.read_text(encoding="utf-8"))
            validate_policy(policy, expected_root=root)
        except (OSError, json.JSONDecodeError, PolicyError, TypeError, ValueError):
            continue
        found_policy = True
        writable.extend(Path(item).resolve(strict=False) for item in policy["writable_paths"])
        denied.extend(Path(item).resolve(strict=False) for item in policy["denied_paths"])
    if not found_policy:
        return ("Execution policy evidence is unavailable.",)
    violations = []
    for relative in changed_paths:
        target = (root / relative).resolve(strict=False)
        if any(target.is_relative_to(blocked) for blocked in denied) or not any(
            target.is_relative_to(scope) for scope in writable
        ):
            violations.append(relative)
    return tuple(sorted(violations))


def _native_run_directory(root: Path, run_id: str) -> Path:
    if (
        not isinstance(run_id, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id) is None
        or ".." in run_id
    ):
        raise ValueError("native run ID is malformed")
    runs_root = (root / ".specify" / "workflows" / "runs").resolve()
    run_directory = (runs_root / run_id).resolve()
    if not run_directory.is_relative_to(runs_root):
        raise ValueError("native run directory escapes the run-state root")
    return run_directory


def _approved_plan_digest(planning_policy: dict[str, Any]) -> str:
    plan_paths = [
        Path(path)
        for path in planning_policy.get("writable_paths", [])
        if isinstance(path, str) and Path(path).name.casefold() == "plan.md"
    ]
    if len(plan_paths) != 1:
        raise PolicyError("Planning policy must identify exactly one approved plan.md")
    try:
        content = plan_paths[0].read_bytes()
    except OSError as error:
        raise PolicyError("Approved plan is unavailable for digest verification") from error
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _git_status_snapshot(repository_root: Path) -> dict[str, str] | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=repository_root,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    entries = result.stdout.split("\0")
    snapshot: dict[str, str] = {}
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        relative = entry[3:]
        path = repository_root / relative
        try:
            if path.is_symlink():
                content_digest = hashlib.sha256(os.readlink(path).encode()).hexdigest()
            elif path.is_file():
                content_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                content_digest = "missing"
        except OSError:
            content_digest = "unavailable"
        snapshot[relative] = f"{entry[:2]}:{content_digest}"
        if "R" in entry[:2] or "C" in entry[:2]:
            index += 1
    return snapshot


def _changed_since_baseline(
    baseline: dict[str, str] | None, current: dict[str, str] | None
) -> list[str] | None:
    if baseline is None or current is None:
        return None
    return sorted(
        path
        for path in set(baseline) | set(current)
        if baseline.get(path) != current.get(path)
    )


def _feature_request_error(request: str) -> str | None:
    normalized = request.casefold()
    words = set(normalized.replace("-", " ").split())
    if not request or any(term in words for term in BUG_TERMS):
        return (
            "Blocking question: Is this a new feature or a bug fix? "
            "This entry point supports concrete feature requests only."
        )
    if not any(verb in words for verb in FEATURE_VERBS):
        return (
            "Blocking question: What new capability should be added? "
            "This entry point supports concrete feature requests only."
        )
    return None


