import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from software_factory.policy import create_policy
from software_factory.preflight import run_static_preflight


class StaticPreflightTests(unittest.TestCase):
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
            read_only_paths=[self.root / "src"],
            denied_paths=[self.root / ".env"],
            allowed_tools=["view", "edit"],
            allowed_commands=[],
            feature_directory=feature_directory,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_static_preflight_checks_version_integration_workflow_and_policy(self):
        outputs = {
            ("specify", "--version"): "specify 1.0.6\n",
            ("copilot", "--version"): "GitHub Copilot CLI 1.0.114.\n",
            ("specify", "integration", "status", "--json"): json.dumps(
                {
                    "status": "ok",
                    "default_integration": "copilot",
                    "installed_integrations": ["copilot"],
                    "missing_managed_files": 0,
                    "modified_managed_files": 0,
                    "invalid_manifest_paths": 0,
                    "unchecked_manifests": 0,
                    "findings": [],
                }
            ),
            ("specify", "workflow", "info", "speckit"):
                "Full SDD Cycle (speckit)\n  Version:     1.0.2\n  Installed\n"
                "  Inputs: spec, integration, speckit_review_spec_verdict, "
                "speckit_review_plan_verdict\n",
            ("specify", "workflow", "resolve", "speckit"):
                "Resolved workflow 'speckit':\n  • [base] base\n"
                "Step attribution:\n  • specify: base\n  • review-spec: base\n"
                "  • plan: base\n  • review-plan: base\n"
                "  • tasks: base\n  • implement: base\n",
        }
        calls = []

        def run(arguments, **kwargs):
            calls.append((arguments, kwargs))
            key = (Path(arguments[0]).stem, *arguments[1:])
            return subprocess.CompletedProcess(
                arguments, 0, outputs[key], ""
            )

        report = run_static_preflight(
            self.root,
            self.policy,
            which=lambda name: f"C:/tools/{name}.exe",
            run=run,
        )

        self.assertTrue(report.ready, report.blockers)
        self.assertEqual(
            report.unverified,
            ("authentication", "live dispatch", "effective sandbox enforcement"),
        )
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(kwargs["shell"] is False for _, kwargs in calls))
        self.assertTrue(all(kwargs["cwd"] == self.root for _, kwargs in calls))
        self.assertFalse(any("run" in arguments for arguments, _ in calls))

    def test_static_preflight_blocks_wrong_versions_and_non_ok_integration(self):
        outputs = {
            ("specify", "--version"): "specify 9.9.9\n",
            ("copilot", "--version"): "GitHub Copilot CLI 1.0.114.\n",
            ("specify", "integration", "status", "--json"): json.dumps(
                {"status": "error", "findings": ["missing integration"]}
            ),
            ("specify", "workflow", "info", "speckit"): "Version: 1.0.1\n",
            ("specify", "workflow", "resolve", "speckit"):
                "Resolved workflow 'speckit':\n  • specify: base\n",
        }

        report = run_static_preflight(
            self.root,
            self.policy,
            which=lambda name: f"C:/tools/{name}.exe",
            run=lambda arguments, **kwargs: subprocess.CompletedProcess(
                arguments,
                0,
                outputs[(Path(arguments[0]).stem, *arguments[1:])],
                "",
            ),
        )

        self.assertFalse(report.ready)
        self.assertTrue(any("Specify" in blocker for blocker in report.blockers))
        self.assertTrue(any("integration" in blocker.lower() for blocker in report.blockers))
        self.assertTrue(any("workflow" in blocker.lower() for blocker in report.blockers))

    def test_static_preflight_blocks_invalid_policy_before_running_commands(self):
        invalid_policy = dict(self.policy)
        invalid_policy["approved_plan_digest"] = "sha256:unexpected"

        report = run_static_preflight(
            self.root,
            invalid_policy,
            which=lambda name: f"C:/tools/{name}.exe",
            run=lambda *args, **kwargs: self.fail("No command should run without both executables"),
        )

        self.assertFalse(report.ready)
        self.assertTrue(any("policy" in blocker.lower() for blocker in report.blockers))
        self.assertEqual(
            report.unverified,
            ("authentication", "live dispatch", "effective sandbox enforcement"),
        )

    def test_static_preflight_blocks_missing_executable_without_running_commands(self):
        report = run_static_preflight(
            self.root,
            self.policy,
            which=lambda name: None if name == "copilot" else "C:/tools/specify.exe",
            run=lambda *args, **kwargs: self.fail("Commands should not run when an executable is missing"),
        )

        self.assertFalse(report.ready)
        self.assertTrue(any("copilot" in blocker.lower() for blocker in report.blockers))


if __name__ == "__main__":
    unittest.main()
