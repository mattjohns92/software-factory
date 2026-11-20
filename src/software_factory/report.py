from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from software_factory.policy import HostedAuthorization
from software_factory.runner import NativeRunState


OUTCOMES = {"verified", "completed-with-limitations", "blocked", "failed"}
CHECK_WORDS = ("test", "check", "lint", "type", "build", "verify", "format")
SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[^\s,;]+"),
)


@dataclass(frozen=True)
class RequiredCheckSet:
    checks: tuple[str, ...]
    sources: Mapping[str, tuple[str, ...]]
    conflicts: tuple[str, ...]
    complete: bool


def collect_required_checks(
    repository_root: str | Path,
    *,
    approved_plan_checks: Sequence[str] = (),
    branch_protection_checks: Sequence[str] | None = None,
    conflicts: Sequence[str] = (),
) -> RequiredCheckSet:
    sources: dict[str, set[str]] = {}
    unresolved = [item for item in conflicts if isinstance(item, str) and item.strip()]

    def add(command: str, source: str) -> None:
        normalized = " ".join(command.strip().split())
        if normalized:
            sources.setdefault(normalized, set()).add(source)

    for command in approved_plan_checks:
        if isinstance(command, str):
            add(command, "approved plan")
        else:
            unresolved.append("Approved plan contains a malformed check requirement")

    root = Path(repository_root)
    repository_files = _repository_requirement_files(root)
    for path in repository_files:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            unresolved.append(f"Required-check source is unreadable: {path.relative_to(root)}")
            continue
        for command in _extract_check_commands(path, content):
            add(command, path.relative_to(root).as_posix())

    complete = branch_protection_checks is not None
    if branch_protection_checks is None:
        pass
    else:
        for command in branch_protection_checks:
            if isinstance(command, str):
                add(command, "owner-supplied branch protection")
            else:
                unresolved.append("Branch-protection requirements contain a malformed check")

    ordered = tuple(sorted(sources))
    return RequiredCheckSet(
        ordered,
        {command: tuple(sorted(sources[command])) for command in ordered},
        tuple(dict.fromkeys(unresolved)),
        complete and not unresolved,
    )


def classify_outcome(
    run_status: str,
    approval_decisions: Sequence[str],
    required_checks: RequiredCheckSet,
    check_results: Sequence[Mapping[str, object]],
    *,
    scope_violations: Sequence[str] = (),
    limitations: Sequence[str] = (),
    review_findings: Sequence[str] = (),
) -> str:
    if run_status.casefold() in {"failed", "error"}:
        return "failed"
    for result in check_results:
        exit_code = result.get("exit_code")
        status = str(result.get("status", "")).casefold()
        if (isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0) or status in {
            "failed",
            "error",
        }:
            return "failed"
    if run_status.casefold() != "completed":
        return "blocked"
    approved = {item.split(":", 1)[0].strip().casefold() for item in approval_decisions if ":" in item and item.split(":", 1)[1].strip().casefold() == "approve"}
    if not {"spec", "plan"}.issubset(approved) or scope_violations or required_checks.conflicts:
        return "blocked"

    results_by_command = {
        str(result.get("command", "")): result for result in check_results
    }
    if any(command not in results_by_command for command in required_checks.checks):
        return "completed-with-limitations"
    for command in required_checks.checks:
        result = results_by_command[command]
        if result.get("status") != "passed" or result.get("exit_code") != 0:
            return "completed-with-limitations"
    if not required_checks.complete or limitations or review_findings:
        return "completed-with-limitations"
    return "verified"


