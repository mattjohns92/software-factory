---
description: "Task list for the native-workflow-powered factory entry point"
---

# Tasks: Bootstrap a Native-Workflow-Powered Factory Entry Point

**Input**: Design documents from `specs/001-factory-entry-point/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md), [quickstart.md](quickstart.md)

**Tests**: Unit and opt-in acceptance tests are required by the independent-test criteria and implementation plan. Live tests run only in a disposable repository after the policy probe passes.

**Organization**: Tasks are grouped by the three prioritized user stories. US1 delivers the approved feature happy path; US2 adds rejection/defer behavior; US3 completes evidence and reporting. Static preflight, hosted-use consent, and security policy are foundational prerequisites.

## Format

Every task follows `- [ ] T### [P?] [US?] Description with exact file path`. `[P]` appears only for independent tasks editing different files. Story labels appear only in user-story phases.

## Phase 1: Setup

**Purpose**: Establish the installable CLI package, exclude native run state, and review dependencies before installation.

- [x] T001 Define Python 3.11+ project metadata, Hatchling build backend, `uv` configuration, and the `factory` console entry point with no runtime dependencies in `pyproject.toml`, then generate `uv.lock` using `uv lock`.
- [x] T002 [P] Create `src/software_factory/__init__.py` and `src/software_factory/__main__.py` so the console command and `python -m software_factory` dispatch to the CLI.
- [x] T003 [P] Add Python, virtual-environment, build-output, and `.specify/workflows/runs/` exclusions to `.gitignore` so native run logs and local reports are not committed.
- [x] T004 Review the initial toolchain and locked dependency provenance in `specs/001-factory-entry-point/research.md` before `uv sync`; record origin, pinned version/reference, license, modifications, and purpose for Specify/Spec Kit, Copilot CLI, `uv`, Hatchling, and each resolved package; block installation or redistribution for unknown or incompatible licenses.

## Phase 2: Foundational

**Purpose**: Implement consent, phase-specific execution policies, static prerequisite checks, and native approval-gate configuration required by every story.

- [x] T005 [P] Add tests in `tests/unit/test_policy.py` for per-run hosted-use disclosure/consent, refusal before dispatch, non-persistence, planning/implementation policy transitions, null versus required plan digests, stale digests, Windows path canonicalization, traversal/link rejection, out-of-scope policy configuration, and unknown-policy denial.
- [x] T006 Implement consent records, sanitized environment construction, and version-1 phase-specific policy creation/validation in `src/software_factory/policy.py` using `phase`, `approved_plan_digest`, `repository_root`, `writable_paths`, `read_only_paths`, `denied_paths`, `allowed_tools`, and exact `allowed_commands` with working directories; planning mode permits only designated Spec Kit planning artifacts, and implementation mode requires the approved-plan digest.
- [x] T007 Implement `.github/hooks/factory-policy.json` and `scripts/factory_pre_tool_use.ps1`, with hook parsing/decision tests in `tests/unit/test_policy.py`; handle native and VS Code-compatible payloads, `toolArgs` as either object or JSON string, and deny malformed/unlisted actions. Treat the hook as supplemental because timeouts fail open.
- [x] T008 Implement the shell-free, fail-closed Copilot boundary in `src/software_factory/runner.py` with tests in `tests/unit/test_runner.py`: set the three Spec Kit/Copilot allow-all guards to `0`/`false`; omit inherited executable/extra-argument overrides and raw tokens; require sandbox and fixed tool restrictions; disable built-in MCPs, enumerate/disable configured MCPs, load no plugins, inventory hook sources, and block on unknown/unreviewed sources. Assert malformed, stale, mismatched, or out-of-scope policy configurations cause zero native workflow subprocess invocations. The Windows sandbox/tool policy must independently enforce runtime scope if the hook is absent or times out.
- [x] T009 [P] Add static-prerequisite tests in `tests/unit/test_preflight.py` for executable/version tuple, integration status, workflow resolution, and policy configuration, explicitly asserting that authentication, dispatch, and effective sandbox enforcement remain unverified.
- [x] T010 Implement static-only checks in `src/software_factory/preflight.py` for the Specify 1.0.6 / `speckit` 1.0.2 / Copilot 1.0.114 target tuple, including both declared review verdict inputs, `specify integration status --json`, workflow resolution, and policy configuration; fail before workflow invocation on any static blocker.
- [x] T011 [P] Create `.specify/workflows/overlays/speckit/speckit-approval-retry.yml` preserving the upstream `speckit_review_spec_verdict` and `speckit_review_plan_verdict` inputs, replace both review gates with `on_reject: retry`, register the overlay, and verify resolution without running a workflow.

