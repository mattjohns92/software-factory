from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from software_factory.policy import PolicyError, validate_policy


UNVERIFIED_CHECKS = (
    "authentication",
    "live dispatch",
    "effective sandbox enforcement",
)
EXPECTED_STEPS = ("specify", "review-spec", "plan", "review-plan", "tasks", "implement")
EXPECTED_VERDICT_INPUTS = (
    "speckit_review_spec_verdict",
    "speckit_review_plan_verdict",
)


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[str, ...]
    blockers: tuple[str, ...]
    unverified: tuple[str, ...] = UNVERIFIED_CHECKS

    @property
    def ready(self) -> bool:
        return not self.blockers


def run_static_preflight(
    repository_root: str | Path,
    policy: object,
    *,
    which: Callable[[str], str | None] | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> PreflightReport:
    root = Path(repository_root).resolve()
    find_executable = which or shutil.which
    run_process = run or subprocess.run
    checks: list[str] = []
    blockers: list[str] = []

    try:
        validate_policy(policy, expected_root=root)
        checks.append("Execution policy is valid for this repository")
    except (PolicyError, TypeError, ValueError, OSError) as error:
        blockers.append(f"Execution policy is invalid: {error}")
        return PreflightReport(tuple(checks), tuple(blockers))

    executables = {name: find_executable(name) for name in ("specify", "copilot")}
    for name, path in executables.items():
        if path is None:
            blockers.append(f"Required executable is unavailable: {name}")
    if blockers:
        return PreflightReport(tuple(checks), tuple(blockers))

    commands: Sequence[tuple[list[str], str]] = (
        ([executables["specify"], "--version"], "Specify CLI version"),
        ([executables["copilot"], "--version"], "Copilot CLI version"),
        (
            [executables["specify"], "integration", "status", "--json"],
            "Specify integration status",
        ),
        (
            [executables["specify"], "workflow", "info", "speckit"],
            "Bundled Spec Kit workflow version",
        ),
        (
            [executables["specify"], "workflow", "resolve", "speckit"],
            "Resolved Spec Kit workflow steps",
        ),
    )

    results: dict[str, str] = {}
    for arguments, label in commands:
        try:
            result = run_process(
                arguments,
                cwd=root,
                capture_output=True,
                text=True,
                shell=False,
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            blockers.append(f"{label} check could not run: {error}")
            continue
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit code {result.returncode}"
            blockers.append(f"{label} check failed: {detail}")
            continue
        results[label] = result.stdout

    specify_version = results.get("Specify CLI version", "")
    if re.search(r"\bspecify\s+1\.0\.6\b", specify_version, re.IGNORECASE):
        checks.append("Specify CLI 1.0.6 is installed")
    else:
        blockers.append("Specify CLI version does not match required 1.0.6")

    copilot_version = results.get("Copilot CLI version", "")
    if re.search(r"\b1\.0\.114\b", copilot_version):
        checks.append("Copilot CLI 1.0.114 is installed")
    else:
        blockers.append("Copilot CLI version does not match required 1.0.114")

    integration_output = results.get("Specify integration status", "")
    try:
        integration = json.loads(integration_output)
    except json.JSONDecodeError:
        integration = None
    if (
        isinstance(integration, dict)
        and integration.get("status") == "ok"
        and integration.get("default_integration") == "copilot"
        and "copilot" in integration.get("installed_integrations", [])
        and integration.get("missing_managed_files") == 0
        and integration.get("modified_managed_files") == 0
        and integration.get("invalid_manifest_paths") == 0
        and integration.get("unchecked_manifests") == 0
        and integration.get("findings") == []
    ):
        checks.append("Copilot integration is registered with no managed-file findings")
    else:
        blockers.append("Specify integration status is invalid or reports findings")

    workflow_info = results.get("Bundled Spec Kit workflow version", "")
    if (
        re.search(r"\bVersion:\s*1\.0\.2\b", workflow_info)
        and "Installed" in workflow_info
        and all(input_name in workflow_info for input_name in EXPECTED_VERDICT_INPUTS)
    ):
        checks.append("speckit workflow 1.0.2 with review verdict inputs is installed")
    else:
        blockers.append(
            "speckit workflow 1.0.2 with both review verdict inputs is required"
        )

    resolved_workflow = results.get("Resolved Spec Kit workflow steps", "")
    if "Resolved workflow 'speckit':" in resolved_workflow and all(
        step in resolved_workflow for step in EXPECTED_STEPS
    ):
        checks.append("Resolved speckit workflow contains all required steps")
    else:
        blockers.append("Spec Kit workflow resolution is missing required steps")

    return PreflightReport(tuple(checks), tuple(blockers))