# Research: Per-Agent Model Preferences

**Date**: 2026-11-21 | **Status**: Option B approved and mechanism verified (see the first section). Earlier sections are historical.

## Workflow evidence under the Option B build (same session, `events.jsonl`)

Local config: `budget=claude-haiku-4.5`, `balanced=claude-sonnet-5.5`, `quality` unset (all three set by the verifier for this session, not bundled; only these two IDs have been observed accepted). Parent model `claude-sonnet-5.5` for implementation delegations.

| Delegation | Requested | Actual (started and completed) | Source | Tokens | Duration |
| --- | --- | --- | --- | --- | --- |
| Engineer, implement (preset Budget, hand-passed before the script existed) | `claude-sonnet-5.5` | `claude-sonnet-5.5` | `task_argument` / `explicit_override` | 485,068 | 132.7 s |
| QA Engineer, tests (Budget → `budget` tier) | `claude-haiku-4.5` | `claude-haiku-4.5` | same | 1,733,506 | 507.9 s |
| Code Reviewer (Budget → `balanced`) | `claude-sonnet-5.5` | `claude-sonnet-5.5` | same | 297,335 | 97.1 s |
| Engineer, fixes (`resolve`) | `claude-sonnet-5.5` | `claude-sonnet-5.5` | same | 165,491 | 39.6 s |
| QA Engineer, test fixes (`resolve`, Budget) | `claude-haiku-4.5` | `claude-haiku-4.5` | same | 1,833,952 | 572.2 s |
| QA Engineer, tiny read-only check after `set-preset balanced` | `claude-sonnet-5.5` | `claude-sonnet-5.5` | same | 26,286 | 4.0 s |

The last row is the same role that ran on `claude-haiku-4.5` under Budget, now `claude-sonnet-5.5` after a preset change, so the preset changes the real task call.

**Efficiency observation (one sample, not a benchmark)**: the Budget-tier QA delegation used about 3.6× the tokens and 3.8× the wall time of the Balanced-tier Engineer delegation, and had to be sent back for a second round after review (stray helper scripts left in the repository root, an unverified "pre-existing failures" claim, and weak tests). The cheaper tier was not demonstrably cheaper overall for this task; tasks differ, so the comparison is indicative only. No prices are claimed.

**Review**: the Code Reviewer ran as a separate delegation (own `subagent.started`/`completed`) and the runtime reported its tools as exactly `read`, `grep`, `glob`. It had no git access and reviewed current files, and it labelled itself a self-review because it could not itself verify the context or restriction. Independence is therefore reported as separate delegated context with runtime-reported read-only tools, but not as an independently verified permission enforcement; VS Code documents that `strict-tools-list` is not forwarded.

**Final review (second Code Reviewer delegation)**: `claude-sonnet-5.5` requested and actual, `task_argument` / `explicit_override`, 195,559 tokens, 57.6 s; `subagent.selected` tools `read, grep, glob`. It reviewed the final patch as a diff. Remaining minor items it listed (not fixed, no further cycle): argparse and invalid-config both exit 2; `report` labels some missing-event cases "none (inherited)"; tests call `read_text()` without an encoding in a few places; the test file begins with a UTF-8 BOM (harmless); duplicate-`toolCallId` assertion is weak.

**Observation**: the final completed event can lag the returned task by a few seconds.

## Option B verification, 2026-11-21 (current)

One read-only Engineer delegation, owner-authorized. Parent model `claude-sonnet-5.5` (`session.model_change` to it at 03:40:25Z, immediately before the call); agent Engineer; native task argument `model: claude-haiku-4.5`; no retries; no repository changes.

| Item | Recorded value (session `events.jsonl`) |
| --- | --- |
| Requested model | `claude-haiku-4.5` |
| `taskModelSource` | `task_argument` |
| `modelSelectionSource` | `explicit_override` |
| Actual model, `subagent.started` | `claude-haiku-4.5` |
| Actual model, `subagent.configured` | `claude-haiku-4.5` |
| Actual model, `subagent.completed` | `claude-haiku-4.5` (`firstDispatchedModel` and `explicitModelOverride` also `claude-haiku-4.5`) |
| Tokens / duration / tool calls | 21,705 / 5,685 ms / 1 |
| Completed | Yes; the response was not used to infer model identity |

