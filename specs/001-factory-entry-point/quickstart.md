# Quickstart: Validate the Factory Entry Point

This guide is for implementation and acceptance validation. Run end-to-end scenarios only in a disposable Spec Kit repository and only after the owner has approved the specification and plan.

## Prerequisites

- Windows with Python 3.11+, `uv`, Git, Specify CLI 1.0.6 (`speckit` itself requires `>=0.15.1`), the reviewed `speckit` workflow 1.0.2, and the tested Copilot CLI version.
- A disposable Git repository initialized with Spec Kit and the Copilot integration.
- Copilot already authenticated by the owner through the approved credential store. The factory does not run login or handle raw tokens.
- Explicit per-run authorization for hosted inference after reviewing the provider, data categories, and possible quota/credit use.
- A Windows sandbox and reviewed Copilot tool permissions that have passed the disposable policy probe for the exact CLI/runtime/policy fingerprint. The factory hook is supplemental, not the enforcement boundary. Do not use allow-all/`--yolo` mode.
- A local `.factory/policy.json` planning policy, `.factory/implementation-policy.json` plan-digest-bound policy, and separate `.factory/security-probe-planning.json` / `.factory/security-probe-implementation.json` evidence records. These files are local-only and ignored by Git.
- `FACTORY_HOSTED_PROVIDER` set to the configured inference provider identity. `FACTORY_POLICY_CONFIG` may point to the planning policy file; the implementation policy remains at `.factory/implementation-policy.json`.

## Local Checks

From the factory repository root:

```powershell
uv lock
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run factory doctor
```

Expected: `uv lock` creates/updates `uv.lock`; unit tests pass; `factory doctor` reports the active integration, workflow resolution, and static policy configuration. It must not claim authentication, live dispatch, hook enforcement, or effective sandbox enforcement was verified.

## Recorded Local Validation

Results from the current Windows checkout:

| Command                                          | Exit | Result                                                                                                                                             |
| ------------------------------------------------ | ---: | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `uv lock --check`                                |    0 | Lockfile is consistent.                                                                                                                            |
| `uv sync --locked`                               |    0 | Reviewed build environment is synchronized.                                                                                                        |
| `uv run python -m unittest discover -s tests -v` |    0 | 44 tests passed; 2 native acceptance tests skipped by default.                                                                                     |
| `uv run factory doctor`                          |    1 | Correctly blocked because `.factory/policy.json` is not configured; authentication, dispatch, and effective sandbox enforcement remain unverified. |
| `uv build`                                       |    0 | Source distribution and wheel built successfully.                                                                                                  |

This is package/unit validation only. The disposable sandbox probe, native workflow acceptance, and certification of the Specify/workflow/Copilot tuple were not run.

The CLI uses the native run directory at `.specify/workflows/runs/<run-id>/` to persist one `hosted-authorization.json` record and `delivery-report.md`. Report refresh compares a pre-run Git status/content snapshot with the current checkout; local run state and policy evidence stay under ignored directories.

## Hosted-Use Consent Checks

- Interactive run: show the configured inference provider, categories of feature-request/repository/tool-output content that may be sent, and possible quota/credit use before asking for explicit yes/no authorization.
- Declined or indeterminate provider: verify zero Copilot invocations, zero Spec Kit workflow runs, and no fabricated run ID.
- Non-interactive run without `--authorize-hosted-agent`: verify it blocks before transmission/dispatch. With the flag, verify the documented disclosure is displayed and consent applies only to that invocation.

## Security Policy Acceptance

Perform these checks in a disposable repository after explicit consent for the hosted test request; do not use the user's working repository. This probe does not run the native Spec Kit workflow. Its successful result is required before any native workflow dispatch for the same CLI/runtime/policy fingerprint; a version or policy change invalidates that result.

