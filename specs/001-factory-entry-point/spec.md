# Feature Specification: Bootstrap a Native-Workflow-Powered Factory Entry Point

**Feature Branch**: `001-factory-entry-point`

**Created**: 2026-11-19

**Status**: Draft

**Input**: User description: "Refine the native-workflow-powered factory entry point so static preflight is distinct from live compatibility acceptance, hosted model traffic requires explicit authorization, and scope and review controls are verifiable."

## User Scenarios & Testing _(mandatory)_

### User Story 1 - Deliver a Feature From One Request (Priority: P1)

As a solo developer, I submit a feature request once, authorize any hosted agent use separately, and the factory carries it through the native feature workflow, pausing for my specification and plan decisions before doing authorized implementation work.

**Why this priority**: This is the first useful factory capability and proves that the factory extends the existing Spec Kit process rather than replacing it.

**Independent Test**: In a disposable repository, pass the separate security acceptance probe, authorize hosted use, submit one feature request, approve its specification and plan, and verify one native run delivers the requested change within scope, runs the applicable required checks, and produces a minimum report containing the actual run identity/status, request, authorization/approval decisions, changed paths, scope-review result, required-check outcomes, known issues, limitations, and next action. Also verify implementation remains blocked before each approval. Unit tests with fake executables validate consent and dispatch behavior but do not by themselves prove feature delivery. US3 adds third-party provenance and actionable requirements-review findings, including independent/self-review labeling.

**Acceptance Scenarios**:

1. **Given** static prerequisites are available and the owner has authorized hosted agent use, **When** the owner submits a feature request, **Then** the factory shows the feature route and proposed scope and starts exactly one native feature run without requiring the request to be re-entered.
2. **Given** the owner has not authorized hosted agent use, **When** a request would send content to an external agent service, **Then** no request or repository content is sent and no agent workflow is invoked.
3. **Given** the native process has produced a specification awaiting review, **When** the owner has not approved it, **Then** implementation does not begin.

---

### User Story 2 - Reject or Resume an Approval Gate (Priority: P2)

As a solo developer, I can reject or defer a decision, then resume the same run after I make a decision, without the factory treating silence as approval or needlessly repeating completed work.

**Why this priority**: Approval gates are the owner's control over consequential work; resume behavior keeps those controls usable across interruptions.

**Independent Test**: Start from saved native run states at each review gate. Exercise pending, rejected, and approved decisions; confirm that protected work remains blocked until approval and an approved decision resumes the same run without needlessly repeating completed progress.

**Acceptance Scenarios**:

1. **Given** a specification or plan is pending or rejected, **When** the run is continued or resumed, **Then** the next protected phase remains blocked and the decision needed from the owner is shown.
2. **Given** the owner later approves the pending artifact, **When** the run is resumed, **Then** the existing Spec Kit run continues and completed steps are not needlessly repeated.
3. **Given** the owner explicitly approves both artifacts, **When** the run resumes, **Then** authorized local work proceeds only within the approved scope and applicable required checks are run.

---

### User Story 3 - Receive an Evidence-Based Outcome (Priority: P3)

As a solo developer, I can tell what the factory did, what it verified, and what remains unresolved from one concise report tied to the actual run.

**Why this priority**: A truthful handoff is necessary to evaluate the result and decide what to do next.

**Independent Test**: Feed completed, blocked, and failed run evidence into report scenarios. Compare each report with actual approvals, scope review, changed files, required-check results, and any recorded third-party execution provenance.

**Acceptance Scenarios**:

1. **Given** a run completes or stops, **When** its report is produced, **Then** the report identifies the request, run, approvals, changed files, checks and their outcomes, known issues, and recommended next action.
2. **Given** a required execution integration or check is unavailable, **When** the run stops, **Then** the report identifies the limitation and does not claim that workflow execution or verification occurred.
3. **Given** local implementation work has occurred, **When** the outcome is reported, **Then** the factory records whether changes were reviewed against approved requirements and labels the review as independent or self-review.
4. **Given** a run depends on a third-party agent, skill, script, or dependency, **When** that component has not passed provenance and license review, **Then** the factory blocks its adoption or execution and identifies the missing review information.

### Edge Cases

