import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from software_factory.policy import (
    PolicyError,
    authorize_hosted_use,
    build_sanitized_environment,
    create_policy,
    evaluate_hook_event,
    validate_policy,
)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name, "repo").resolve()
        self.root.mkdir()
        self.feature_directory = self.root / "specs" / "001-example"
        self.plan_path = self.feature_directory / "plan.md"
        self.plan_path.parent.mkdir(parents=True)
        self.plan_path.touch()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_hosted_use_refusal_or_unknown_provider_fails_before_authorization(self):
        with self.assertRaises(PolicyError):
            authorize_hosted_use("copilot", ["request"], accepted=False)
        with self.assertRaises(PolicyError):
            authorize_hosted_use("", ["request"], accepted=True)

    def test_hosted_use_authorization_is_per_call_and_records_disclosure(self):
        authorization = authorize_hosted_use(
            "copilot", ["feature request", "repository context"], accepted=True
        )

        self.assertEqual(authorization.provider, "copilot")
        self.assertEqual(
            authorization.content_categories,
            ("feature request", "repository context"),
        )
        self.assertTrue(authorization.authorized)
        self.assertTrue(authorization.authorized_at)
        self.assertFalse(hasattr(authorization, "persistence_path"))

    def test_sanitized_environment_drops_tokens_and_dispatch_overrides(self):
        environment = build_sanitized_environment(
            {
                "PATH": "C:\\Windows",
                "SYSTEMROOT": "C:\\Windows",
                "GITHUB_TOKEN": "secret",
                "COPILOT_TOKEN": "secret",
                "SPECKIT_INTEGRATION_COPILOT_EXECUTABLE": "evil.exe",
                "SPECKIT_INTEGRATION_COPILOT_EXTRA_ARGS": "--yolo",
                "UNRELATED_SETTING": "ignored",
            },
            credential_store_env_keys=("GITHUB_TOKEN",),
        )

        self.assertEqual(environment["PATH"], "C:\\Windows")
        self.assertEqual(environment["SYSTEMROOT"], "C:\\Windows")
        self.assertEqual(environment["SPECKIT_COPILOT_ALLOW_ALL_TOOLS"], "0")
        self.assertEqual(environment["SPECKIT_ALLOW_ALL_TOOLS"], "0")
        self.assertEqual(environment["COPILOT_ALLOW_ALL"], "false")
        self.assertNotIn("GITHUB_TOKEN", environment)
        self.assertNotIn("COPILOT_TOKEN", environment)
        self.assertNotIn("GITHUB_TOKEN", environment)
        self.assertNotIn("SPECKIT_INTEGRATION_COPILOT_EXECUTABLE", environment)
        self.assertNotIn("SPECKIT_INTEGRATION_COPILOT_EXTRA_ARGS", environment)
        self.assertNotIn("UNRELATED_SETTING", environment)

    def test_planning_policy_requires_null_digest_and_feature_artifact_paths(self):
        policy = create_policy(
            phase="planning",
            repository_root=self.root,
            writable_paths=[self.plan_path],
            read_only_paths=[self.root / "src"],
            denied_paths=[self.root / ".env"],
            allowed_tools=["view", "edit"],
            allowed_commands=[],
            feature_directory=self.feature_directory,
        )

        validate_policy(policy, expected_root=self.root)
        self.assertIsNone(policy["approved_plan_digest"])

        with self.assertRaises(PolicyError):
            create_policy(
                phase="planning",
                repository_root=self.root,
                writable_paths=[self.root / "src" / "app.py"],
                read_only_paths=[],
                denied_paths=[],
                allowed_tools=["edit"],
                allowed_commands=[],
                feature_directory=self.feature_directory,
            )

        with self.assertRaises(PolicyError):
            create_policy(
                phase="planning",
                repository_root=self.root,
                writable_paths=[self.root / "specs" / "002-other" / "plan.md"],
                read_only_paths=[],
                denied_paths=[],
                allowed_tools=["edit"],
                allowed_commands=[],
                feature_directory=self.feature_directory,
            )

    def test_implementation_policy_requires_exact_approved_plan_digest(self):
        policy = create_policy(
            phase="implementation",
            repository_root=self.root,
            writable_paths=[self.root / "src"],
            read_only_paths=[self.feature_directory],
            denied_paths=[self.root / ".env"],
            allowed_tools=["view", "edit"],
            allowed_commands=[],
            approved_plan_digest="sha256:approved",
        )

        validate_policy(policy, approved_plan_digest="sha256:approved")
        with self.assertRaises(PolicyError):
            validate_policy(policy, approved_plan_digest="sha256:stale")

    def test_policy_rejects_out_of_repository_paths_and_unknown_fields(self):
        for field in ("writable_paths", "read_only_paths", "denied_paths"):
            policy = create_policy(
                phase="implementation",
                repository_root=self.root,
                writable_paths=[],
                read_only_paths=[],
                denied_paths=[],
                allowed_tools=["edit"],
                allowed_commands=[],
                approved_plan_digest="sha256:approved",
            )
            policy[field] = [str(self.root.parent / "outside")]
            with self.subTest(field=field), self.assertRaises(PolicyError):
                validate_policy(policy)

        malformed = {
            "schema_version": 1,
            "phase": "implementation",
            "approved_plan_digest": "sha256:approved",
            "repository_root": str(self.root),
            "writable_paths": [],
            "read_only_paths": [],
            "denied_paths": [],
            "allowed_tools": ["edit"],
            "allowed_commands": [],
            "unreviewed_field": True,
        }
        decision = evaluate_hook_event(
            malformed,
            {"toolName": "edit", "toolArgs": {"filePath": str(self.plan_path)}},
        )
        self.assertFalse(decision.allowed)

    def test_hook_path_comparison_is_case_insensitive_on_windows(self):
        if os.name != "nt":
            self.skipTest("Windows path comparison requires Windows")

        policy = create_policy(
            phase="implementation",
            repository_root=self.root,
            writable_paths=[self.root / "src"],
            read_only_paths=[],
            denied_paths=[],
            allowed_tools=["edit"],
            allowed_commands=[],
            approved_plan_digest="sha256:approved",
        )
        case_variant = Path(str(self.root / "src" / "app.py").upper())

        decision = evaluate_hook_event(
            policy,
            {"toolName": "edit", "toolArgs": {"filePath": str(case_variant)}},
        )

        self.assertTrue(decision.allowed)

    def test_policy_rejects_traversal_unc_and_link_escape(self):
        for unsafe_path in (
            self.root / "src" / ".." / "outside.py",
            Path("\\\\server\\share\\outside.py"),
            Path("\\\\?\\C:\\outside.py"),
        ):
            with self.subTest(path=unsafe_path), self.assertRaises(PolicyError):
                create_policy(
                    phase="implementation",
                    repository_root=self.root,
                    writable_paths=[unsafe_path],
                    read_only_paths=[],
                    denied_paths=[],
                    allowed_tools=["edit"],
                    allowed_commands=[],
                    approved_plan_digest="sha256:approved",
                )

        outside = self.root.parent / "outside"
        outside.mkdir(exist_ok=True)
        link = self.root / "linked-outside"
        target = link / "file.py"
        resolve_path = Path.resolve

        def resolve_with_escape(path, strict=False):
            if path == target:
                return outside / "file.py"
            return resolve_path(path, strict=strict)

        with patch("software_factory.policy.Path.resolve", resolve_with_escape):
            with self.assertRaises(PolicyError):
                create_policy(
                    phase="implementation",
                    repository_root=self.root,
                    writable_paths=[target],
                    read_only_paths=[],
                    denied_paths=[],
                    allowed_tools=["edit"],
                    allowed_commands=[],
                    approved_plan_digest="sha256:approved",
                )

    def test_hook_event_allows_only_listed_tool_and_writable_path(self):
        policy = create_policy(
            phase="implementation",
            repository_root=self.root,
            writable_paths=[self.root / "src"],
            read_only_paths=[self.feature_directory],
            denied_paths=[self.root / ".env"],
            allowed_tools=["view", "edit"],
            allowed_commands=[
                {"command": "python -m unittest", "working_directory": str(self.root)}
            ],
            approved_plan_digest="sha256:approved",
        )

        allowed = evaluate_hook_event(
            policy,
            {
                "toolName": "edit",
                "toolArgs": {"filePath": str(self.root / "src" / "app.py")},
            },
        )
        denied = evaluate_hook_event(
            policy,
            {
                "toolName": "edit",
                "toolArgs": {"filePath": str(self.root / ".env")},
            },
        )
        unknown = evaluate_hook_event(
            policy, {"toolName": "unknown", "toolArgs": {}}
        )

        self.assertTrue(allowed.allowed)
        self.assertFalse(denied.allowed)
        self.assertFalse(unknown.allowed)

    def test_native_agent_discovery_and_task_require_explicit_policy_allowlist(self):
        policy = create_policy(
            phase="implementation",
            repository_root=self.root,
            writable_paths=[],
            read_only_paths=[self.feature_directory],
            denied_paths=[],
            allowed_tools=["read", "grep", "glob"],
            allowed_agents=["engineer", "code-review", "code-reviewer"],
            allowed_commands=[],
            approved_plan_digest="sha256:approved",
        )
        policy["allowed_tools"] = ["list_agents", "task", "read", "grep", "glob"]

        discovery = evaluate_hook_event(
            policy, {"toolName": "list_agents", "toolArgs": {}}
        )
        delegation = evaluate_hook_event(
            policy,
            {
                "toolName": "task",
                "toolArgs": {
                    "agent_type": "code-review",
                    "prompt": "Read-only review.",
                },
            },
        )
        custom_delegations = [
            evaluate_hook_event(
                policy,
                {
                    "toolName": "task",
                    "toolArgs": {"agent_type": agent, "prompt": "Inspect read-only."},
                },
            )
            for agent in ("engineer", "code-reviewer")
        ]
        unsupported_task_type = evaluate_hook_event(
            policy,
            {
                "toolName": "task",
                "toolArgs": {"agent_type": "general-purpose", "prompt": "Inspect."},
            },
        )
        discovery_not_allowlisted = create_policy(
            phase="implementation",
            repository_root=self.root,
            writable_paths=[],
            read_only_paths=[self.feature_directory],
            denied_paths=[],
            allowed_tools=["read", "grep", "glob"],
            allowed_commands=[],
            approved_plan_digest="sha256:approved",
        )
        discovery_denied = evaluate_hook_event(
            discovery_not_allowlisted,
            {"toolName": "list_agents", "toolArgs": {}},
        )
        disallowed = evaluate_hook_event(
            create_policy(
                phase="implementation",
                repository_root=self.root,
                writable_paths=[],
                read_only_paths=[self.feature_directory],
                denied_paths=[],
                allowed_tools=["read", "grep", "glob"],
                allowed_commands=[],
                approved_plan_digest="sha256:approved",
            ),
            {"toolName": "task", "toolArgs": {"agent_type": "code-review"}},
        )

        self.assertTrue(discovery.allowed)
        self.assertTrue(delegation.allowed)
        self.assertTrue(all(result.allowed for result in custom_delegations))
        self.assertFalse(unsupported_task_type.allowed)
        self.assertFalse(discovery_denied.allowed)
        self.assertFalse(disallowed.allowed)
        for tool in ("list_agents", "task"):
            with self.subTest(tool=tool), self.assertRaises(PolicyError):
                create_policy(
                    phase="implementation",
                    repository_root=self.root,
                    writable_paths=[],
                    read_only_paths=[self.feature_directory],
                    denied_paths=[],
                    allowed_tools=[tool],
                    allowed_commands=[],
                    approved_plan_digest="sha256:approved",
                )

    def test_native_task_rejects_malformed_payloads(self):
        policy = create_policy(
            phase="implementation",
            repository_root=self.root,
            writable_paths=[],
            read_only_paths=[self.feature_directory],
            denied_paths=[],
            allowed_tools=["read", "grep", "glob"],
            allowed_commands=[],
            approved_plan_digest="sha256:approved",
        )
        policy["allowed_tools"] = ["task", "read", "grep", "glob"]
        malformed_payloads = (
            {"agent_type": "engineer"},
            {"agent_type": "engineer", "prompt": " "},
            {"agent_type": "engineer", "prompt": "Inspect.", "tools": ["edit"]},
            {"agent_type": "engineer", "agentType": "engineer", "prompt": "Inspect."},
            {"agent_type": "engineer", "prompt": "Inspect.", "description": None},
            {"agent_type": "engineer", "prompt": "Inspect.", "mode": "background"},
            {"agent_type": "engineer", "prompt": "Inspect.", "name": 42},
        )

        for payload in malformed_payloads:
            with self.subTest(payload=payload):
                decision = evaluate_hook_event(
                    policy, {"toolName": "task", "toolArgs": payload}
                )
                self.assertFalse(decision.allowed)

    def test_native_task_uses_policy_agent_allowlist_and_requires_user_approval(self):
        policy = create_policy(
            phase="planning",
            repository_root=self.root,
            writable_paths=[],
            read_only_paths=[self.root / "scripts" / "validate_specialist_profiles.py"],
            denied_paths=[],
            allowed_tools=["task", "read"],
            allowed_agents=["engineer"],
            allowed_commands=[],
            feature_directory=self.feature_directory,
            allow_native_tools=True,
        )
        observed_args = {
            "agent_type": "Engineer",
            "description": "Read-only validator inspection.",
            "mode": "sync",
            "name": "Validator inspection",
            "prompt": "Inspect and explain validation behavior.",
        }
        engineer_task = evaluate_hook_event(
            policy,
            {"toolName": "task", "toolArgs": observed_args},
        )
        engineer_task_json = evaluate_hook_event(
            {**policy, "allowed_tools": ["task", "read"]},
            {"toolName": "task", "toolArgs": json.dumps(observed_args)},
        )
        denied_tasks = [
            evaluate_hook_event(
                policy,
                {"toolName": "task", "toolArgs": {"agent_type": agent, "prompt": "Inspect."}},
            )
            for agent in ("code-reviewer", "code-review", "general-purpose")
        ]
        missing_agent = evaluate_hook_event(
            policy, {"toolName": "task", "toolArgs": {"prompt": "Inspect."}}
        )

        self.assertTrue(engineer_task.allowed)
        self.assertEqual(engineer_task.permission_decision, "ask")
        self.assertTrue(engineer_task_json.allowed)
        self.assertEqual(engineer_task_json.permission_decision, "ask")
        self.assertTrue(all(not decision.allowed for decision in denied_tasks))
        self.assertTrue(all(decision.permission_decision == "deny" for decision in denied_tasks))
        self.assertFalse(missing_agent.allowed)
        self.assertEqual(missing_agent.permission_decision, "deny")

    def test_subagent_requires_allowlisted_identity_and_path_scoped_read_only_tools(self):
        policy = create_policy(
            phase="implementation",
            repository_root=self.root,
            writable_paths=[self.root / "src"],
            read_only_paths=[self.feature_directory],
            denied_paths=[self.feature_directory / "private.md"],
            allowed_tools=["view", "read", "grep", "glob", "edit", "powershell"],
            allowed_agents=["engineer"],
            allowed_commands=[
                {"command": "python -m unittest", "working_directory": str(self.root)}
            ],
            approved_plan_digest="sha256:approved",
        )
        identity = {"agentId": "subagent-1", "agentType": "engineer"}
        allowed = evaluate_hook_event(
            policy,
            {**identity, "toolName": "view", "toolArgs": {"filePath": str(self.plan_path)}},
        )
        missing_identity = evaluate_hook_event(
            policy,
            {"agentType": "engineer", "toolName": "view", "toolArgs": {"filePath": str(self.plan_path)}},
        )
        unknown_agent = evaluate_hook_event(
            policy,
            {**identity, "agentType": "general-purpose", "toolName": "view", "toolArgs": {"filePath": str(self.plan_path)}},
        )
        write_attempt = evaluate_hook_event(
            policy,
            {**identity, "toolName": "edit", "toolArgs": {"filePath": str(self.root / "src" / "app.py")}},
        )
        reviewer_write_attempt = evaluate_hook_event(
            policy,
            {
                **identity,
                "agentType": "code-reviewer",
                "toolName": "edit",
                "toolArgs": {"filePath": str(self.root / "src" / "app.py")},
            },
        )
        reviewer_read_attempt = evaluate_hook_event(
            policy,
            {
                **identity,
                "agentType": "code-reviewer",
                "toolName": "read",
                "toolArgs": {"filePath": str(self.plan_path)},
            },
        )
        command_attempt = evaluate_hook_event(
            policy,
            {**identity, "toolName": "powershell", "toolArgs": {"command": "python -m unittest", "cwd": str(self.root)}},
        )
        outside_read = evaluate_hook_event(
            policy,
            {**identity, "toolName": "read", "toolArgs": {"filePath": str(self.root / "README.md")}},
        )

        self.assertTrue(allowed.allowed)
        self.assertFalse(missing_identity.allowed)
        self.assertFalse(unknown_agent.allowed)
        self.assertFalse(write_attempt.allowed)
        self.assertFalse(reviewer_write_attempt.allowed)
        self.assertFalse(reviewer_read_attempt.allowed)
        self.assertFalse(command_attempt.allowed)
        self.assertFalse(outside_read.allowed)

    def test_powershell_hook_matches_task_and_subagent_restrictions(self):
        executable = shutil.which("powershell") or shutil.which("pwsh")
        if executable is None:
            self.skipTest("PowerShell is unavailable")

        policy = create_policy(
            phase="planning",
            repository_root=self.root,
            writable_paths=[],
            read_only_paths=[self.root / "scripts" / "validate_specialist_profiles.py"],
            denied_paths=[],
            allowed_tools=["task", "read"],
            allowed_agents=["engineer"],
            allowed_commands=[],
            feature_directory=self.feature_directory,
            allow_native_tools=True,
        )
        policy_path = self.root / "policy.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        invalid_policy = dict(policy)
        invalid_policy.pop("allowed_agents")
        invalid_policy_path = self.root / "invalid-policy.json"
        invalid_policy_path.write_text(json.dumps(invalid_policy), encoding="utf-8")
        repository_root = Path(__file__).resolve().parents[2]
        hook_config_path = repository_root / ".github" / "hooks" / "factory-policy.json"
        hook_entry = json.loads(hook_config_path.read_text(encoding="utf-8"))["hooks"]["preToolUse"][0]
        hook_command = hook_entry["powershell"]
        hook_working_directory = (repository_root / hook_entry["cwd"]).resolve()
        environment = os.environ.copy()
        environment["FACTORY_POLICY_PATH"] = str(policy_path)
        environment["FACTORY_REPOSITORY_ROOT"] = str(self.root)

        def invoke(event, *, include_policy=True, include_repository_root=True, invalid_policy_file=False):
            hook_environment = environment.copy()
            if invalid_policy_file:
                hook_environment["FACTORY_POLICY_PATH"] = str(invalid_policy_path)
            if not include_policy:
                hook_environment.pop("FACTORY_POLICY_PATH", None)
            if not include_repository_root:
                hook_environment.pop("FACTORY_REPOSITORY_ROOT", None)
            return subprocess.run(
                [executable, "-NoProfile", "-Command", hook_command],
                input=json.dumps(event),
                capture_output=True,
                text=True,
                env=hook_environment,
                cwd=hook_working_directory,
                check=False,
            )

        permitted_task = invoke(
            {
                "toolName": "task",
                "toolArgs": {
                    "agent_type": "Engineer",
                    "description": "Read-only validator inspection.",
                    "mode": "sync",
                    "name": "Validator inspection",
                    "prompt": "Inspect and explain validation behavior.",
                },
            }
        )
        permitted_task_json = invoke(
            {
                "toolName": "task",
                "toolArgs": json.dumps({
                    "agent_type": "Engineer",
                    "description": "Read-only validator inspection.",
                    "mode": "sync",
                    "name": "Validator inspection",
                    "prompt": "Inspect and explain validation behavior.",
                }),
            }
        )
        denied_reviewer_task = invoke(
            {"toolName": "task", "toolArgs": {"agent_type": "code-reviewer", "prompt": "Review only."}}
        )
        denied_agent = invoke(
            {"toolName": "task", "toolArgs": {"agent_type": "general-purpose", "prompt": "Inspect."}}
        )
        malformed_task = invoke(
            {"toolName": "task", "toolArgs": {"agent_type": "engineer", "prompt": "Inspect.", "tools": ["edit"]}}
        )
        malformed_mode_task = invoke(
            {"toolName": "task", "toolArgs": {"agent_type": "engineer", "prompt": "Inspect.", "mode": "background"}}
        )
        malformed_name_task = invoke(
            {"toolName": "task", "toolArgs": {"agent_type": "engineer", "prompt": "Inspect.", "name": 42}}
        )
        missing_task_agent = invoke(
            {"toolName": "task", "toolArgs": {"prompt": "Inspect."}}
        )
        malformed_tool_args = invoke(
            {"toolName": "task", "toolArgs": "not-json"}
        )
        permitted_read = invoke(
            {
                "agentId": "subagent-1",
                "agentType": "engineer",
                "toolName": "read",
                "toolArgs": {
                    "filePath": str(self.root / "scripts" / "validate_specialist_profiles.py")
                },
            }
        )
        permitted_view = invoke(
            {
                "agentId": "subagent-1",
                "agentType": "engineer",
                "toolName": "view",
                "toolArgs": {
                    "filePath": str(self.root / "scripts" / "validate_specialist_profiles.py")
                },
            }
        )
        denied_write = invoke(
            {
                "agentId": "subagent-1",
                "agentType": "engineer",
                "toolName": "edit",
                "toolArgs": {"filePath": str(self.root / "src" / "app.py")},
            }
        )
        denied_reviewer_write = invoke(
            {
                "agentId": "subagent-2",
                "agentType": "code-reviewer",
                "toolName": "edit",
                "toolArgs": {"filePath": str(self.root / "src" / "app.py")},
            }
        )
        missing_identity = invoke(
            {
                "agentType": "engineer",
                "toolName": "view",
                "toolArgs": {"filePath": str(self.plan_path)},
            }
        )
        invalid_identity = invoke(
            {
                "agentId": " ",
                "agentType": "engineer",
                "toolName": "view",
                "toolArgs": {"filePath": str(self.plan_path)},
            }
        )
        command_attempt = invoke(
            {
                "agentId": "subagent-3",
                "agentType": "engineer",
                "toolName": "powershell",
                "toolArgs": {"command": "python -m unittest", "cwd": str(self.root)},
            }
        )
        missing_policy = invoke(
            {"toolName": "task", "toolArgs": {"agent_type": "Engineer", "prompt": "Inspect only."}},
            include_policy=False,
        )
        missing_repository_root = invoke(
            {"toolName": "task", "toolArgs": {"agent_type": "Engineer", "prompt": "Inspect only."}},
            include_repository_root=False,
        )
        invalid_policy_result = invoke(
            {"toolName": "task", "toolArgs": {"agent_type": "Engineer", "prompt": "Inspect only."}},
            invalid_policy_file=True,
        )

        self.assertEqual(permitted_task.returncode, 0, permitted_task.stderr)
        self.assertTrue(json.loads(permitted_task.stdout)["permissionDecision"] == "ask")
        self.assertEqual(permitted_task_json.returncode, 0, permitted_task_json.stderr)
        self.assertTrue(json.loads(permitted_task_json.stdout)["permissionDecision"] == "ask")
        self.assertEqual(denied_reviewer_task.returncode, 0, denied_reviewer_task.stderr)
        self.assertTrue(json.loads(denied_reviewer_task.stdout)["permissionDecision"] == "deny")
        self.assertEqual(denied_agent.returncode, 0, denied_agent.stderr)
        self.assertTrue(json.loads(denied_agent.stdout)["permissionDecision"] == "deny")
        self.assertEqual(malformed_task.returncode, 0, malformed_task.stderr)
        self.assertTrue(json.loads(malformed_task.stdout)["permissionDecision"] == "deny")
        self.assertEqual(malformed_mode_task.returncode, 0, malformed_mode_task.stderr)
        self.assertTrue(json.loads(malformed_mode_task.stdout)["permissionDecision"] == "deny")
        self.assertEqual(malformed_name_task.returncode, 0, malformed_name_task.stderr)
        self.assertTrue(json.loads(malformed_name_task.stdout)["permissionDecision"] == "deny")
        self.assertEqual(missing_task_agent.returncode, 0, missing_task_agent.stderr)
        self.assertTrue(json.loads(missing_task_agent.stdout)["permissionDecision"] == "deny")
        self.assertEqual(malformed_tool_args.returncode, 0, malformed_tool_args.stderr)
        self.assertTrue(json.loads(malformed_tool_args.stdout)["permissionDecision"] == "deny")
        self.assertEqual(permitted_read.returncode, 0, permitted_read.stderr)
        self.assertTrue(json.loads(permitted_read.stdout)["permissionDecision"] == "allow")
        self.assertEqual(permitted_view.returncode, 0, permitted_view.stderr)
        self.assertTrue(json.loads(permitted_view.stdout)["permissionDecision"] == "allow")
        self.assertEqual(denied_write.returncode, 0, denied_write.stderr)
        self.assertTrue(json.loads(denied_write.stdout)["permissionDecision"] == "deny")
        self.assertEqual(denied_reviewer_write.returncode, 0, denied_reviewer_write.stderr)
        self.assertTrue(json.loads(denied_reviewer_write.stdout)["permissionDecision"] == "deny")
        self.assertEqual(missing_identity.returncode, 0, missing_identity.stderr)
        self.assertTrue(json.loads(missing_identity.stdout)["permissionDecision"] == "deny")
        self.assertEqual(invalid_identity.returncode, 0, invalid_identity.stderr)
        self.assertTrue(json.loads(invalid_identity.stdout)["permissionDecision"] == "deny")
        self.assertEqual(command_attempt.returncode, 0, command_attempt.stderr)
        self.assertTrue(json.loads(command_attempt.stdout)["permissionDecision"] == "deny")
        self.assertEqual(missing_policy.returncode, 0, missing_policy.stderr)
        self.assertTrue(json.loads(missing_policy.stdout)["permissionDecision"] == "deny")
        self.assertEqual(missing_repository_root.returncode, 0, missing_repository_root.stderr)
        self.assertTrue(json.loads(missing_repository_root.stdout)["permissionDecision"] == "deny")
        self.assertEqual(invalid_policy_result.returncode, 0, invalid_policy_result.stderr)
        self.assertTrue(json.loads(invalid_policy_result.stdout)["permissionDecision"] == "deny")
    def test_read_tool_requires_a_target_within_an_allowed_read_scope(self):
        policy = create_policy(
            phase="implementation",
            repository_root=self.root,
            writable_paths=[],
            read_only_paths=[self.feature_directory],
            denied_paths=[self.feature_directory / "private.md"],
            allowed_tools=["read"],
            allowed_commands=[],
            approved_plan_digest="sha256:approved",
        )

        allowed = evaluate_hook_event(
            policy,
            {"toolName": "read", "toolArgs": {"filePath": str(self.plan_path)}},
        )
        cli_view = evaluate_hook_event(
            policy,
            {"toolName": "view", "toolArgs": {"filePath": str(self.plan_path)}},
        )
        outside = evaluate_hook_event(
            policy,
            {"toolName": "read", "toolArgs": {"filePath": str(self.root / "README.md")}},
        )
        denied = evaluate_hook_event(
            policy,
            {
                "toolName": "read",
                "toolArgs": {
                    "filePath": str(self.feature_directory / "private.md")
                },
            },
        )
        missing_target = evaluate_hook_event(
            policy, {"toolName": "read", "toolArgs": {"limit": 20}}
        )

        self.assertTrue(allowed.allowed)
        self.assertTrue(cli_view.allowed)
        self.assertFalse(outside.allowed)
        self.assertFalse(denied.allowed)
        self.assertFalse(missing_target.allowed)

    def test_hook_event_accepts_object_and_json_string_payload_variants(self):
        policy = create_policy(
            phase="implementation",
            repository_root=self.root,
            writable_paths=[self.root / "src"],
            read_only_paths=[],
            denied_paths=[],
            allowed_tools=["edit"],
            allowed_commands=[],
            approved_plan_digest="sha256:approved",
        )
        target = self.root / "src" / "app.py"

        native = evaluate_hook_event(
            policy, {"toolName": "edit", "toolArgs": {"filePath": str(target)}}
        )
        encoded = evaluate_hook_event(
            policy,
            {
                "tool_name": "edit",
                "tool_input": json.dumps({"file_path": str(target)}),
            },
        )
        malformed = evaluate_hook_event(
            policy, {"toolName": "edit", "toolArgs": "not-json"}
        )

        self.assertTrue(native.allowed)
        self.assertTrue(encoded.allowed)
        self.assertFalse(malformed.allowed)

    def test_powershell_hook_requires_exact_command_and_working_directory(self):
        command = "python -m unittest"
        policy = create_policy(
            phase="implementation",
            repository_root=self.root,
            writable_paths=[],
            read_only_paths=[],
            denied_paths=[],
            allowed_tools=["powershell"],
            allowed_commands=[
                {"command": command, "working_directory": str(self.root)}
            ],
            approved_plan_digest="sha256:approved",
        )
        accepted = evaluate_hook_event(
            policy,
            {
                "toolName": "powershell",
                "toolArgs": {"command": command, "cwd": str(self.root)},
            },
        )
        altered = evaluate_hook_event(
            policy,
            {
                "toolName": "powershell",
                "toolArgs": {"command": command + " --failfast", "cwd": str(self.root)},
            },
        )

        self.assertTrue(accepted.allowed)
        self.assertFalse(altered.allowed)


if __name__ == "__main__":
    unittest.main()