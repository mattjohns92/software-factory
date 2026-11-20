import json
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
        unsupported_task_type = evaluate_hook_event(
            policy,
            {"toolName": "task", "toolArgs": {"agent_type": "general-purpose"}},
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