1. Verify the pre-approval `planning` policy has a null plan digest, allows writes only to designated Spec Kit planning artifacts, and denies application-source writes. After approving the disposable test plan, verify transition to `implementation` requires that plan's exact digest and grants only its canonical writable/read-only/denied paths, pinned tool identifiers, and exact local-check commands. Reject policy drift or malformed inputs.
2. Inventory hook discovery sources: machine policy files/registry, the dedicated factory user profile, repository `.github/hooks`, repository and local `.github/copilot/settings*.json`, `.claude/settings*.json`, and plugin configuration. Permit exactly the reviewed `.github/hooks/factory-policy.json` repository hook invoking `scripts/factory_pre_tool_use.ps1`; policy hooks cannot be disabled, and broad `disableAllHooks` disables the factory hook too. Load no plugins and stop if any source cannot be inspected or approved.
3. Start a standalone Copilot CLI session with explicit `--sandbox`; inspect `/sandbox` and `/sandbox policy`. A recognized flag alone is not evidence of enforcement. Verify a harmless out-of-scope write is denied with the factory hook active and produces no diff.
4. Repeat the harmless denial with the hook absent or a disposable test hook deliberately timed out. The official CLI contract says command-hook timeouts fail open to normal permission handling; this test proves the sandbox/tool policy still denies the write independently. Verify non-allowlisted tools/commands are denied and approved local checks remain usable.
5. Confirm no unreviewed MCP/plugin/hook is active and child-process outbound networking is restricted by the sandbox. Do not equate URL denials with a network firewall. If any control is unsupported, missing, or unobservable, stop without native workflow dispatch and record the tuple as uncertified.

### T026 Readiness (Offline Inspection Only)

No Copilot session or native workflow was started. This offline follow-up updates the earlier stopped-at-inspection record; T026 remains incomplete and the tuple remains uncertified.

**Hook and integration inventory**:

- Official Copilot CLI discovery combines policy hooks, user hooks/settings, repository hooks/settings, and plugin hooks. Agent-scoped hooks in custom-agent definitions are an additional repository/user source. Policy hooks load first and cannot be disabled with `disableAllHooks`.
- The user hook at `%USERPROFILE%\.copilot\hooks\discord-notifications.json` is an `agentStop` command hook invoking `discord-notify.ps1`. Static review shows that script reads the Copilot transcript's latest assistant response and posts it to Discord when the user-scoped `COPILOT_DISCORD_WEBHOOK` value exists. The script was not run; the environment variable's value was not read or copied.
- The repository has exactly one hook file, `.github/hooks/factory-policy.json`, a `preToolUse` command hook invoking `scripts/factory_pre_tool_use.ps1`. No repository `.claude` settings, inline Copilot settings, custom-agent hook files, or repository MCP configuration were found. The repository hook and its script were inspected statically only.
- No user `settings.json` or `mcp-config.json` exists in the current Copilot home; the installed-plugin directory is empty. `copilot plugin list` reported no installed plugins and reported bundled `computer-use` and `browser-use` as disabled. `copilot mcp list` reported built-in `computer-use` (local) and `github-mcp-server` (HTTP). `copilot instruction list` found no instruction sources.
- The documented machine policy hook locations, `%ProgramData%\GitHub\Copilot\policy.d` and `HKLM\SOFTWARE\Policies\GitHub\Copilot`, were absent in non-elevated checks. No machine policy hook was observed. This does not reveal server-managed or MDM sandbox settings.
- `COPILOT_HOME` is a supported override. A new empty temporary home excludes the current user hooks/settings/MCP configuration, credentials stored in that home, and installed plugins without changing the existing profile. It does not suppress machine policy hooks or repository hooks. Preserve the factory hook by placing only its reviewed hook JSON and script in the disposable repository. `COPILOT_PLUGIN_DIR_ONLY=true` with no `--plugin-dir`, `--disable-builtin-mcps`, and an explicit `--disable-mcp-server` for every server reported by `copilot mcp list` provide additional plugin/MCP controls. Verify the list in the isolated profile before any probe. Do not copy tokens or existing Copilot configuration; an empty profile will need its own separately authorized authentication.

**Windows and update status**:

- `Win32_OperatingSystem` reports Microsoft Windows 11 Home, version `10.0.26200`, build `26200`, x64. The registry reports display version `25H2`, build `26200`, UBR `9974`; its `ProductName` string and an earlier `Get-ComputerInfo` result said Windows 10, which conflicts with the CIM caption and current build. Treat the CIM caption plus display version/build as the observed OS identity, and retain the stale product-name discrepancy as a limitation.
- `Get-HotFix` reports KB5132061 installed; Microsoft's November 10, 2026 update record maps that update to build `26200.9974` for Windows 11 25H2. The installed UBR matches that current security build as of November 19, 2026.
- Copilot CLI 1.0.114 documents Windows sandboxing through MXC ProcessContainer with BaseContainer. The MXC project lists Windows 11 x64/ARM64 for ProcessContainer, so the OS/version/architecture baseline matches. The documentation does not identify `Containers-DisposableClientVM` as a BaseContainer prerequisite. The non-elevated `Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM` query failed because DISM requires elevation to query that online optional-feature state on this host; no feature was changed and no elevation was requested. This query does not establish that the feature is needed by Copilot.
- `hns` and `vmcompute` were running, but that is not proof that Copilot's BaseContainer backend works. Effective sandbox status/policy and server/MDM managed settings remain runtime questions; `/sandbox status` and `/sandbox policy` have not been run because they require a Copilot session.

