import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from software_factory.policy import authorize_hosted_use
from software_factory.preflight import PreflightReport
from software_factory.cli import _refresh_delivery_report
from software_factory.runner import NativeRunState


class FactoryCliTests(unittest.TestCase):
    def invoke(self, arguments, *, provider="GitHub Copilot", preflight=None, answer="yes"):
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"FACTORY_HOSTED_PROVIDER": provider}, clear=False),
            patch("software_factory.cli.load_policy", return_value={"phase": "planning"}),
            patch(
                "software_factory.cli.run_static_preflight",
                return_value=preflight or PreflightReport(("static checks passed",), ()),
            ),
            patch(
                "software_factory.cli.run_native_workflow",
                return_value=subprocess.CompletedProcess(
                    [], 0, '{"run_id":"run-1","status":"paused","current_step":"review-spec"}', ""
                ),
            ) as run_workflow,
            patch("software_factory.cli.load_security_probe", return_value=object()),
            patch("software_factory.cli._store_authorization"),
            patch("software_factory.cli.write_delivery_report", return_value="delivery-report.md"),
            patch("builtins.input", return_value=answer),
            patch("sys.stdin.isatty", return_value=True),
            redirect_stdout(output),
        ):
            from software_factory.cli import main
            status = main(arguments)
        return status, output.getvalue(), run_workflow

    def test_feature_run_discloses_provider_data_quota_and_visible_route_before_dispatch(self):
        status, output, run_workflow = self.invoke(
            ["run", "--type", "feature", "Add a small example feature"]
        )

        self.assertEqual(status, 0)
        self.assertIn("Provider: GitHub Copilot", output)
        self.assertIn("feature request", output)
        self.assertIn("repository content", output)
        self.assertIn("tool output", output)
        self.assertIn("quota or credits", output)
        self.assertIn("Route: feature -> speckit", output)
        self.assertIn("Scope:", output)
        run_workflow.assert_called_once()
        self.assertEqual(
            run_workflow.call_args.args[0], "Add a small example feature"
        )

    def test_noninteractive_run_requires_explicit_hosted_authorization(self):
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"FACTORY_HOSTED_PROVIDER": "GitHub Copilot"}),
            patch("software_factory.cli.load_policy", return_value={"phase": "planning"}),
            patch("software_factory.cli.load_security_probe", return_value=object()),
            patch(
                "software_factory.cli.run_static_preflight",
                return_value=PreflightReport(("static checks passed",), ()),
            ),
            patch("software_factory.cli.run_native_workflow") as run_workflow,
            patch("sys.stdin.isatty", return_value=False),
            redirect_stdout(output),
        ):
            from software_factory.cli import main

            status = main(["run", "--type", "feature", "Add an example"])

        self.assertNotEqual(status, 0)
        self.assertIn("--authorize-hosted-agent", output.getvalue())
        run_workflow.assert_not_called()

    def test_explicit_noninteractive_authorization_dispatches_once(self):
        status, _, run_workflow = self.invoke(
            ["run", "--type", "feature", "--authorize-hosted-agent", "Add an example"]
        )

        self.assertEqual(status, 0)
        run_workflow.assert_called_once()

    def test_bug_fix_and_ambiguous_requests_are_blocked_before_dispatch(self):
        for request in ("Fix the broken login", "Improve it"):
            with self.subTest(request=request):
                output = io.StringIO()
                with (
                    patch.dict(os.environ, {"FACTORY_HOSTED_PROVIDER": "GitHub Copilot"}),
                    patch("software_factory.cli.load_policy", return_value={"phase": "planning"}),
                    patch("software_factory.cli.run_static_preflight") as preflight,
                    patch("software_factory.cli.run_native_workflow") as run_workflow,
                    redirect_stdout(output),
                ):
                    from software_factory.cli import main

                    status = main(["run", "--type", "feature", request])

                self.assertNotEqual(status, 0)
                self.assertIn("Blocking question:", output.getvalue())
                preflight.assert_not_called()
                run_workflow.assert_not_called()

    def test_unknown_provider_or_failed_preflight_blocks_dispatch(self):
        status, output, run_workflow = self.invoke(
            ["run", "--type", "feature", "--authorize-hosted-agent", "Add an example"],
            provider="",
        )
        self.assertNotEqual(status, 0)
        self.assertIn("provider", output.casefold())
        run_workflow.assert_not_called()

        status, output, run_workflow = self.invoke(
            ["run", "--type", "feature", "--authorize-hosted-agent", "Add an example"],
            preflight=PreflightReport((), ("workflow missing",)),
        )
        self.assertNotEqual(status, 0)
        self.assertIn("workflow missing", output)
        run_workflow.assert_not_called()

    def test_doctor_reports_static_checks_and_unverified_live_capabilities(self):
        output = io.StringIO()
        with (
            patch("software_factory.cli.load_policy", return_value={"phase": "planning"}),
            patch(
                "software_factory.cli.run_static_preflight",
                return_value=PreflightReport(("versions and workflow are ready",), ()),
            ),
            redirect_stdout(output),
        ):
            from software_factory.cli import main

            status = main(["doctor"])

        self.assertEqual(status, 0)
        self.assertIn("PASS: versions and workflow are ready", output.getvalue())
        for capability in ("authentication", "live dispatch", "effective sandbox enforcement"):
            self.assertIn(capability, output.getvalue())

    def test_status_uses_native_run_identity(self):
        output = io.StringIO()
        with (
            patch(
                "software_factory.cli.get_native_workflow_status",
                return_value=NativeRunState("run-1", "paused", "review-spec", "speckit"),
            ) as get_status,
            redirect_stdout(output),
        ):
            from software_factory.cli import main

            status = main(["status", "run-1"])

        self.assertEqual(status, 0)
        self.assertIn("Run: run-1", output.getvalue())
        self.assertIn("Current step: review-spec", output.getvalue())
        get_status.assert_called_once()

    def test_resume_requires_explicit_gate_decision_and_keeps_native_identity(self):
        authorization = authorize_hosted_use(
            "GitHub Copilot", ["feature request"], accepted=True
        )
        output = io.StringIO()
        with (
            patch("software_factory.cli._load_authorization", return_value=authorization),
            patch("software_factory.cli.load_policy", return_value={"phase": "planning"}),
            patch("software_factory.cli.load_security_probe", return_value=object()),
            patch(
                "software_factory.cli.run_static_preflight",
                return_value=PreflightReport(("static checks passed",), ()),
            ),
            patch(
                "software_factory.cli.resume_native_workflow",
                return_value=subprocess.CompletedProcess(
                    [],
                    0,
                    '{"run_id":"run-1","status":"paused","current_step":"plan","workflow_id":"speckit"}',
                    "",
                ),
            ) as resume,
            patch(
                "software_factory.cli.get_native_workflow_status",
                return_value=NativeRunState("run-1", "paused", "plan", "speckit"),
            ),
            redirect_stdout(output),
        ):
            from software_factory.cli import main

            status = main(
                ["resume", "run-1", "--gate", "spec", "--decision", "approve"]
            )

        self.assertEqual(status, 0)
        self.assertIn("Native run: run-1", output.getvalue())
        resume.assert_called_once()
        self.assertEqual(resume.call_args.args[0:3], ("run-1", "spec", "approve"))

    def test_report_refresh_preserves_baseline_and_adds_native_evidence(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_directory = root / ".specify" / "workflows" / "runs" / "run-1"
            run_directory.mkdir(parents=True)
            authorization = authorize_hosted_use(
                "GitHub Copilot", ["feature request"], accepted=True
            )
            state = NativeRunState(
                "run-1",
                "completed",
                "implement",
                "speckit",
                (
                    {"step_id": "review-spec", "decision": "approve"},
                    {"step_id": "review-plan", "verdict": "approve"},
                    {"command": "uv run tests", "exit_code": 0},
                ),
                None,
                "",
            )
            with (
                patch(
                    "software_factory.cli._load_run_metadata",
                    return_value={
                        "request": "Add a feature",
                        "pre_existing_snapshot": {"README.md": " M:old-hash"},
                    },
                ),
                patch("software_factory.cli._load_authorization", return_value=authorization),
                patch(
                    "software_factory.cli._git_status_snapshot",
                    return_value={
                        "README.md": " M:new-hash",
                        "src/new.py": "??:new-hash",
                    },
                ),
                patch("software_factory.cli._approved_plan_checks", return_value=("uv run tests",)),
                patch("software_factory.cli._observed_scope_violations", return_value=()),
            ):
                report_path = _refresh_delivery_report(root, state)

            report = report_path.read_text(encoding="utf-8")
            self.assertEqual(report_path, run_directory / "delivery-report.md")
            self.assertIn("Add a feature", report)
            self.assertIn("spec: approve", report)
            self.assertIn("plan: approve", report)
            self.assertIn("README.md", report)
            self.assertIn("src/new.py", report)
            self.assertIn("uv run tests", report)
            self.assertIn("completed-with-limitations", report)
            self.assertIn("does not attribute writes to planning versus implementation phases", report)


if __name__ == "__main__":
    unittest.main()