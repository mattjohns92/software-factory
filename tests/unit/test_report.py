import tempfile
import unittest
from pathlib import Path

from software_factory.policy import authorize_hosted_use
from software_factory.report import (
    classify_outcome,
    collect_required_checks,
    redact_sensitive,
    write_delivery_report,
)
from software_factory.runner import NativeRunState


class DeliveryReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.run_directory = self.root / ".specify" / "workflows" / "runs" / "run-1"
        self.run_directory.mkdir(parents=True)
        self.run = NativeRunState("run-1", "paused", "review-spec", "speckit")
        self.authorization = authorize_hosted_use(
            "GitHub Copilot",
            ["feature request", "repository content", "selected tool output"],
            accepted=True,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_initial_report_records_real_run_and_marks_unobserved_evidence(self):
        path = write_delivery_report(
            self.root,
            self.run,
            request="Add an example feature",
            authorization=self.authorization,
            route="feature -> speckit",
            approval_decisions=("spec: pending", "plan: pending"),
            pre_existing_paths=(),
            changed_paths=(),
            scope_review="Pending native approval; no implementation scope review yet.",
            required_checks=(),
            known_issues=("Not yet evaluated.",),
            limitations=("Implementation has not begun.",),
            next_action="Review the generated specification.",
            outcome="blocked",
        )

        report = path.read_text(encoding="utf-8")
        self.assertEqual(path, self.run_directory / "delivery-report.md")
        for expected in (
            "run-1",
            "paused",
            "Add an example feature",
            "GitHub Copilot",
            "spec: pending",
            "No changed paths observed.",
            "No required checks have run.",
            "Pending native approval",
            "Not yet evaluated.",
            "Review the generated specification.",
            "blocked",
        ):
            self.assertIn(expected, report)

    def test_report_requires_an_existing_native_run_directory(self):
        self.run_directory.rmdir()

        with self.assertRaises(ValueError):
            write_delivery_report(
                self.root,
                self.run,
                request="Add an example feature",
                authorization=self.authorization,
                route="feature -> speckit",
                approval_decisions=(),
                pre_existing_paths=(),
                changed_paths=(),
                scope_review="Pending",
                required_checks=(),
                known_issues=(),
                limitations=(),
                next_action="Inspect status.",
                outcome="blocked",
            )

    def test_required_checks_are_the_union_of_plan_repository_and_owner_sources(self):
        workflow_directory = self.root / ".github" / "workflows"
        workflow_directory.mkdir(parents=True)
        (workflow_directory / "checks.yml").write_text(
            "jobs:\n  test:\n    steps:\n      - name: Unit tests\n        run: uv run python -m unittest discover -s tests\n",
            encoding="utf-8",
        )
        (self.root / "CONTRIBUTING.md").write_text(
            "Before review, run `uv run ruff check .`.\n", encoding="utf-8"
        )

        required = collect_required_checks(
            self.root,
            approved_plan_checks=("uv run python -m unittest",),
            branch_protection_checks=("CI / required checks",),
        )

        self.assertTrue(required.complete)
        self.assertIn("uv run python -m unittest", required.checks)
        self.assertIn("uv run python -m unittest discover -s tests", required.checks)
        self.assertIn("uv run ruff check .", required.checks)
        self.assertIn("CI / required checks", required.checks)
        self.assertIn("approved plan", required.sources["uv run python -m unittest"])
        self.assertIn("CONTRIBUTING.md", required.sources["uv run ruff check ."])

    def test_outcome_requires_all_approvals_scope_and_check_evidence(self):
        required = collect_required_checks(
            self.root,
            approved_plan_checks=("unit", "lint"),
            branch_protection_checks=(),
        )
        passing = (
            {"command": "unit", "status": "passed", "exit_code": 0},
            {"command": "lint", "status": "passed", "exit_code": 0},
        )

        self.assertEqual(
            classify_outcome(
                "completed",
                ("spec: approve", "plan: approve"),
                required,
                passing,
            ),
            "verified",
        )
        self.assertEqual(
            classify_outcome("completed", ("spec: approve",), required, passing),
            "blocked",
        )
        self.assertEqual(
            classify_outcome(
                "completed",
                ("spec: approve", "plan: approve"),
                required,
                passing,
                scope_violations=("src/unauthorized.py",),
            ),
            "blocked",
        )
        self.assertEqual(
            classify_outcome(
                "completed",
                ("spec: approve", "plan: approve"),
                required,
                passing,
                limitations=("Remote branch protection unavailable",),
            ),
            "completed-with-limitations",
        )

    def test_incomplete_conflicting_missing_and_failed_checks_never_verify(self):
        incomplete = collect_required_checks(self.root, approved_plan_checks=("unit",))
        self.assertFalse(incomplete.complete)
        self.assertEqual(
            classify_outcome(
                "completed",
                ("spec: approve", "plan: approve"),
                incomplete,
                ({"command": "unit", "status": "passed", "exit_code": 0},),
            ),
            "completed-with-limitations",
        )

        complete = collect_required_checks(
            self.root,
            approved_plan_checks=("unit",),
            branch_protection_checks=(),
        )
        approvals = ("spec: approve", "plan: approve")
        self.assertEqual(
            classify_outcome("completed", approvals, complete, ()),
            "completed-with-limitations",
        )
        self.assertEqual(
            classify_outcome(
                "completed",
                approvals,
                complete,
                ({"command": "unit", "status": "failed", "exit_code": 2},),
            ),
            "failed",
        )
        conflict = collect_required_checks(
            self.root,
            approved_plan_checks=("unit",),
            branch_protection_checks=(),
            conflicts=("Incompatible required command",),
        )
        self.assertEqual(
            classify_outcome(
                "completed",
                approvals,
                conflict,
                ({"command": "unit", "status": "passed", "exit_code": 0},),
            ),
            "blocked",
        )

    def test_report_redacts_secrets_and_records_review_provenance_and_path_origins(self):
        token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
        path = write_delivery_report(
            self.root,
            self.run,
            request=f"Add a feature token={token}",
            authorization=self.authorization,
            route="feature -> speckit",
            approval_decisions=("spec: approve", "plan: approve"),
            pre_existing_paths=("README.md",),
            changed_paths=("src/new_feature.py",),
            scope_review="Pass; no violations.",
            required_checks=({"name": "unit", "source": "approved plan", "status": "passed", "exit_code": 0},),
            known_issues=(),
            limitations=(),
            next_action="Review the change.",
            outcome="completed-with-limitations",
            branch_protection_checks=(),
            provenance=("Copilot CLI 1.0.114: reviewed",),
            roles_skills=None,
            review_findings=("Confirm the error message meets the requirement.",),
            reviewer_type="self-review",
        )

        report = path.read_text(encoding="utf-8")
        self.assertNotIn(token, report)
        self.assertIn("[REDACTED]", report)
        self.assertIn("README.md", report)
        self.assertIn("src/new_feature.py", report)
        self.assertIn("Copilot CLI 1.0.114: reviewed", report)
        self.assertIn("Roles and skills: none/unknown", report)
        self.assertIn("self-review", report)
        self.assertIn("Confirm the error message", report)

    def test_redaction_handles_bearer_and_token_assignments(self):
        self.assertNotIn("secret-value", redact_sensitive("Bearer secret-value"))
        self.assertNotIn("secret-value", redact_sensitive("api_key=secret-value"))


if __name__ == "__main__":
    unittest.main()