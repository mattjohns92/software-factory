# Command-Line Contract

The first delivery exposes one feature-intake entry point plus preflight and run-management commands. It does not expose a bug-fix route. Hosted inference consent is separate from native spec/plan approval.

## Commands

### `factory doctor`

Checks that Python can locate the supported Specify CLI and Copilot CLI, reads their versions, verifies `specify integration status --json`, confirms the installed `speckit` workflow resolves, and checks that required policy configuration is present. This is a static prerequisite check only: it does not authenticate, start a Copilot session/workflow, or prove live dispatch or Windows sandbox enforcement.

- Initial compatibility test tuple: Specify CLI 1.0.6, `speckit` workflow 1.0.2 from the immutable `github/spec-kit` v1.4.2 tag (minimum CLI requirement `>=0.15.1`), Copilot CLI 1.0.114, Windows/PowerShell. This is not a certified support claim until the disposable-repository acceptance test passes.
- Exit `0`: required executables/version tuple, active integration, workflow registration, and static policy configuration are present. State explicitly that authentication, live dispatch, hook enforcement, and effective sandbox enforcement remain unverified.
- Nonzero: one or more prerequisites are missing or invalid; print the failed check and corrective action.
- Authentication state and sandbox enforcement are not checked. No login, credential prompt, model request, or workflow run is started.

### `factory run --type feature [--authorize-hosted-agent] "<request>"`

Starts exactly one native `speckit` run only after static checks and run-specific hosted-inference consent. `--type` is required and only `feature` is supported in this slice. No approval input is accepted by this command.

- Before transmission, identify the configured provider, disclose that the feature request, relevant repository content, and selected tool output may be sent, and disclose possible subscription quota/credit use. Interactive mode requests an explicit yes/no confirmation. Non-interactive mode requires `--authorize-hosted-agent`; this flag represents explicit acceptance of the documented disclosure and does not persist to later runs.
- If provider identity cannot be determined or the owner refuses consent, return a blocked result before invoking Copilot or Spec Kit. Do not fabricate a native run ID or run report.
- Before dispatch, print the selected feature route and request scope.
- If classification is ambiguous or the request is a bug fix, ask one blocking question in an interactive terminal or return a blocked result without dispatch in non-interactive mode.
- Do not pass approval verdicts during initial run.
- Return the native run ID and current status/gate, plus the report path.
- A static preflight failure occurs before native workflow invocation; return the failed check and corrective action without inventing a run ID or per-run report. Authentication and dispatch can fail only when the native command is attempted; inspect and report the resulting native state and real run ID when available. If it is indeterminate whether state was created, say so and do not claim no run exists. Never simulate success.

### `factory status <run-id>`

Reads `specify workflow status <run-id> --json`, validates the returned identity, and presents the native status and current gate. It does not mutate the run.

### `factory resume <run-id> --gate <spec|plan> --decision <approve|reject>`

Requires an explicit owner decision. The adapter verifies that the native run is paused at the matching gate, then maps the decision to that gate's native verdict input and calls `specify workflow resume` for the same run ID. A rejection leaves the run paused at that gate; approval allows the native workflow to proceed. No new run is created.

## Execution Rules

- Invoke external commands with an argument array and `shell=False`; preserve the working directory and stream/record actual stdout, stderr, and exit status without exposing secrets.
- Run identifiers and gate names come from native Spec Kit status, not user-provided state files.
- The factory constructs an allowlisted child environment, sets `SPECKIT_COPILOT_ALLOW_ALL_TOOLS=0`, legacy `SPECKIT_ALLOW_ALL_TOOLS=0`, and `COPILOT_ALLOW_ALL=false`, and does not inherit arbitrary Spec Kit executable/extra-argument overrides or raw credential variables. It never uses `--allow-all` or `--yolo`.
- Use a version-1 phase-specific policy. Exact fields are `schema_version`, `phase` (`planning` or `implementation`), `approved_plan_digest`, canonical `repository_root`, `writable_paths`, `read_only_paths`, `denied_paths`, `allowed_tools`, and `allowed_commands` (each with exact command text and working directory). Planning mode requires a null digest and permits writes only to designated Spec Kit planning artifacts, never application implementation paths. After owner plan approval, implementation mode requires the matching non-null plan digest. Reject stale/malformed policies and relative, traversal, UNC/device, or link/reparse-escaping paths; denied paths take precedence. Tool names come from a fixed allowlist validated against the pinned CLI. Command matching is exact text plus canonical working directory, never wildcard or prefix matching.
- Pass fixed, reviewed Copilot arguments only: require `--sandbox`, disable built-in MCPs, enumerate and disable every other configured MCP, and expose only the required reviewed tools. Use no plugins. Inventory machine policy, user, repository file, inline settings, and plugin hook sources. The CLI has no supported “load only this hook” control: `disableAllHooks` disables the repository factory hook too, and administrator policy hooks cannot be disabled. Use a dedicated factory user configuration profile to isolate unrelated user-level configuration; retain exactly the reviewed repository hook identified below, reject other unreviewed repository/inline hook sources and plugins, and block if any hook/MCP/plugin source cannot be enumerated or reviewed. The factory `preToolUse` hook denies malformed and unlisted actions but is supplemental only because command-hook timeouts fail open to normal permission handling. The Windows OS sandbox and restrictive tool permissions must independently deny out-of-scope access, including when that hook is absent or times out. Restrict sandbox filesystem and child-process network access; URL permission checks are not treated as a firewall. Retain only approved credential-store access.
- The one permitted repository hook is the reviewed `.github/hooks/factory-policy.json`, which invokes `scripts/factory_pre_tool_use.ps1`. The dedicated `COPILOT_HOME` isolates user-level settings/hooks but does not suppress repository or administrator policy hooks. Inventory those sources separately and block if any unreviewed repository/inline/plugin hook or unknown policy hook is present.
- Deny Git push/merge, release/deploy, package installation from unreviewed sources, arbitrary URL/network tools, and unconfigured MCP tools. Hosted inference traffic is separately consented and does not grant network access to agent tools.
- Verify policy option support against the pinned CLI and demonstrate actual sandbox/tool denials in a disposable repository before implementation dispatch for each CLI/runtime/policy fingerprint. Include a safe case with the hook absent or timed out to prove independent enforcement. If any hook, MCP, plugin, scope, or Windows sandbox control cannot be established, do not dispatch; report a compatibility/security blocker.
- Required checks are the union of approved-plan checks, checks explicitly required by checked-in CI configuration or repository contributor/instruction documentation, and branch-protection checks supplied by the owner. The plan cannot waive a repository mandate; unresolved conflicts or unavailable remote-only branch-protection requirements block a verified outcome until the owner resolves the check set, and changing repository requirements requires separate authorization.
- Before completion, review observed changes against approved requirements and paths, record actionable findings, and label independent review or self-review.
- `verified` is returned only when required checks ran and passed. Paused, blocked, failed, and completed-with-limitations outcomes remain distinct.