Contrast: the earlier probe with no task argument (and Engineer frontmatter `model: claude-haiku-4.5`) recorded `taskModelSource: unset`, `modelSelectionSource: session_inheritance`, actual `claude-sonnet-5.5` (29,052 tokens, 5,164 ms). Conclusion: the per-delegation task argument is a working, observable application mechanism; repository frontmatter was not effective in that session.

## P0 verification of frontmatter application, earlier 2026-11-21 (historical)

The owner reprioritised Feature 005 as P0 and authorized one bounded delegated verification with a named parent model.

**Observability finding (positive)**: the Copilot SDK session in VS Code writes a local `events.jsonl` under `~/.copilot/session-state/<session-id>/`. It already contains `session.start.selectedModel`, `assistant.message.model`, `subagent.started`, `subagent.configured` and `subagent.completed`, each with the subagent `model`, plus `taskModelSource`, `modelSelectionSource` and, on completion, `totalTokens` and `durationMs`. No `assistant.usage` events were present in that file, so cost and latency detail beyond tokens and duration are NOT AVAILABLE there. No new host, service or logging was added. Requested model and verified execution can therefore be distinguished from existing local diagnostics.

**Probe**: parent model `claude-sonnet-5.5` (named, not Auto). `engineer.agent.md` was temporarily given `model: claude-haiku-4.5` and `model-policy: preferred`, then one read-only Engineer task was delegated with no task-level model override. Recorded result: `subagent.started` and `subagent.completed` both reported `model: claude-sonnet-5.5`, `modelSelectionSource: session_inheritance`, `taskModelSource: unset`; the delegated task ran 5.2 s using 29,052 tokens. The preferred model was **not applied**. The temporary edit was reverted; `git status` showed only the untracked `specs/005-agent-model-preferences/` afterwards.

**Limitation of this result**: the profile was edited after the session started, so a start-of-session profile cache is not excluded as the cause, and the model ID format was not separately varied. Only one probe was authorized, so a fresh-session repeat has not been run. Classification: repository-frontmatter application in the current session is **FAILED/NOT EFFECTIVE (this session)**; fresh-session behavior and user-level `subagents.agents` overrides are **NOT VERIFIED**.

**Smallest supported alternative**: a per-delegation `model` argument on the native `task` call (the runtime records it as `taskModelSource`), set by Factory Lead from the selected preset. It is native and observable, but requires the owner's explicit approval because current runtime instructions allow Factory Lead to set it only when the owner names the model.

## Final investigation decision, 2026-11-21 (earlier record)

1. **Rejected**: the helper that generates global personal copies of the specialist profiles is not to be built.
2. **Not complete**: Feature 005 is not complete, and a documentation-only guide must not be presented as satisfying the original requirements.
3. **Preferred, unproven in Chat**: native per-subagent model configuration for Architect, Engineer, QA Engineer and Code Reviewer. Factory Lead's model remains the user's Chat selection.
4. **Preserved requirements**: user-defined Budget, Balanced and Quality-first mappings, per-agent overrides, no required model locking, preserved specialist instructions and tool declarations, and reporting of the actual model where observable.
5. **No further live model experiments** at this stage. No workaround that merely appears to apply preferences is to be implemented.

### CLI-documented precedence (documentation only, not verified here)

From the [CLI command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference) (custom agent fields and precedence): model and effort resolve, highest first, from an explicit per-call value, the `subagents` override in `~/.copilot/settings.json`, the agent definition's `model`/`models`/`reasoningEffort`, then the parent session's value. A declared model that cannot be honored falls back to the session's value unless the agent declares `modelPolicy: "required"`. The [CLI configuration reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference#configuration-file-settings) documents `subagents.agents`, keyed by agent name, with optional `model`, `modelPolicy`, `effortLevel` and `contextTier`, and the `/subagents` picker for interactive configuration.

### Auto-session caveat

