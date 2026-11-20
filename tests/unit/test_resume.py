import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from software_factory.policy import authorize_hosted_use, create_policy
from software_factory.preflight import PreflightReport
from software_factory.runner import (
    DispatchBoundary,
    RunnerError,
    compute_security_fingerprint,
    resume_native_workflow,
)


class NativeResumeTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name, "repo").resolve()
        self.root.mkdir()
        feature_directory = self.root / "specs" / "001-example"
        feature_directory.mkdir(parents=True)
        self.policy = create_policy(
            phase="planning",
            repository_root=self.root,
            writable_paths=[feature_directory / "plan.md"],
            read_only_paths=[feature_directory],
            denied_paths=[self.root / ".env"],
            allowed_tools=["view", "edit"],
            allowed_commands=[],
            feature_directory=feature_directory,
        )
        self.authorization = authorize_hosted_use(
            "GitHub Copilot", ["feature request"], accepted=True
        )
        self.preflight = PreflightReport(("static checks passed",), ())
        self.boundary = DispatchBoundary(
            inventory_complete=True,
            sandbox_enabled=True,
            available_tools=("edit", "view"),
            builtin_mcps_disabled=True,
            configured_mcp_servers=(),
            disabled_mcp_servers=(),
            plugin_sources=(),
            hook_sources=(".github/hooks/factory-policy.json",),
            denied_with_hook=True,
            denied_without_hook=True,
            probe_produced_no_diff=True,
            approved_checks_usable=True,
            runtime_fingerprint="test-runtime",
            security_probe_fingerprint=None,
        )
        self.boundary = DispatchBoundary(
            **{
                **self.boundary.__dict__,
                "security_probe_fingerprint": compute_security_fingerprint(
                    self.policy, self.root, self.boundary
                ),
            }
        )
        self.factory_home = self.root / ".factory-home"
        self.policy_path = self.factory_home / "policy.json"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def invoke(self, status, *, gate="spec", decision="approve", resume_id="run-1"):
        status_result = subprocess.CompletedProcess(
            [], 0, json.dumps(status), ""
        )
        resume_result = subprocess.CompletedProcess(
            [], 0, json.dumps({"run_id": resume_id}), ""
        )
        outputs = [status_result, resume_result]
        if decision == "reject":
            outputs.append(status_result)
        process = Mock(side_effect=outputs)
        result = resume_native_workflow(
            "run-1",
            gate,
            decision,
            self.root,
            self.policy,
            authorization=self.authorization,
            preflight=self.preflight,
            boundary=self.boundary,
            policy_path=self.policy_path,
            factory_home=self.factory_home,
            which=lambda name: "specify.exe",
            run=process,
        )
        return result, process

    def test_pending_spec_gate_acceptance_resumes_same_run(self):
        status = {
            "run_id": "run-1",
            "workflow_id": "speckit",
            "status": "paused",
            "current_step": "review-spec",
        }

        result, process = self.invoke(status)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(process.call_count, 2)
        self.assertIn("speckit_review_spec_verdict=approve", process.call_args.args[0])

    def test_rejection_resumes_the_same_run_with_explicit_reject(self):
        status = {
            "run_id": "run-1",
            "workflow_id": "speckit",
            "status": "paused",
            "current_step": "review-spec",
        }

        result, process = self.invoke(status, decision="reject")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(process.call_count, 3)
        resume_arguments = process.call_args_list[1].args[0]
        self.assertIn("speckit_review_spec_verdict=reject", resume_arguments)
        self.assertIn("run-1", resume_arguments)

    def test_wrong_gate_wrong_run_or_nonresumable_state_never_resumes(self):
        cases = (
            ({"run_id": "run-1", "workflow_id": "speckit", "status": "paused", "current_step": "review-plan"}, "spec"),
            ({"run_id": "other", "workflow_id": "speckit", "status": "paused", "current_step": "review-spec"}, "spec"),
            ({"run_id": "run-1", "workflow_id": "speckit", "status": "running", "current_step": "review-spec"}, "spec"),
            ({"run_id": "run-1", "workflow_id": "speckit", "status": "completed", "current_step": "review-spec"}, "spec"),
        )
        for state, gate in cases:
            with self.subTest(state=state):
                status_result = subprocess.CompletedProcess([], 0, json.dumps(state), "")
                process = Mock(return_value=status_result)
                with self.assertRaises(RunnerError):
                    resume_native_workflow(
                        "run-1",
                        gate,
                        "approve",
                        self.root,
                        self.policy,
                        authorization=self.authorization,
                        preflight=self.preflight,
                        boundary=self.boundary,
                        policy_path=self.policy_path,
                        factory_home=self.factory_home,
                        which=lambda name: "specify.exe",
                        run=process,
                    )
                self.assertEqual(process.call_count, 1)

    def test_missing_decision_is_not_approval_and_never_queries_or_resumes(self):
        process = Mock()

        with self.assertRaises(RunnerError):
            resume_native_workflow(
                "run-1",
                "spec",
                "",
                self.root,
                self.policy,
                authorization=self.authorization,
                preflight=self.preflight,
                boundary=self.boundary,
                policy_path=self.policy_path,
                factory_home=self.factory_home,
                which=lambda name: "specify.exe",
                run=process,
            )

        process.assert_not_called()


if __name__ == "__main__":
    unittest.main()