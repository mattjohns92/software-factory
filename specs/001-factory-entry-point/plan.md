# Implementation Plan: Bootstrap a Native-Workflow-Powered Factory Entry Point

**Branch**: `001-factory-entry-point` | **Date**: 2026-11-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-factory-entry-point/spec.md`

## Summary

Provide a small local Python CLI that discloses the configured agent service and content categories, obtains per-run authorization before hosted inference, performs static prerequisite checks, and delegates one feature request to the installed `speckit` workflow. Spec Kit's persisted run ID, gate decisions, and run status remain authoritative. The factory adds the entry point, explicit approval/resume commands, enforced scope policy, a requirements review, provenance records, and a truthful report; it does not implement a second workflow engine.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Python standard library at runtime; `uv` for project and environment management; GitHub Spec Kit CLI 1.0.6, `speckit` workflow 1.0.2 from the immutable `github/spec-kit` v1.4.2 tag (minimum CLI requirement `>=0.15.1`), and GitHub Copilot CLI 1.0.114 as the observed initial compatibility test tuple. This tuple is a test target, not yet certified. `hatchling` is build-only for the installable console entry point.

**Storage**: Spec Kit run state under `.specify/workflows/runs/<run-id>/` is authoritative. Store one generated delivery report beside that run; do not add a database or duplicate run state. Exclude native run logs and reports from Git.

**Testing**: Python `unittest` for fast unit and subprocess-boundary tests; disposable-repository acceptance tests for native workflow dispatch, approval gates, resume, and reporting.

**Target Platform**: Windows local checkout, PowerShell for documented examples; ordinary Git checkout, no worktrees.

**Project Type**: Python command-line application.

**Performance Goals**: No throughput or model-latency target. Local preflight and status operations must not wait for a model response.

**Constraints**: Preserve native Spec Kit state; never inject approval values on initial run; invoke child commands without a shell; do not automatically log in or perform external/destructive actions. Before any hosted request or repository context is sent, disclose the configured provider, data categories, and possible plan-usage consumption and obtain explicit per-run authorization. Construct a sanitized child environment; set `SPECKIT_COPILOT_ALLOW_ALL_TOOLS=0`, `SPECKIT_ALLOW_ALL_TOOLS=0`, and `COPILOT_ALLOW_ALL=false`; discard inherited executable/extra-argument overrides and raw token variables; preserve only the owner-approved credential-store mechanism. Use a versioned per-run policy bound to the approved-plan digest, with canonical writable/read-only/denied paths, a narrow tool allowlist, and exact local-check command strings plus working directories. Reject traversal, UNC/device paths, and reparse/link escapes. Pin and verify CLI arguments; disable built-in MCPs and enumerate/disable configured MCPs; load no plugins; inventory policy, user, repository, inline, and plugin hook sources. The CLI has no supported “load only this hook” switch; use a dedicated factory profile for user configuration, reject unreviewed project hooks/settings and plugins, and block if policy hooks cannot be inventoried or approved. A factory-owned `preToolUse` hook is defense in depth only: command-hook timeouts fail open to normal permission handling, so the hook MUST NOT be the sole scope boundary. The effective Windows OS sandbox and tool/permission restrictions MUST independently deny out-of-scope access, including when the hook is absent or times out. `factory doctor` checks static configuration only. Before first dispatch for a CLI/runtime/policy fingerprint, require an explicitly authorized disposable-repository probe; repeat it when that fingerprint changes. Do not claim URL denials alone are a network firewall or that a recognized sandbox flag proves enforcement.

**Policy Lifecycle**: The initial native run occurs before an approved plan exists, so it uses `phase=planning` with a null `approved_plan_digest`, writes limited to the current feature's designated Spec Kit planning artifacts, and no application implementation paths. After the owner approves the plan, create a new `phase=implementation` policy bound to that exact plan digest before any implementation tool call. Transition failure or digest mismatch blocks the protected phase.

**Policy Scope Clarification**: Any reference in this plan to a policy bound to the approved-plan digest means the `implementation` policy only. The `planning` policy has a null digest and permits writes only to designated Spec Kit planning artifacts; it must not grant application implementation paths.

**Hook Source Policy**: Permit exactly the reviewed repository hook `.github/hooks/factory-policy.json`, invoking `scripts/factory_pre_tool_use.ps1`. The dedicated `COPILOT_HOME` isolates unrelated user-level settings/hooks but does not suppress repository or administrator policy hooks. Inventory those separately and block if any unreviewed repository, inline, plugin, or unknown policy hook is present.

**Story Delivery Boundary**: US1's minimum report contains the actual native run identity and status, request, hosted authorization and approval decisions, changed paths, scope-review result, required checks and actual outcomes, known issues, limitations, and next action. US3 extends that report with third-party provenance and actionable requirements-review findings, including independent/self-review labeling. This keeps US1 independently deliverable while reserving the deeper provenance and review reconciliation for US3.

**Policy Enforcement Tests**: Unit tests must assert that malformed, stale, mismatched, or out-of-scope policy configuration blocks before the native workflow subprocess is invoked. Separately, the disposable acceptance probe must verify that a runtime out-of-scope write is denied independently of the supplemental hook, as specified in the Phase 0 gate.

**Scale/Scope**: One local owner and one feature request per invocation. Feature delivery only; bug workflow, role/skill packaging, automatic repair, cross-repository installation, and self-development proof are deferred.

## Constitution Check

_GATE: Must pass before Phase 0 research. Re-check after Phase 1 design._

| Principle                                     | Gate             | Plan decision                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| --------------------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| I. Spec Kit Remains the Foundation            | PASS             | Invoke the installed `speckit` workflow and use its run state/artifacts. The factory owns no parallel phase tracker.                                                                                                                                                                                                                                                                                                                                                                          |
| II. Product-Owner Authority and Approvals     | PASS             | Hosted inference requires a separate per-run authorization after provider/data disclosure. Specification and plan approvals remain native gates and are supplied only in an explicit resume action.                                                                                                                                                                                                                                                                                           |
| III. Roles, Delegation and Relevant Expertise | PASS             | No independent-agent claim is required for this first slice. The report lists only roles or skills evidenced by the run.                                                                                                                                                                                                                                                                                                                                                                      |
| IV. Evidence-Based Quality                    | PASS             | Record actual run state, changed paths, command results, required-check evidence, and a requirements/scope review with actionable findings labeled independent or self-review.                                                                                                                                                                                                                                                                                                                |
| V. Security, Provenance and Permissions       | CONDITIONAL PASS | Per-run consent precedes hosted traffic. A least-privilege child environment and phase-specific policy govern exact tools, paths, and check commands; only the implementation policy is digest-bound. Inventory hook/MCP/plugin sources; the CLI has no reliable hook-source allowlist and hook timeouts fail open, so the hook is supplemental. The Windows sandbox must independently deny out-of-scope access; no workflow dispatch is permitted until the disposable policy probe passes. |
| VI. Simplicity and Developer Experience       | PASS             | Use a standard-library CLI adapter and the existing Spec Kit process; no service, database, or worktree.                                                                                                                                                                                                                                                                                                                                                                                      |
| VII. Controlled Self-Improvement              | PASS             | This bootstrap remains a reviewed Spec Kit feature with an explicit baseline (no existing application/tests), defined acceptance scenarios, and rollback through ordinary Git. It does not modify the constitution or authorize later self-modification.                                                                                                                                                                                                                                      |
| VIII. Traceability, Transparency and Delivery | PASS             | Keep the native run ID and produce one report per run from persisted status and observed evidence.                                                                                                                                                                                                                                                                                                                                                                                            |

The constitution file is still marked draft and pending owner ratification. This plan applies its constraints but does not imply ratification or change its authority rules. Security is a release gate: dispatch must not proceed unless the sanitized environment, exact policy profile, hook/MCP/plugin inventory, and effective Windows sandbox have been verified. Do not copy the full parent environment into the Spec Kit subprocess; retain only required Windows process variables, pinned executable paths, non-secret settings, and the owner-approved credential-store access. If the user's setup depends on raw token environment variables, block rather than forward those secrets to the agent process. A hook timeout falls through to normal permission handling by CLI design; therefore the sandbox and restrictive tool permissions must continue to deny prohibited access independently. Copilot's hosted inference network path is disclosed and consented to; this does not authorize network-capable agent tools.

### Phase 0 Gate Result

CONDITIONAL PASS for design and static prerequisite validation only. The repository has an installed `speckit` workflow and the CLI exposes native run, status, and resume commands. `factory doctor` can verify executable/version presence, integration registration/integrity, policy configuration, and workflow resolution; it cannot prove authentication, live dispatch, or effective Windows sandbox enforcement. Before enabling native workflow dispatch for a CLI/runtime/policy fingerprint, an owner-authorized disposable-repository probe must verify runtime sandbox status/policy, denied out-of-scope access with the hook active and absent/timed out, exact tool/command restrictions, and absence of unreviewed MCP/plugin/hook execution. A probe that can only demonstrate the pre-tool hook's denial is insufficient because hook timeouts fail open. If any control is unsupported or unobservable, stop without dispatch. If a probe or later dispatch fails after native state may have been created, inspect/report actual state and any real run ID; if state cannot be determined, report it as unconfirmed, never as absent or simulated.

### Post-Design Constitution Check

PASS for Principles I-IV and VI-VIII: the design preserves native Spec Kit state, separates owner consent from approval gates, records evidence and provenance, and includes a final scope/requirements review. Principle V remains CONDITIONAL PASS until the disposable policy probe proves the pinned Windows sandbox and restrictive tool permissions deny out-of-scope actions independently of the supplemental hook, and confirms no unreviewed MCP/plugin/hook is active. No workflow implementation dispatch is allowed before that gate passes. The constitution remains draft; this plan does not imply ratification.

## Project Structure

### Documentation (this feature)

```text
specs/001-factory-entry-point/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── cli.md
└── tasks.md             # Generated by /speckit-tasks, not this plan
```

### Source Code (repository root)

```text
pyproject.toml
uv.lock
.github/
└── hooks/
    └── factory-policy.json  # Factory-owned supplemental preToolUse hook