**Checkpoint**: Unit-level policy and static checks pass. No native workflow dispatch is permitted until the live disposable policy probe (T026) passes for the exact CLI/runtime/policy fingerprint.

## Phase 3: User Story 1 - Deliver a Feature From One Request (Priority: P1)

**Goal**: Obtain explicit hosted-use consent, run one native feature process, honor both approval gates, deliver within approved scope, and report actual checks.

**Independent Test**: In a disposable repository, pass the separate policy probe, authorize hosted use, submit one request, approve its specification and plan, and verify one native run delivers the requested change within scope, runs all applicable required checks, and produces a minimum report containing the actual run identity/status, request, authorization/approval decisions, changed paths, scope-review result, required-check outcomes, limitations, and next action. Verify implementation stays blocked before each approval. Fake-executable unit tests cover consent and dispatch boundaries but do not by themselves prove feature delivery. US3 adds third-party provenance and actionable requirements-review findings, including independent/self-review labeling.

### Tests for User Story 1

- [x] T012 [P] [US1] Add CLI tests in `tests/unit/test_cli.py` for `factory run --type feature`, provider/data/quota disclosure, explicit consent, non-interactive `--authorize-hosted-agent`, visible route/scope, and blocking ambiguous, bug-fix, refused, or unknown-provider requests without dispatch.
- [x] T013 [P] [US1] Add runner tests in `tests/unit/test_runner.py` asserting one `specify workflow run speckit --json` invocation after consent, native run-ID parsing, `shell=False`, no approval verdict on initial run, and same-run explicit approval resume.

### Implementation for User Story 1

- [x] T014 [US1] Implement native workflow start and explicit approve-path resume in `src/software_factory/runner.py`, invoking only after static preflight, matching certified planning-policy fingerprint, and accepted per-run authorization; after plan approval, require transition to an implementation policy bound to that plan digest before implementation; never provide verdicts on initial run.
- [x] T015 [US1] Implement `factory doctor`, `factory run --type feature [--authorize-hosted-agent] "<request>"`, and approved-gate continuation in `src/software_factory/cli.py`; display disclosure before consent and route/scope before dispatch, and preserve the native run identity.
- [x] T016 [US1] Implement the initial `delivery-report.md` in `src/software_factory/report.py`, keyed only by a real native run ID and including actual run status, request, provider authorization, route, observed approvals, changed paths, scope-review result, required checks and actual outcomes, known issues, limitations, next action, outcome, and report path.
- [x] T017 [US1] Add the opt-in end-to-end disposable-repository harness in `tests/integration/test_specify_workflow.py` for one authorized feature request, both native approval gates, within-scope delivery, all required checks, and assertions for every US1 minimum report field including known issues; normal unit-test discovery must never launch Copilot.

**Checkpoint**: The approved happy path delivers one feature in one native run. Live validation is still blocked until T026 passes.

## Phase 4: User Story 2 - Reject or Resume an Approval Gate (Priority: P2)

**Goal**: Let the owner reject or defer a decision, then resume the same native run without treating silence as approval or repeating completed work.

**Independent Test**: Use native status fixtures and the disposable workflow to verify pending/rejected decisions keep protected work blocked, an explicit matching approval resumes the same run, and completed-step history is retained.

### Tests for User Story 2

- [x] T018 [P] [US2] Add tests in `tests/unit/test_resume.py` for pending, rejected, approved, wrong-gate, wrong-run, and non-resumable states; prove silence never approves and invalid states never create another run.

### Implementation for User Story 2