- The request mixes feature work with bug fixing, or cannot be classified as feature work from its explicit type and description; the factory asks one blocking question instead of guessing.
- The request is a bug fix, which is outside this first feature-delivery slice; the factory does not silently process it as a feature.
- A static prerequisite is missing or invalid; the factory reports the failed check and does not invoke the workflow.
- Static checks pass but authentication, live dispatch, or effective sandbox enforcement fails or remains uncertain; the factory reports actual or indeterminate native state and does not claim compatibility.
- The owner declines hosted agent use; the factory sends no request or repository content to the service and does not invoke the agent workflow.
- A run is interrupted after an approval or local action; resumption uses existing run state and flags any uncertain side effect for owner review.
- Relevant tests or other expected checks are unavailable or fail; the report records the actual result and does not label the run verified.
- An action would exceed the approved scope, or an out-of-scope change is observed; the factory pauses further work and reports the discrepancy for owner review.
- A required third-party tool, skill, script, or dependency lacks reviewed provenance or license information; the factory blocks its adoption or execution.
- The requested work would push, deploy, publish, spend money, expose secrets, or change approval rules; the factory pauses for separate explicit authorization.

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: The factory MUST provide one documented local entry point for submitting a feature request and MUST allow the owner to identify the request as feature work explicitly.
- **FR-002**: Before consequential execution, the factory MUST show the selected feature route and proposed scope; it MUST ask one blocking question when the request is mixed or its description and explicit type do not establish feature work without inference.
- **FR-003**: The factory MUST use the native Spec Kit feature workflow and its run state as the source of truth; it MUST NOT simulate a workflow when the supported agent execution integration is unavailable.
- **FR-004**: Before invoking a workflow, the factory MUST check static prerequisites: required executables and versions, integration registration and integrity, workflow resolution, and configured execution-policy controls. If any static prerequisite fails, it MUST report the blocker and invoke no workflow. Static preflight MUST NOT claim to verify authentication, live dispatch, or effective sandbox enforcement; those capabilities are established only by an explicitly authorized disposable-repository acceptance run.
- **FR-005**: The factory MUST pause for explicit owner approval of the specification and implementation plan before entering their respective protected next phases. Pending or rejected approval MUST block progression; generated approval inputs or silence MUST NOT count as approval.
- **FR-006**: The owner MUST be able to resume a paused run by its existing Spec Kit run identity; completed steps MUST NOT be needlessly repeated, and uncertain side effects MUST be flagged before retry.
- **FR-007**: After required approvals, the factory MAY make local changes and run available checks only within the approved scope. It MUST pause before a proposed out-of-scope action; if an out-of-scope change is observed, it MUST stop further work and flag it for owner review. It MUST NOT push, merge, publish, deploy, spend money, expose secrets, or change approval rules without separate explicit authorization.
- **FR-008**: For each stopped or completed run, the factory MUST produce one concise report tied to the actual run, stating the request, route, hosted-agent authorization, approvals, changed files, scope-review result, roles or skills actually used, checks and results, review findings, known issues, and next action.
- **FR-009**: The factory MUST distinguish verified completion, completion with limitations, blocked work, and failed work. The required-check set MUST include checks identified by the approved plan, checks explicitly required in checked-in CI configuration or repository contributor/instruction documentation, and branch-protection checks explicitly supplied by the owner. The approved plan MUST NOT waive a repository-mandated check. If those sources conflict or a required check cannot be identified, the factory MUST block a verified outcome and ask the owner to resolve the conflict; changing a repository check requirement requires separate explicit authorization. If remote-only branch-protection requirements are not supplied and cannot be inspected through an already-authorized integration, the check set is incomplete and MUST NOT be reported verified. The factory MUST disclose skipped or unavailable required checks and MUST NOT claim verification without evidence that all required checks ran and passed.
- **FR-010**: This first delivery MUST handle feature requests only; bug-fixing workflow routing, automatic repair cycles, role and skill packaging, installation into another repository, and self-development proof are outside its scope.
- **FR-011**: Before any feature request or repository content is sent to an external agent or model service, the factory MUST disclose the service and the categories of content that may be sent and obtain the owner's explicit authorization. Authorization MUST be specific to the run; refusal MUST block transmission and workflow invocation.
- **FR-012**: Before adopting or executing a third-party agent, skill, script, or dependency, the factory MUST ensure its origin, pinned reference or version, license, modifications, and intended purpose have been reviewed and recorded. Unknown or incompatible licensing MUST block redistribution.
- **FR-013**: Before reporting implementation complete, the factory MUST review actual changes against the approved requirements and scope, record actionable findings, and identify whether the review was independent or self-review.