The same CLI reference states, for the agent `model` field, that when the session model is set to `Auto` (server-selected), subagents always inherit the resolved session model regardless of that field. It does not, in the passages reviewed, say whether the `subagents.agents` override is likewise ignored under Auto; that is unresolved. All earlier UI observations in this investigation were made with the Chat model picker on Auto, so they cannot show that per-agent model preferences are unsupported. They also cannot show that they are supported.

### VS Code Chat status: NOT VERIFIED

- Whether the Copilot harness in VS Code Chat consumes `subagents.agents` or any equivalent user-level setting.
- Model precedence among explicit task overrides, user settings, agent preferences and the parent session for native `task` subagents in Chat, including the effect of a non-Auto parent selection.
- Fallback behavior for an unavailable preferred model.
- The actual model of any delegated subagent: the native `task` response and visible interface exposed no trustworthy model metadata.
- Effective reviewer read-only permissions: VS Code documents that `strict-tools-list` is not forwarded in SDK agent conversion.

### Live subagent probe, owner-authorized single delegation

The owner authorized one synchronous native `task` invocation of the existing `Feature 005 Precedence Probe` with no model override, no file or settings changes, and no retry. It succeeded and returned the requested text `PROBE COMPLETE`. The response exposed no distinct task ID, delegated-context details or model metadata. Dispatch is therefore evidenced; the requested model resolved for the subagent, the actual model, and which same-ID definition was loaded are **NOT VERIFIED**. The agent's text is not model evidence, and the probe was not asked to state its model. The invocation was in the Copilot SDK session in VS Code, not an inspected Chat UI task view. No further probing is authorized.

### Disposable artifact cleanup

- The repository probe was removed earlier after its SHA-256 matched the recorded original value.
- The personal probe matched the last recorded SHA-256 `6A8EEC3D714516A0D13C07325553548EE8D10ACA6CB9A0D71A9C010A49115BB3`, was an ordinary file (not a link), and its content exactly matched the owner-edited form recorded below (only `model: GPT-6.1 Sol (copilot)` differing from the last assistant-created version). On the owner's instruction it was removed after re-verifying that hash. The `~/.copilot/agents` directory did not exist before this test, contained only that file, and was removed once empty. `~/.copilot` itself, all production agents, source code, settings and Git state were left unchanged. Neither probe exists now.

## Corrected scope and native subagent research (earlier record)

The owner corrected the requirement: only delegated Architect, Engineer, QA Engineer and Code Reviewer need model preferences; Factory Lead's model is selected in Chat. The earlier Chat smoke test selected the probe as the main agent, so it does not establish how native `task` subagents resolve models.

