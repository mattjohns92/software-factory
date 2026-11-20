import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from software_factory.policy import authorize_hosted_use, create_policy
from software_factory.preflight import PreflightReport
from software_factory.runner import (
    DispatchBoundary,
    RunnerError,
    compute_security_fingerprint,
    parse_native_run_result,
    run_native_workflow,
    resume_native_workflow,
)

_USE_DEFAULT_AUTHORIZATION = object()


class RunnerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name, "repo").resolve()
        self.root.mkdir()
        self.feature_directory = self.root / "specs" / "001-example"
        self.feature_directory.mkdir(parents=True)
        self.factory_home = self.root / ".factory-copilot-home"
        self.policy_path = self.factory_home / "policy.json"
        self.policy = self.make_policy()
        self.authorization = authorize_hosted_use(
            "copilot", ["feature request", "repository context"], accepted=True
        )
        self.preflight = PreflightReport(("static checks passed",), ())
        self.boundary = self.make_boundary(self.policy)
        self.run = Mock(return_value=subprocess.CompletedProcess([], 0, "{\"run_id\": \"r1\"}", ""))

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_policy(self, *, phase="planning", digest=None):
        return create_policy(
            phase=phase,
            repository_root=self.root,
            writable_paths=[self.feature_directory / "plan.md"],
            read_only_paths=[self.root / "src"],
            denied_paths=[self.root / ".env"],
            allowed_tools=["view", "edit", "powershell"],
            allowed_commands=[
                {"command": "python -m unittest", "working_directory": str(self.root)}
            ],
            approved_plan_digest=digest,
            feature_directory=self.feature_directory if phase == "planning" else None,
        )

    def make_boundary(self, policy):
        boundary = DispatchBoundary(
            inventory_complete=True,
            sandbox_enabled=True,
            available_tools=("edit", "powershell", "view"),
            builtin_mcps_disabled=True,
            configured_mcp_servers=("custom-server",),
            disabled_mcp_servers=("custom-server",),
            plugin_sources=(),
            hook_sources=(".github/hooks/factory-policy.json",),
            denied_with_hook=True,
            denied_without_hook=True,
            probe_produced_no_diff=True,
            approved_checks_usable=True,
            runtime_fingerprint=(
                "Windows; PowerShell; Specify 1.0.6; speckit 1.0.2; Copilot 1.0.114"
            ),
            security_probe_fingerprint=None,
        )
        return replace(
            boundary,
            security_probe_fingerprint=compute_security_fingerprint(
                policy, self.root, boundary
            ),
        )

    def invoke(
        self,
        *,
        policy=None,
        boundary=None,
        expected_digest=None,
        authorization=_USE_DEFAULT_AUTHORIZATION,
        preflight=None,
    ):
        return run_native_workflow(
            "Add a small example feature",
            self.root,
            policy if policy is not None else self.policy,
            authorization=(
                self.authorization
                if authorization is _USE_DEFAULT_AUTHORIZATION
                else authorization
            ),
            preflight=preflight or self.preflight,
            boundary=boundary or self.boundary,
            policy_path=self.policy_path,
            factory_home=self.factory_home,
            expected_plan_digest=expected_digest,
            source_environment={"PATH": "C:\\Windows", "COPILOT_TOKEN": "do-not-forward"},
            which=lambda name: f"C:/tools/{name}.exe",
            run=self.run,
        )

    def test_invalid_malformed_stale_mismatched_and_out_of_scope_policy_never_dispatch(self):
        malformed = dict(self.policy)
        malformed["unknown"] = True
        stale = self.make_policy(phase="implementation", digest="sha256:stale")
        mismatched_root = dict(self.policy)
        mismatched_root["repository_root"] = str(self.root.parent)
        out_of_scope = dict(self.policy)
        out_of_scope["writable_paths"] = [str(self.root.parent / "outside")]

        for policy, expected_digest in (
            (malformed, None),
            (stale, "sha256:approved"),
            (mismatched_root, None),
            (out_of_scope, None),
        ):
            with self.subTest(policy=policy):
                self.run.reset_mock()
                with self.assertRaises(RunnerError):
                    self.invoke(policy=policy, expected_digest=expected_digest)
                self.run.assert_not_called()

    def test_missing_probe_or_incomplete_inventory_never_dispatches(self):
        cases = (
            replace(self.boundary, security_probe_fingerprint=None),
            replace(self.boundary, inventory_complete=False),
            replace(self.boundary, sandbox_enabled=False),
            replace(self.boundary, denied_without_hook=False),
            replace(self.boundary, probe_produced_no_diff=False),
            replace(self.boundary, approved_checks_usable=False),
            replace(self.boundary, plugin_sources=("unreviewed-plugin",)),
            replace(self.boundary, hook_sources=(".github/hooks/other.json",)),
            replace(self.boundary, disabled_mcp_servers=()),
            replace(self.boundary, sandbox_enabled="false"),
            replace(self.boundary, available_tools=(1,)),
        )
        for boundary in cases:
            with self.subTest(boundary=boundary):
                self.run.reset_mock()
                with self.assertRaises(RunnerError):
                    self.invoke(boundary=boundary)
                self.run.assert_not_called()

    def test_refusal_and_static_preflight_failure_never_dispatch(self):
        self.run.reset_mock()
        with self.assertRaises(RunnerError):
            self.invoke(authorization=None)
        self.run.assert_not_called()

        self.run.reset_mock()
        with self.assertRaises(RunnerError):
            self.invoke(preflight=PreflightReport((), ("missing executable",)))
        self.run.assert_not_called()

    def test_approved_static_boundary_uses_shell_free_fixed_policy_invocation(self):
        result = self.invoke()

        self.assertEqual(result.returncode, 0)
        self.run.assert_called_once()
        arguments = self.run.call_args.args[0]
        options = self.run.call_args.kwargs
        self.assertEqual(
            arguments[:5],
            ["C:/tools/specify.exe", "workflow", "run", "speckit", "--json"],
        )
        self.assertEqual(arguments[-2:], ["--input", "spec=Add a small example feature"])
        self.assertNotIn("speckit_review_spec_verdict", arguments)
        self.assertNotIn("speckit_review_plan_verdict", arguments)
        self.assertIs(options["shell"], False)
        self.assertEqual(options["cwd"], self.root)
        self.assertEqual(options["env"]["SPECKIT_COPILOT_ALLOW_ALL_TOOLS"], "0")
        self.assertEqual(options["env"]["SPECKIT_ALLOW_ALL_TOOLS"], "0")
        self.assertEqual(options["env"]["COPILOT_ALLOW_ALL"], "false")
        self.assertNotIn("COPILOT_TOKEN", options["env"])
        self.assertEqual(options["env"]["FACTORY_POLICY_PATH"], str(self.policy_path))
        self.assertEqual(options["env"]["FACTORY_REPOSITORY_ROOT"], str(self.root))
        self.assertIn("--sandbox", options["env"]["SPECKIT_INTEGRATION_COPILOT_EXTRA_ARGS"])
        self.assertIn("--disable-builtin-mcps", options["env"]["SPECKIT_INTEGRATION_COPILOT_EXTRA_ARGS"])
        self.assertEqual(json.loads(self.policy_path.read_text()), self.policy)
        settings = json.loads((self.factory_home / "settings.json").read_text())
        sandbox = settings["sandbox"]
        self.assertTrue(sandbox["enabled"])
        self.assertFalse(sandbox["allowBypass"])
        self.assertFalse(sandbox["userPolicy"]["network"]["allowOutbound"])

    def test_existing_different_factory_profile_blocks_before_dispatch(self):
        self.factory_home.mkdir()
        (self.factory_home / "settings.json").write_text("{}")

        with self.assertRaises(RunnerError):
            self.invoke()

        self.run.assert_not_called()

    def test_native_run_result_parses_real_run_identity(self):
        result = subprocess.CompletedProcess(
            [],
            0,
            '{"run_id":"run-1","status":"paused","current_step":"review-spec"}',
            "",
        )

        run = parse_native_run_result(result)

        self.assertEqual(run.run_id, "run-1")
        self.assertEqual(run.status, "paused")
        self.assertEqual(run.current_step, "review-spec")

    def test_explicit_approval_resumes_the_same_paused_native_run(self):
        status = subprocess.CompletedProcess(
            [],
            0,
            '{"run_id":"run-1","workflow_id":"speckit","status":"paused","current_step":"review-spec"}',
            "",
        )
        resumed = subprocess.CompletedProcess([], 0, '{"run_id":"run-1"}', "")
        invoke = Mock(side_effect=(status, resumed))

        result = resume_native_workflow(
            "run-1",
            "spec",
            "approve",
            self.root,
            self.policy,
            authorization=self.authorization,
            preflight=self.preflight,
            boundary=self.boundary,
            policy_path=self.policy_path,
            factory_home=self.factory_home,
            which=lambda name: "C:/tools/specify.exe",
            run=invoke,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(invoke.call_count, 2)
        status_args = invoke.call_args_list[0].args[0]
        resume_call = invoke.call_args_list[1]
        self.assertEqual(status_args[1:], ["workflow", "status", "run-1", "--json"])
        self.assertEqual(
            resume_call.args[0][1:],
            [
                "workflow",
                "resume",
                "run-1",
                "--json",
                "--input",
                "speckit_review_spec_verdict=approve",
            ],
        )
        self.assertIs(resume_call.kwargs["shell"], False)
        self.assertEqual(resume_call.kwargs["cwd"], self.root)


if __name__ == "__main__":
    unittest.main()