- **FR-014**: The factory MUST use phase-specific execution policies. Before plan approval, the planning policy MUST restrict writes to designated Spec Kit planning artifacts for the current feature and MUST prohibit application implementation changes. After plan approval, the implementation policy MUST bind to the approved-plan digest and define its writable paths, read-only paths, available tools, exact permitted local-check commands, and denied sensitive paths. Paths MUST be canonicalized and checked against traversal and link escapes; missing, malformed, or mismatched phase policy MUST block the corresponding workflow action.

### Key Entities _(include if feature involves data)_

- **Run**: One submitted feature request and its native Spec Kit process identity, status, artifacts, and completed steps.
- **Approval decision**: The owner's explicit approval, rejection, or pending state for a specification or plan, associated with the relevant run and artifact.
- **Hosted-agent authorization**: The per-run provider, content disclosure, owner decision, and time captured before any hosted inference.
- **Execution policy**: A versioned, phase-specific per-run policy. The planning policy has a null approved-plan digest and is restricted to designated Spec Kit planning artifacts; the implementation policy is bound to the approved-plan digest and defines canonical path, tool, command, and denied-path allowlists.
- **Third-party provenance record**: Reviewed origin, pinned reference/version, license, modifications, purpose, and review status for each adopted or executed external component.
- **Scope review**: Observed tool actions and file changes compared with the execution policy and approved requirements, including findings and reviewer type.
- **Delivery report**: A concise record of the run's request, route, decisions, changes, verification evidence, limitations, and outcome.

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: In the supported feature acceptance scenario, one submitted request creates one native workflow run and reaches the specification review gate without asking the owner to re-enter the request.
- **SC-002**: In all tested pending and rejected specification or plan decisions, 100% of protected next phases remain blocked; after approval, resumption continues the same run without needlessly repeating completed steps.
- **SC-003**: Every completed or stopped acceptance run produces exactly one report whose stated approvals, changed files, and check results match the run evidence, with zero unsupported claims of execution or verification.
- **SC-004**: In all tested static-prerequisite failure cases, preflight reports the specific blocker and starts zero workflow runs; when static checks pass, preflight makes no claim that authentication, live dispatch, or effective sandbox enforcement has been proven.
- **SC-005**: A reviewer can identify from the report whether the request was delivered, what was verified, what remains unresolved, and the next action without consulting an undocumented source.
- **SC-006**: In every tested run without explicit hosted-agent authorization, zero request or repository content is transmitted and zero agent workflow invocations occur.
- **SC-007**: In all tested out-of-scope action cases, no further out-of-scope action occurs after detection, and the run is paused or reported for owner review.
- **SC-008**: Every third-party component adopted or executed by the factory has a recorded origin, pinned reference or version, license, modifications, and intended purpose before use.
- **SC-009**: Every completed implementation report records a review against approved requirements and scope, actionable findings, and whether that review was independent or self-review.
- **SC-010**: In every tested required-check conflict, the factory runs the union of approved-plan and repository-mandated checks when compatible; otherwise it blocks a verified outcome and reports the conflict without silently waiving either source.
- **SC-011**: In every tested malformed, stale, mismatched, or out-of-scope policy-configuration case, zero native workflow dispatches occur. Separately, a runtime out-of-scope write attempt MUST be denied by the effective Windows sandbox even when the pre-tool hook is absent or times out.

## Assumptions

- The product owner is the only person who can approve the specification and plan for this initial local workflow.
- The repository has an installed Spec Kit CLI and native feature workflow; the supported Copilot CLI-capable execution mode remains to be verified and documented.
- Hosted agent/model use is not implied by permission to edit local files; the owner makes an explicit per-run decision after seeing the service and content disclosure.
- The first slice is run from an ordinary local checkout on Windows and does not require Git worktrees.
- The owner authorizes local implementation and safe local checks only after approving both the specification and plan; external or destructive actions require separate authorization.
- Exact entry-point naming and the presentation of run status are planning decisions, not fixed by this specification.
- A missing or failing relevant check results in a limited, blocked, or failed outcome rather than an unverified success.
- Applicable repository-mandated checks cannot be waived by the approved plan; conflicts require owner resolution, and changes to repository check requirements need separate explicit authorization.