scripts/
└── factory_pre_tool_use.ps1 # Windows hook adapter; denies malformed events
src/
└── software_factory/
    ├── __init__.py
    ├── __main__.py
    ├── cli.py                 # argparse commands and exit status
    ├── preflight.py           # static executable/version/integration/workflow checks
    ├── policy.py              # consent record and fail-closed tool/path policy
    ├── runner.py              # sanitized, shell-free Spec Kit subprocess boundary
    └── report.py              # report from persisted run and observed Git/check evidence
tests/
├── unit/
│   ├── test_cli.py
│   ├── test_preflight.py
│   ├── test_policy.py
│   ├── test_runner.py
│   ├── test_resume.py
│   └── test_report.py
└── integration/
    └── test_specify_workflow.py  # opt-in, disposable repository only
```

**Structure Decision**: One installable Python CLI package with a small subprocess adapter and policy module. A generated versioned policy binds the approved-plan digest to canonical writable/read-only/denied path lists, the pinned tool-name allowlist, and exact permitted local-check command strings and working directories. Reject ambiguous paths, UNC/device paths, traversal, and link/reparse escapes. Unit tests fake external commands and hook payloads, including string/object argument forms and malformed input. The factory-owned pre-tool hook denies unknown or malformed events by default but is supplemental because CLI hook timeouts fail open. The effective Windows OS sandbox and restrictive CLI tool policy must independently enforce scope. Since the CLI combines hooks from policy, user, repository, inline settings, and plugins and has no supported single-hook allowlist, use a dedicated factory user profile, inventory every source (including non-disableable policy hooks), reject unreviewed project hook/settings/plugin sources, and block if sources cannot be enumerated or reviewed. The disposable acceptance probe validates denial even with the hook absent/timed out before native workflow dispatch is enabled for that runtime/policy fingerprint. The upstream `speckit` workflow declares empty-default approval inputs; the project-local overlay changes rejection to retry, and resolution is validated before any run. Repository-required and approved-plan checks form a union; conflicts block a verified outcome pending owner resolution and cannot be waived by the plan. `research.md` records provenance for each adopted/executed external component; no Copilot CLI binaries are bundled or modified.

The digest-binding statement in the Structure Decision applies only to the implementation policy. The separate planning policy has a null digest and is limited to designated Spec Kit planning artifact writes.

## Complexity Tracking

Planning and implementation use separate policy instances because the planning phase necessarily precedes plan approval. The planning policy is restricted to Spec Kit artifacts; only the approved-plan-bound implementation policy grants application-source writes.

No constitution violations are planned; no complexity exceptions are required.