def redact_sensitive(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _repository_requirement_files(root: Path) -> tuple[Path, ...]:
    candidates = [
        *root.glob("README*"),
        *root.glob("CONTRIBUTING*"),
        *root.glob("AGENTS.md"),
        root / ".github" / "copilot-instructions.md",
        *root.glob(".github/workflows/*.yml"),
        *root.glob(".github/workflows/*.yaml"),
        *root.glob(".github/instructions/**/*.instructions.md"),
    ]
    return tuple(sorted({path for path in candidates if path.is_file()}))


def _extract_check_commands(path: Path, content: str) -> tuple[str, ...]:
    commands: set[str] = set()
    if path.suffix.casefold() in {".yml", ".yaml"} and ".github" in path.parts:
        for match in re.finditer(r"(?im)^\s*run\s*:\s*['\"]?([^\r\n]+)", content):
            command = match.group(1).strip().rstrip("'\"")
            if _looks_like_check(command):
                commands.add(command)
    else:
        for match in re.finditer(r"`([^`]+)`", content):
            command = match.group(1).strip()
            if _looks_like_check(command):
                commands.add(command)
        for match in re.finditer(
            r"(?im)^\s*(?:\$\s*)?((?:uv|python(?:\d+(?:\.\d+)?)?|pytest|ruff|mypy|npm|pnpm|yarn)\s+[^\r\n]+)",
            content,
        ):
            command = match.group(1).strip()
            if _looks_like_check(command):
                commands.add(command)
    return tuple(sorted(commands))


def _looks_like_check(command: str) -> bool:
    normalized = command.casefold()
    return any(word in normalized for word in CHECK_WORDS)


def write_delivery_report(
    repository_root: str | Path,
    native_run: NativeRunState,
    *,
    request: str,
    authorization: HostedAuthorization,
    route: str,
    approval_decisions: Sequence[str],
    pre_existing_paths: Sequence[str],
    changed_paths: Sequence[str] | None,
    scope_review: str,
    required_checks: Sequence[Mapping[str, object]],
    known_issues: Sequence[str],
    limitations: Sequence[str],
    next_action: str,
    outcome: str | None = None,
    approved_plan_checks: Sequence[str] = (),
    branch_protection_checks: Sequence[str] | None = None,
    check_conflicts: Sequence[str] = (),
    scope_violations: Sequence[str] = (),
    provenance: Sequence[str] = (),
    roles_skills: Sequence[str] | None = None,
    review_findings: Sequence[str] = (),
    reviewer_type: str = "unknown",
) -> Path:
    if not isinstance(native_run, NativeRunState) or native_run.workflow_id != "speckit":
        raise ValueError("A parsed native speckit run is required")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", native_run.run_id) is None or ".." in native_run.run_id:
        raise ValueError("Native run ID is malformed")
    if not isinstance(authorization, HostedAuthorization) or not authorization.authorized:
        raise ValueError("A real hosted-use authorization is required")
    if outcome is not None and outcome not in OUTCOMES:
        raise ValueError("Unknown delivery outcome")
    if reviewer_type not in {"independent", "self-review", "unknown", "not-reviewed"}:
        raise ValueError("Unknown reviewer type")

    root = Path(repository_root).resolve()
    runs_root = (root / ".specify" / "workflows" / "runs").resolve()
    run_directory = runs_root / native_run.run_id
    if run_directory.is_symlink() or not run_directory.is_dir():
        raise ValueError("Native run directory is unavailable")
    run_directory = run_directory.resolve()
    if not run_directory.is_relative_to(runs_root):
        raise ValueError("Native run directory escapes the run-state root")

    report_path = run_directory / "delivery-report.md"
    if report_path.is_symlink():
        raise ValueError("Refusing to overwrite a linked delivery report")
    required_check_set = collect_required_checks(
        root,
        approved_plan_checks=approved_plan_checks,
        branch_protection_checks=branch_protection_checks,
        conflicts=check_conflicts,
    )
    resolved_outcome = outcome or classify_outcome(
        native_run.status,
        approval_decisions,
        required_check_set,
        required_checks,
        scope_violations=scope_violations,
        limitations=limitations,
        review_findings=review_findings,
    )
    content = _render_report(
        native_run,
        request=request,
        authorization=authorization,
        route=route,
        approval_decisions=approval_decisions,
        pre_existing_paths=pre_existing_paths,
        changed_paths=changed_paths,
        scope_review=scope_review,
        scope_violations=scope_violations,
        required_checks=required_checks,
        required_check_set=required_check_set,
        known_issues=known_issues,
        limitations=limitations,
        provenance=provenance,
        roles_skills=roles_skills,
        review_findings=review_findings,
        reviewer_type=reviewer_type,
        next_action=next_action,
        outcome=resolved_outcome,
    )
    report_path.write_text(content, encoding="utf-8", newline="\n")
    return report_path


def _render_report(
    native_run: NativeRunState,
    *,
    request: str,
    authorization: HostedAuthorization,
    route: str,
    approval_decisions: Sequence[str],
    pre_existing_paths: Sequence[str],
    changed_paths: Sequence[str] | None,
    scope_review: str,
    scope_violations: Sequence[str],
    required_checks: Sequence[Mapping[str, object]],
    required_check_set: RequiredCheckSet,
    known_issues: Sequence[str],
    limitations: Sequence[str],
    provenance: Sequence[str],
    roles_skills: Sequence[str] | None,
    review_findings: Sequence[str],
    reviewer_type: str,
    next_action: str,
    outcome: str,
) -> str:
    categories = ", ".join(_escape(item) for item in authorization.content_categories)
    return "\n".join(
        (
            "# Delivery Report",
            "",
            f"- Outcome: **{_escape(outcome)}**",
            f"- Workflow: `speckit` 1.0.2",
            f"- Native run: `{_escape(native_run.run_id)}`",
            f"- Native status: {_escape(native_run.status or 'unknown')}",
            f"- Current step: {_escape(native_run.current_step or 'unknown')}",
            f"- Route: {_escape(route)}",
            "",
            "## Request",
            "",
            "> " + _escape(request).replace("\n", "\n> "),
            "",
            "## Hosted Authorization",
            "",
            f"- Provider: {_escape(authorization.provider)}",
            f"- Authorized: {'yes' if authorization.authorized else 'no'}",
            f"- Authorized at: {_escape(authorization.authorized_at)}",
            f"- Disclosed content: {categories}",
            "",
            "## Decisions And Changes",
            "",
            "### Approval Decisions",
            "",
            *_list_items(approval_decisions, "No approval decision recorded."),
            "",
            "### Changed Paths",
            "",
            *(
                ["Changed paths have not been measured against a pre-run baseline."]
                if changed_paths is None
                else _list_items(changed_paths, "No changed paths observed.")
            ),
            "",
            "### Pre-existing Paths",
            "",
            *_list_items(pre_existing_paths, "No pre-existing paths observed."),
            "",
            f"Scope review: {_escape(scope_review)}",
            "",
            "Scope violations:",
            *_list_items(scope_violations, "None observed."),
            "",
            "## Required Checks",
            "",
            f"Required-check sources complete: {'yes' if required_check_set.complete else 'no'}",
            *_required_check_items(required_check_set),
            *_check_items(required_checks),
            "",
            "## Review And Follow-Up",
            "",
            f"Reviewer type: {_escape(reviewer_type)}",
            f"Roles and skills: {_escape(', '.join(roles_skills) if roles_skills else 'none/unknown')}",
            "",
            "### Third-Party Provenance",
            "",
            *_list_items(provenance, "None recorded."),
            "",
            "### Review Findings",
            "",
            *_list_items(review_findings, "None recorded."),
            "",
            "### Known Issues",
            "",
            *_list_items(known_issues, "None recorded."),
            "",
            "### Limitations",
            "",
            *_list_items(limitations, "None recorded."),
            "",
            f"Next action: {_escape(next_action)}",
            "",
        )
    )


def _list_items(values: Sequence[str], empty: str) -> list[str]:
    return [f"- {_escape(value)}" for value in values] if values else [empty]


def _check_items(checks: Sequence[Mapping[str, object]]) -> list[str]:
    if not checks:
        return ["No required checks have run."]
    lines = []
    for check in checks:
        name = _escape(str(check.get("name", check.get("command", "unnamed check"))))
        status = _escape(str(check.get("status", "unknown")))
        source = _escape(str(check.get("source", "unknown")))
        exit_code = check.get("exit_code", "unknown")
        lines.append(
            f"- {name}: {status}; source: {source}; exit code: {_escape(str(exit_code))}"
        )
    return lines


def _required_check_items(required: RequiredCheckSet) -> list[str]:
    if not required.checks:
        lines = ["No local required checks were identified."]
    else:
        lines = [
            f"- {_escape(command)}; sources: {_escape(', '.join(required.sources[command]))}"
            for command in required.checks
        ]
    if required.conflicts:
        lines.extend(f"- Unresolved: {_escape(item)}" for item in required.conflicts)
    if not required.complete:
        lines.append("- Branch-protection requirements are incomplete or unavailable.")
    return lines


def _escape(value: str) -> str:
    return html.escape(redact_sensitive(value), quote=False).replace("`", "&#96;")