**Readiness and remaining limitations**:

- User, repository, plugin, and built-in MCP isolation is technically achievable with a fresh `COPILOT_HOME`, a disposable repository containing only the factory hook, plugin discovery disabled, and built-in plus enumerated MCPs disabled. No existing user configuration needs to be changed. Do not set `disableAllHooks` because it would also suppress the factory hook.
- The installed Windows version and current security build meet the documented Windows 11 x64 baseline. No OS upgrade or feature enablement is indicated by the published BaseContainer requirements. Actual backend support and effective policy still must be confirmed in the authorized probe; if `/sandbox status` is off or `/sandbox policy` is unavailable/inadequate, stop without weakening policy.
- `factory doctor` previously reported that this checkout has no `.factory/policy.json`. The reviewed hook therefore cannot be exercised with a configured factory policy yet. The future disposable repository needs a test-only policy approved for the probe, limited to its fixture paths and exact test commands. If such a policy cannot be derived without relaxing the approved boundary, stop instead of inventing or weakening it.
- No implementation or existing user configuration change is required for preparation. The required setup is disposable test data, an approved test-only policy, and a new empty Copilot home at probe time. Keep all normal restrictions in force or make them stricter; do not use allow-all/`--yolo`, bypass, or learning/allow mode.
- Server-managed or MDM settings cannot be fully determined from this offline inspection. The effective `/sandbox policy` view during the future session is required. Authentication in the empty profile and hosted inference consent are not granted by this readiness instruction.

**Proposed T026 procedure after separate authorization**:

1. Create a new temporary Copilot home and a new Git repository outside this development checkout. Do not copy user settings, installed plugins, MCP configuration, tokens, or other credentials. Use only an owner-approved test-only policy/fixture and copies of `.github/hooks/factory-policy.json` and `scripts/factory_pre_tool_use.ps1`; include no other hooks, agent definitions, settings, instructions, or MCP files. Set `COPILOT_PLUGIN_DIR_ONLY=true` and launch with explicit `--sandbox`, `--disable-builtin-mcps`, `--disable-mcp-server` for each enumerated server, and the pinned `--available-tools`/`--deny-tool` restrictions. Construct the process environment from an explicit safe allowlist; never inherit or print secret values.
2. Authenticate only into the temporary profile after the owner separately approves it. Before any tool test, inspect `/sandbox status` and `/sandbox policy`; require sandbox enabled, bypass forbidden, exact temporary-repository writes, explicit tool read access, a deny rule for the out-of-repository sentinel path, and child-process outbound networking disabled. Stop if any hook/MCP/plugin or managed-policy source is unreviewed, or if policy is unavailable or broader than approved.
3. With the reviewed factory hook active, request one harmless write to the out-of-repository sentinel. Confirm the hook denies it, no sentinel exists, and the disposable repository has no diff. Do not use the development checkout.
4. Repeat with the repository hook absent, then with a disposable test hook deliberately exceeding its timeout. Copilot command-hook timeouts are documented fail-open, so in both cases confirm the ordinary tool policy and OS sandbox still deny the same harmless write. Keep every other restriction identical; verify no sentinel and no diff after each case. Also verify a disallowed tool/command is refused and approved local checks run successfully without installing dependencies or network access.
5. Record exact CLI/runtime/policy fingerprint, sanitized hook/MCP/plugin inventory, `/sandbox` output, commands, results, and limitations. Stop; do not run Spec Kit or any native workflow. T026 passes only if all required denials and allowed local checks are observed; otherwise leave it open and report the blocker.