- **Existing probe, static evidence (at the time; since superseded by the probe result above)**: The native `functions.task` agent-type schema included `Feature 005 Precedence Probe`. The personal probe had `model: GPT-6.1 Sol (copilot)` and `tools: []`; the repository probe had been removed. Both are now removed.
- **Documented CLI settings**: [GitHub's CLI configuration reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference#configuration-file-settings) describes `subagents.agents`, keyed by agent name, with optional `model`, `modelPolicy`, `effortLevel`, and `contextTier`. `/subagents` offers interactive configuration. The preferred policy allows user choice; no required model locking is proposed.
- **Documented SDK/CLI precedence**: The [CLI command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference) describes per-call value, user `subagents` override, agent definition, then parent session, with unsupported preferences falling back to session values unless required. Its SDK custom-agent `model` field description also states that an Auto session's resolved model is inherited regardless of that field. Those descriptions concern their documented contexts; do not assume the same behavior in this Chat session or ignore the Auto caveat.
- **VS Code documentation**: The [VS Code subagent guide](https://code.visualstudio.com/docs/agents/run/subagents) describes custom agents with optional model preferences and native `task` in the Copilot harness. The [agent-file reference](https://code.visualstudio.com/docs/agents/reference/custom-agent-file-reference) documents the `model` field and says `strict-tools-list` is not forwarded when agent files are converted to SDK custom-agent configuration. The documentation reviewed here does not establish that VS Code Chat consumes the CLI's `subagents.agents` settings or exposes actual model identity in task details.
- **Runtime evidence**: Previous Architect tasks demonstrate task dispatch in this session, not their actual model or preference resolution. Current task schema provides an optional model argument and advertises the probe; neither proves it ran. The available task response schema does not promise actual model metadata. Effective reviewer tool enforcement is not established by static profile fields.

The earlier smoke test did not authorize a subagent delegation; the later single owner-authorized delegation is recorded above. The current status and requirements are in [plan.md](plan.md).

## Historical proposal: Native personal agent definitions with guarded generation (blocked)

- **Decision**: The proposed helper generates complete same-ID personal profiles with the native `model` field, after explicit user action and safety checks. It is not a model router.
- **Rationale**: [GitHub's CLI agent guide](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-custom-agents-for-cli) documents repository and `~/.copilot/agents/` personal profiles and says a personal agent with the same ID wins. The ID is the filename without the suffix, not the `name` field. [VS Code's custom-agent reference](https://code.visualstudio.com/docs/agents/reference/custom-agent-file-reference) lists the Copilot user directory and native model field. The latter does not establish same-ID precedence for VS Code in this research; verify separately.
- **Alternatives**: Recording a standalone preference without applying it fails FR-017. A personal model-only profile can replace the role, losing its instructions and restrictions. Editing shared profiles for each user violates the local-override requirement. A gateway or custom dispatcher is out of scope.
- **Risk**: Global personal profiles can shadow agents in other repositories; source drift persists until explicitly detected and reconciled. The helper cannot enforce a runtime preflight. Existing personal definitions must never be overwritten without a safe ownership check.

## Decision: Single model string, optional preference

- **Decision**: Use one user-supplied model ID per resolved role and no required lock. Presets select user-configured tiers; no identifiers or prices are shipped as fact.
- **Rationale**: The [GitHub configuration reference](https://docs.github.com/en/copilot/reference/custom-agents-configuration) documents `model` as a string and an inherited default when absent. [VS Code's reference](https://code.visualstudio.com/docs/agents/reference/custom-agent-file-reference#_model-preferences) describes a string or ordered list, selecting the first available value, and `model-policy: preferred` by default. It describes user model changes remaining selected for the conversation. A single string is the conservative common documented form.
- **Alternatives**: Model arrays have uneven documentation across surfaces. Required locking conflicts with owner requirements. Guessing IDs or ranking capabilities across entitlements would create unsupported claims.
- **Unknown**: Current Copilot harness precedence when the parent explicitly chooses a model and a delegated profile has its own preference, fallback for unavailable models, and the actual model used. Do not apply [VS Code Local harness](https://code.visualstudio.com/docs/agents/run/subagents) precedence rules to the Copilot harness.

## Decision: Preserve and validate complete profiles

- **Decision**: Treat the current repository profile as source; compare all parsed metadata except `model`, compare the complete instruction body exactly, and retain the reviewer validator's strict `read`, `grep`, `glob` rule. Refuse unmanaged targets and source/target drift.
- **Rationale**: Personal precedence can replace rather than merge profiles. The existing validator checks name, description and reviewer declarations but does not check effective runtime permissions, personal profiles or source equivalence. Static validation and runtime enforcement are distinct.
- **Alternatives**: A partial profile risks losing role instructions. Blind regeneration destroys user edits. Treating a declared strict tool list as proof of enforcement would misrepresent evidence.
- **VS Code limitation**: The [VS Code custom agent reference](https://code.visualstudio.com/docs/agents/reference/custom-agent-file-reference) says `strict-tools-list` is not forwarded when VS Code converts agent files to SDK custom-agent configuration. Static preservation is necessary but does not establish effective read-only enforcement.

## Decision: Evidence tiers and authorization

- **Decision**: Separate static fixtures, official documentation, actual native task delegation, effective-model identity, separate execution, and effective reviewer permissions. Treat unobserved evidence as NOT VERIFIED. Obtain separately authorized run-specific permission for hosted/live delegation tests.
- **Rationale**: The [VS Code subagent guide](https://code.visualstudio.com/docs/agents/run/subagents) distinguishes harness behavior, identifies the Copilot native task mechanism, and cautions that instructions alone do not enforce a read-only boundary.
- **Alternatives**: Using CLI success as proof of Chat compatibility, or inferring effective model and tools from a profile, would not meet the approved requirements.

## Architect handoff

Native `functions.task` launched Architect `profile-preservation`, task ID `b222c186-1877-4c35-88fe-e328ec235841`, for bounded read-only planning research. Runtime returned a completed one-turn handoff. The Architect recommended complete source-profile copying with only model changes, preservation of unknown metadata and body, drift/ownership protection, and tests for all five profiles. It inspected the feature draft, five profiles, validator and its tests; it performed no commands, tests, network access, hosted sessions or edits. The agent described its work as a same-session role pass; the task tool and returned task ID establish a delegated task in a separate agent context, but do not establish its actual model or effective permissions. No independent review is claimed.

## Git investigation

The previous staged path list matches the 20 paths in new HEAD `481aca7ba8e26a512461070294eae2498f731d4a`, created at 13:29:02 per reflog, and tracked index and worktree match HEAD. The previous staging snapshot contained paths but no blob hashes; exact identity of earlier staged bytes cannot be proved from available evidence. No Git state was changed in this investigation. See the [plan](plan.md#git-safeguard-and-baseline) for the full baseline and required pre-implementation refresh.

## Compatibility gate, 2026-11-21

Owner approved the plan with amendments and authorized a bounded Chat smoke test, requiring separate explicit confirmation before creating or modifying a personal agent file. On 2026-11-21 the owner explicitly authorized the following two disposable files with ID `feature-005-precedence-probe-7c8f49a2`. Checks found no `.md` or `.agent.md` conflict in either agent directory; the personal agents directory did not exist. The files were then created with exclusive create, without modifying production profiles:

| Scope | Path | Original SHA-256 |
| --- | --- | --- |
| Repository | `.github/agents/feature-005-precedence-probe-7c8f49a2.agent.md` | `F69CB15B056529500FBFA35B63EBF229F0F2F005F5DBAFEAED5CAAE1072A8B9D` |
| Personal | `~/.copilot/agents/feature-005-precedence-probe-7c8f49a2.agent.md` | `DABA7F28FBF19967CAC272CFBC7B18E416ABA14466C4FECC62981769B7ABC1FC` |

The owner reported that the probe appeared in the Chat picker and the Customizations editor listed its personal path under User. Initially, selecting it showed Auto rather than the original `gpt-5.3-codex` preference. The assistant then changed the preference to `gpt-6.1-sol`; its recorded SHA-256 was `D2DE4F0ADE45BB38CCCA9AB52C963E35810B70273A80E74C8598135F6A843905`.

The owner subsequently set the personal agent's preference using VS Code model completion to `GPT-6.1 Sol (copilot)`. The owner observed Chat remaining on Auto and a subsequent request routed to MAI Code 2 Flash. This is owner-reported execution-routing evidence, not an assistant-observed runtime trace. It demonstrates personal discovery but does not establish same-ID precedence or application of the requested preference; the observed request was not reported as running on the requested model. The automatic global personal-agent override design did not pass its compatibility gate and is **BLOCKED**. No further precedence experiments are authorized.

Cleanup: the repository probe matched its recorded original SHA-256 and was removed. The personal probe's SHA-256 was `6A8EEC3D714516A0D13C07325553548EE8D10ACA6CB9A0D71A9C010A49115BB3`, different from the last assistant-created version after the owner's model-completion edit; it was preserved at that time and removed later after the owner's instruction and re-verification (see the cleanup record at the top). No production agents were changed. Manually selecting a model in the native Chat picker is a per-conversation fallback only; it does not implement presets, apply per-agent preferences, or prove the effective execution model.

**Superseded conclusion**: this section's earlier statement that the personal-agent design was blocked because Chat "remained on Auto" is refined above: the Auto-session caveat means those observations were inconclusive about per-subagent preferences. The global personal-agent-copy approach remains rejected for its other risks (global shadowing, drift, unverified same-ID precedence in Chat).
