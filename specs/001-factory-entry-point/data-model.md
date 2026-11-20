# Data Model: Factory Entry Point

The factory does not own an independent run database. These are the concepts it reads, validates, or reports from the native Spec Kit run and its local evidence.

## Workflow Run

**System of record**: Spec Kit, under `.specify/workflows/runs/<run-id>/`.

**Fields used by the factory**:

- `run_id`: Native Spec Kit identifier; required for status, resume, and report location.
- `workflow_id` and workflow version: Expected to identify the installed `speckit` process.
- `status`: Native lifecycle state such as running, paused, failed, or completed.
- `current_step`: Current workflow step, especially `review-spec` or `review-plan` when paused.
- `inputs`: Original feature request and integration selection; approval inputs are supplied only through explicit resume.
- `step_results`: Completed steps, gate choices, command outcomes, and timestamps available from persisted native state.
- `error`: Actual dispatch or step failure, when present.
- `hosted_authorization`: Provider identity, disclosed content categories, explicit decision, and timestamp. This is separate from specification/plan approval and is required before dispatch.
- `approved_scope`: Writable path set and allowed local-check commands derived from the owner-approved plan.
- `scope_review`: Observed paths/actions, allow/deny decisions, review findings, and reviewer type.

**Validation**: The requested run ID must resolve to a native run for the expected workflow. Resume is allowed only for a native resumable state and the expected current gate. A missing or malformed state is reported as blocked; it is never reconstructed as a new run.

## Approval Decision

**System of record**: The native gate step result for the run.

**Fields used by the factory**:

- `run_id`: Parent workflow run.
- `gate_id`: `review-spec` or `review-plan`.
- `decision`: Explicit `approve` or `reject`; no value, silence, or generated content is approval.
- `recorded_at`: Native decision time, if present.

**State transitions**:

| Current state                    | Owner action          | Result                                                                        |
| -------------------------------- | --------------------- | ----------------------------------------------------------------------------- |
| Paused at review gate            | Approve current gate  | Resume the same run and continue to its next step.                            |
| Paused at review gate            | Reject current gate   | Keep the same run paused at that gate; do not enter the protected next phase. |
| Running or paused outside a gate | Attempt gate decision | Reject the command without changing native state.                             |
| Unknown run or inconsistent gate | Attempt resume        | Block and report the mismatch; do not create another run.                     |

The project-local overlay uses Spec Kit's native gate verdict input and `on_reject: retry`. The initial factory run never supplies either approval value.

## Hosted-Agent Authorization

**Lifecycle**: Authorization is captured before any request or repository context is sent. If refused, no native run is created and no native run ID or per-run report is fabricated. If accepted, the decision is attached to the resulting native run.

**Fields**:

- Configured inference provider identity.
- Disclosed categories of content that may be transmitted, including the feature request, relevant repository content, and selected tool output.
- Explicit owner decision and timestamp; no decision is equivalent to refusal.
- Disclosure that inference may consume subscription quota or credits.

Consent is not persisted across runs and does not authorize external tool actions or either native approval gate.

## Third-Party Provenance

**System of record**: The feature's `research.md` provenance inventory, updated whenever the adopted/executed component set changes.

**Fields**: Component identity, origin, pinned reference/version, license, modifications, intended purpose, review status, and review date. Unknown origin, version, or license blocks adoption/execution pending review; unknown or incompatible licensing blocks redistribution.

## Execution Policy

**Authority**: A policy is phase-specific and valid only for the current feature and pinned CLI/runtime/policy fingerprint. Planning mode exists before an approved plan; implementation mode is bound to the owner-approved plan digest.

**Schema, version 1**:

- `schema_version`: Exact integer `1`.
- `phase`: Exact value `planning` or `implementation`.
- `approved_plan_digest`: `null` in planning mode; required digest of the approved plan in implementation mode.
- `repository_root`: Canonical absolute repository path.
- `writable_paths`, `read_only_paths`, `denied_paths`: Arrays of canonical absolute paths. Writable descendants are permitted only beneath explicit writable roots; denied paths take precedence.
- `allowed_tools`: Exact runtime tool identifiers from the pinned CLI profile; unknown identifiers are invalid.
- `allowed_commands`: Exact PowerShell command text and canonical working directory for each approved local check. No wildcard or prefix matching.

**Validation**: Planning mode permits writes only to designated Spec Kit planning artifacts for the current feature and prohibits application implementation changes. Implementation mode requires a matching non-null approved-plan digest. Reject missing/unknown schema fields, stale plan digests, relative paths, traversal, UNC/device paths, and symlink/reparse escapes. Apply Windows case-insensitive canonical comparison. The policy hook denies malformed/unlisted actions, but is supplemental: runtime acceptance must prove the Windows OS sandbox and tool restrictions deny out-of-scope access even when the hook is absent or times out.

## Scope and Review

**System of record**: The execution policy derived from the approved plan's explicit writable/read-only/denied paths, tool allowlist, and exact check commands, plus actual tool events and Git/check evidence observed for the native run.

**Validation**: A factory-owned pre-tool policy denies unknown tools, unlisted write paths, and non-allowlisted commands. The Windows sandbox and CLI restrictions must independently enforce the protected boundary. The final review compares changed paths and behavior with approved requirements and scope, records actionable findings, and labels independent review or self-review. Any policy uncertainty blocks dispatch; any detected out-of-scope change stops further work and is reported for owner review.

## Delivery Report

**Storage**: One local `delivery-report.md` per native run, beside that run's state. The file is updated when the same run is resumed; it is not an independent run record. Native run state and potentially sensitive logs remain excluded from Git.

**Fields**:

- Original request, workflow ID/version, and native run ID.
- Hosted inference provider, consent decision, disclosed content categories, and authorization time.
- Outcome: `verified`, `completed-with-limitations`, `blocked`, or `failed`.
- Actual gate decisions and their gate IDs.
- Changed paths, with pre-existing work distinguished from changes observed during the run.
- Approved scope and the result of the scope-boundary review.
- Checks actually executed, command identity, exit status, and evidence location where available.
- Required-check sources (approved plan, checked-in CI configuration, repository contributor/instruction documentation, and owner-supplied branch protection), any conflict, and owner resolution.
- Review findings and whether the review was independent or self-review.
- Third-party execution components and their provenance record references.
- Roles/skills actually invoked; absence of evidence is reported as none/unknown, not inferred.
- Known issues, skipped/unavailable checks, and next action.

**Validation**: Required checks are the union of approved-plan checks, checks explicitly required by checked-in CI configuration or repository contributor/instruction documentation, and branch-protection checks supplied by the owner. The plan cannot waive a repository mandate. If remote-only branch-protection requirements are unavailable, the check set is incomplete and cannot be verified. An unresolved conflict blocks a verified outcome and is referred to the owner. `verified` requires all required checks to have run and pass. A missing integration or required approval is `blocked`; a failed command/check is `failed`; completed work with a skipped optional or unavailable required check is never called verified.