The future probe requires a new explicit hosted-use consent and authentication in the temporary profile. The documented feature-state query requires elevation on this host, but no elevation is currently indicated or authorized; if backend verification later identifies a Windows prerequisite requiring an OS change, stop and obtain separate owner/admin authorization rather than changing it. Sources: [Copilot hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference), [local sandbox policy](https://docs.github.com/en/copilot/concepts/security-governance-and-network-settings/understanding-local-sandboxing), [enterprise-managed settings](https://docs.github.com/en/copilot/reference/enterprise-administrators/enterprise-managed-settings), [MXC](https://github.com/microsoft/mxc), and [KB5132061](https://support.microsoft.com/en-us/servicing/os/windows-11/2026/11/kb5132061-windows-11-24h2-25h2-26h2-security-update).

## Native Workflow Acceptance

In the disposable repository, first confirm the native process is installed:

```powershell
specify integration status --json
specify workflow info speckit
specify workflow resolve speckit
```

Expected: workflow version 1.0.2 with both `speckit_review_spec_verdict` and `speckit_review_plan_verdict` inputs; resolution attributes `review-spec` and `review-plan` to the enabled `speckit-approval-retry` project overlay. This verifies configuration only and does not authorize or start a workflow.

Set the safe Copilot dispatch mode for the test session and submit a small, authorized feature request:

```powershell
factory run --type feature "Add a small example feature"
```

Before a live run, the factory must disclose hosted use and obtain per-run consent, then construct the sanitized child environment and fixed Copilot policy described in [cli.md](contracts/cli.md). The user must not need to set an environment variable to disable `--yolo` manually. Expected: one native `speckit` run is created only after static preflight, consent, and security policy checks pass. The request reaches `review-spec`; the run ID and current gate are visible. No implementation starts before explicit approval. Approve at the prompt, then verify the same behavior at `review-plan`.

To test non-interactive pause and later same-run resume, start without a TTY, capture the returned native run ID, inspect it, and explicitly resume the matching gate:

```powershell
factory status <run-id>
factory resume <run-id> --gate spec --decision reject
factory status <run-id>
factory resume <run-id> --gate spec --decision approve
```

Expected: rejection keeps the run paused at `review-spec`; later approval resumes that same run ID and does not repeat completed steps. Repeat for the plan gate. Never send an approval on the initial run.

## Failure and Report Acceptance

- Hide or misconfigure the required CLI in a test fixture: `factory doctor` and `factory run` must fail clearly before workflow dispatch.
- Use a fake dispatcher for unit tests to test missing executables, nonzero exits, malformed status, wrong gate/run IDs, and missing checks without contacting Copilot.
- Cause a required check to fail in the disposable repository: the report must show its actual nonzero exit and must not say `verified`.
- Compare the report with native `workflow status --json`, the run logs, owner decisions, Git state before/after, and check output. Required checks are the union of approved-plan checks, checked-in CI configuration, repository contributor/instruction documentation, and branch-protection checks supplied by the owner. The plan cannot waive a repository check; unresolved conflicts or unavailable remote-only branch-protection requirements block a verified outcome. Confirm the report distinguishes pre-existing files and records only roles/skills actually invoked.
- Compare the final requirements/scope review with the approved plan and actual diff; verify actionable findings and independent/self-review labeling.
- Verify no Git push, merge, publish, deployment, secret disclosure, or unapproved approval-rule change occurs.
- Verify the provenance inventory records origin, pinned version/reference, license, modifications, purpose, and review status for each adopted/executed external component.

## Implementation Self-Review

Review type: self-review by the implementing agent; no independent reviewer was available.

Open acceptance findings:

- **Blocker**: T026 stopped before a Copilot session because effective sandbox policy and Windows BaseContainer support could not be established without interactive inspection/elevation. Out-of-scope denial with the hook absent or timed out remains untested. No native workflow may be dispatched until this exact runtime/policy probe passes.
- **Blocker**: T028 native feature delivery and both owner approval gates were not exercised. The Specify/workflow/Copilot tuple remains uncertified.
- **Blocker**: `factory doctor` exits 1 in this checkout because `.factory/policy.json` and phase-specific probe evidence have not been configured.
- **Limitation**: Final Git changes cannot establish which policy phase produced each write without runtime event evidence; refreshed reports state this and cannot claim verified status.

No live compatibility or delivery claim is made. Local unit/build validation does not resolve these acceptance findings.

No live Copilot workflow, hook-policy acceptance, or Windows sandbox containment test was executed. `factory doctor` cannot prove authentication, dispatch, hook enforcement, or effective sandbox behavior. Passing local checks alone is not release acceptance; resolve the T026 environment blockers, complete the disposable policy probe and workflow acceptance, and satisfy all applicable success criteria before claiming V1 compatibility.