- [x] T019 [US2] Extend native status/resume handling in `src/software_factory/runner.py` to map rejection to the current native verdict input, validate the gate/run identity, and keep rejected runs paused for retry.
- [x] T020 [US2] Complete `factory status <run-id>` and `factory resume <run-id> --gate <spec|plan> --decision <approve|reject>` behavior in `src/software_factory/cli.py`; reject mismatched or non-resumable state without creating a run.
- [x] T021 [US2] Extend `tests/integration/test_specify_workflow.py` with disposable rejection/retry/resume assertions that preserve the run ID and completed-step history.

**Checkpoint**: Pending and rejected gates remain blocked; only an explicit owner decision on the existing native run can continue it.

## Phase 5: User Story 3 - Receive an Evidence-Based Outcome (Priority: P3)

**Goal**: Produce one accurate report tied to native state, consent, approved scope, checks, provenance, and a requirements review.

**Independent Test**: Feed completed, blocked, failed, and limited run fixtures plus changed-path and check evidence into report tests; verify check-source precedence, scope, provenance, actionable findings, reviewer type, secret redaction, and outcome classification.

### Tests for User Story 3

- [x] T022 [P] [US3] Add tests in `tests/unit/test_report.py` for verified/limited/blocked/failed outcomes, the union of approved-plan checks, checked-in CI/instruction requirements, and owner-supplied branch-protection checks; verify unresolved conflicts or unavailable remote-only rules block verification, alongside known issues, limitations, changed/pre-existing paths, scope violations, provenance, roles/skills evidence and none/unknown fallback, review findings, self-review labels, absent evidence, and redaction.

### Implementation for User Story 3

- [x] T023 [US3] Implement report check discovery and outcome classification in `src/software_factory/report.py`; require the union of approved-plan checks, checks explicitly required by checked-in CI configuration or repository contributor/instruction documentation, and branch-protection checks supplied by the owner. Block verified status on unresolved conflicts or unavailable remote-only branch-protection requirements, and include check sources, scope, provenance, roles/skills only when evidenced by the run (otherwise `none`/`unknown`), known issues, limitations, actionable findings, and reviewer type.
- [x] T024 [US3] Refresh the same `delivery-report.md` from native status/resume evidence in `src/software_factory/cli.py` and `src/software_factory/runner.py`, recording actual exits and known issues while separating pre-existing Git changes from changes observed during the run.
- [x] T025 [US3] Extend `tests/integration/test_specify_workflow.py` with report comparisons against native status, actual approvals, changed paths, check results, known issues and limitations, evidence-backed roles/skills (or `none`/`unknown` when absent), and requirements/scope-review evidence.

**Checkpoint**: Every native run has one updated report; missing authorization, scope violations, unresolved required-check conflicts, and failed checks cannot be reported as verified.

## Phase 6: Polish and Cross-Cutting Validation

**Purpose**: Prove the security boundary, validate the package, run native acceptance only when authorized, and record provenance/review results.

- [ ] T026 Verify Windows sandbox/tool policy and hook-source inventory using `specs/001-factory-entry-point/quickstart.md` in a disposable repository: require explicit hosted-use authorization; inspect runtime sandbox policy; prove an out-of-scope write is denied with the hook active and absent/timed out; confirm no unreviewed hook, MCP, or plugin is active and approved checks remain usable. Do not start a native workflow; record evidence and stop if any control is unsupported or unobservable.
- [x] T027 Verify the lockfile with `uv lock --check`, then run `uv sync --locked`, `uv run python -m unittest discover -s tests -v`, `uv run factory doctor`, and `uv build`; record commands, exit codes, limitations, and skipped live checks in `specs/001-factory-entry-point/quickstart.md`.
- [ ] T028 Run `tests/integration/test_specify_workflow.py` only in a disposable Spec Kit repository after T026 passes and with explicit hosted-use authorization and owner approvals at both native gates; verify one-run feature delivery, same-run behavior, required checks, report accuracy, and no external/destructive actions; record results in `specs/001-factory-entry-point/quickstart.md`.
- [x] T029 Reconcile actual Specify/workflow/Copilot versions, policy-probe results, Windows limitations, and remaining blockers in `specs/001-factory-entry-point/research.md`; update provenance for every adopted/executed component and locked dependency, and leave the tuple uncertified if any required acceptance check did not pass.
- [ ] T030 Review actual changes and behavior against `specs/001-factory-entry-point/spec.md` and the approved scope; record actionable findings and independent/self-review status in `specs/001-factory-entry-point/quickstart.md`, and do not claim completion while unresolved findings violate acceptance criteria.

## Dependencies and Execution Order

### Phase Dependencies

- **Setup**: T001-T003 establish the package and local-state exclusions; T004 follows lockfile generation and precedes dependency installation.
- **Foundational**: Depends on Setup. T005, T009, and T011 can proceed independently; T006 follows T005; T007 follows T006; T008 follows T007; T010 follows T009. All foundational tasks block user stories.
- **US1**: Depends on Setup and Foundational. T012 and T013 are separate test files and may run in parallel; implementation follows the relevant tests. US1's live test is not run until T026 passes.
- **US2**: Depends on the US1 native run/approve path. Rejection tests precede runner/CLI extensions; the integration test extends the same file only after the US1 harness exists.
- **US3**: Depends on US1 and US2 lifecycle evidence. Report tests precede report implementation; integration assertions follow the harness.
- **Polish**: T026 follows implementation and is a prerequisite for native dispatch. T028 depends on T026 and package validation; provenance reconciliation and final review follow observed results.

### User Story Dependencies

- **US1 (P1)**: Depends on Setup and Foundational. It includes the approve-path needed to deliver the happy path and is the first demonstrable product increment.
- **US2 (P2)**: Extends US1 with rejection/defer and retry behavior; it does not block the approved US1 happy path.
- **US3 (P3)**: Builds on US1/US2 lifecycle data and adds full evidence/report reconciliation.

### Parallel Opportunities

- **Setup**: T002 and T003 can run in parallel with T001 because they edit distinct files; T004 follows T001's lockfile.
- **Foundational**: T005, T009, and T011 edit separate files and can proceed in parallel. T006/T007/T008 and T009/T010 remain sequential within their dependencies.
- **US1**: T012 and T013 can run in parallel because CLI and runner tests are separate files; implementation follows test contracts.
- **US2**: T018 and T021 can proceed in parallel after the US1 harness exists because unit and integration tests are in separate files; runner/CLI implementation remains sequential where the shared run contract requires it.
- **US3**: T022 and T025 can proceed in parallel once the US1/US2 integration harness exists because unit and integration tests are in separate files; T023/T024 remain sequential where report behavior is shared.
- **Across stories**: Story phases remain sequential because each extends the same native run lifecycle and report.

### Parallel Execution Examples

```text
Foundational:
Task T005: Policy schema and consent tests in tests/unit/test_policy.py
Task T009: Static prerequisite tests in tests/unit/test_preflight.py
Task T011: Native approval overlay in .specify/workflows/overlays/speckit-approval-retry.yml

US1 after Foundational:
Task T012: CLI consent/routing tests in tests/unit/test_cli.py
Task T013: Native run/approve-path tests in tests/unit/test_runner.py

US2 after US1 harness:
Task T018: Gate-state unit tests in tests/unit/test_resume.py
Task T021: Native rejection/resume acceptance in tests/integration/test_specify_workflow.py

US3 after lifecycle harness:
Task T022: Report unit tests in tests/unit/test_report.py
Task T025: Report evidence acceptance in tests/integration/test_specify_workflow.py
```

## Implementation Strategy

1. Complete Setup and Foundational phases; review dependency provenance before installation, validate the phase-specific execution policy, and resolve the native approval overlay without starting a workflow.
2. Deliver US1 as the MVP, including the consented one-request path and approve-path through both native gates. Use fakes for normal tests; do not claim live compatibility.
3. Add US2 rejection/defer/retry behavior and verify that no missing or generated decision advances a gate.
4. Add US3 evidence reconciliation for both check sources, all outcome classes, provenance, and final scope/requirements review.
5. Run the disposable policy probe before any native workflow acceptance. Run workflow acceptance only after the probe passes and the owner authorizes hosted use; otherwise record a blocked/uncertified outcome rather than bypassing the gate.

## Notes

- Task IDs are sequential. Every actionable task includes a checkbox, ID, required story label where applicable, and exact file path.
- `[P]` appears only for independent tasks editing different files with no dependency on unfinished work.
- No task installs unreviewed sources, authenticates Copilot, commits changes, transmits feature/repository content without per-run authorization, or starts a native workflow before T026 and both owner gates.
