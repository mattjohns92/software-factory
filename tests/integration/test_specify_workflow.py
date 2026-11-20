import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path


FACTORY_ROOT = Path(__file__).resolve().parents[2]
DISPOSABLE_REPOSITORY = os.environ.get("FACTORY_DISPOSABLE_REPOSITORY")
NATIVE_ACCEPTANCE_ENABLED = (
    os.environ.get("FACTORY_NATIVE_ACCEPTANCE") == "1"
    and os.environ.get("FACTORY_ACCEPTANCE_DISPOSABLE") == "1"
    and os.environ.get("FACTORY_ACCEPTANCE_HOSTED_AUTHORIZED") == "1"
    and DISPOSABLE_REPOSITORY is not None
)


@unittest.skipUnless(
    NATIVE_ACCEPTANCE_ENABLED,
    "Native acceptance requires explicit disposable-repository and hosted-use authorization flags.",
)
class SpecifyWorkflowAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = Path(DISPOSABLE_REPOSITORY).resolve()
        if cls.repository == FACTORY_ROOT or cls.repository.is_relative_to(FACTORY_ROOT):
            raise unittest.SkipTest("The acceptance repository must be separate from the factory checkout.")
        required_paths = (
            cls.repository / ".git",
            cls.repository / ".specify" / "workflows" / "runs",
            cls.repository / ".factory" / "policy.json",
            cls.repository / ".factory" / "implementation-policy.json",
            cls.repository / ".factory" / "security-probe-planning.json",
            cls.repository / ".factory" / "security-probe-implementation.json",
        )
        if any(not path.exists() for path in required_paths):
            raise unittest.SkipTest("The disposable repository or phase-specific security evidence is incomplete.")
        if not os.environ.get("FACTORY_HOSTED_PROVIDER"):
            raise unittest.SkipTest("FACTORY_HOSTED_PROVIDER must identify the configured inference service.")
        if not sys.stdin.isatty():
            raise unittest.SkipTest("Native gate approvals require an interactive terminal.")

    def test_one_authorized_feature_run_passes_both_owner_gates(self):
        request = os.environ.get("FACTORY_ACCEPTANCE_REQUEST", "Add a small acceptance feature")
        specs_before = set((self.repository / "specs").glob("*/spec.md"))
        plans_before = set((self.repository / "specs").glob("*/plan.md"))
        baseline_paths = self._git_paths()
        self.assertFalse(baseline_paths, "The disposable repository must be clean before acceptance.")
        existing_runs = self._run_ids()

        started = self._factory("run", "--type", "feature", "--authorize-hosted-agent", request)
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        run_id = self._reported_run_id(started.stdout)
        self.assertEqual(self._run_ids() - existing_runs, {run_id})
        self.assertEqual(self._status(run_id)["current_step"], "review-spec")

        spec_paths = sorted(set((self.repository / "specs").glob("*/spec.md")) - specs_before)
        self.assertTrue(spec_paths, "No generated specification was found for owner review.")
        self._request_gate_approval("spec", spec_paths)
        spec_resume = self._factory("resume", run_id, "--gate", "spec", "--decision", "approve")
        self.assertEqual(spec_resume.returncode, 0, spec_resume.stdout + spec_resume.stderr)
        self.assertEqual(self._status(run_id)["current_step"], "review-plan")

        plan_paths = sorted(set((self.repository / "specs").glob("*/plan.md")) - plans_before)
        self.assertTrue(plan_paths, "No generated plan was found for owner review.")
        self._request_gate_approval("plan", plan_paths)
        plan_resume = self._factory("resume", run_id, "--gate", "plan", "--decision", "approve")
        self.assertEqual(plan_resume.returncode, 0, plan_resume.stdout + plan_resume.stderr)
        final_status = self._status(run_id)
        self.assertEqual(final_status["run_id"], run_id)
        self.assertIn(final_status["status"], {"completed", "completed-with-limitations"})

        report_path = self.repository / ".specify" / "workflows" / "runs" / run_id / "delivery-report.md"
        report = report_path.read_text(encoding="utf-8")
        changed_paths = self._git_paths()
        for field in (
            run_id,
            request,
            "Native status:",
            "Provider:",
            "Authorized: yes",
            "spec: approve",
            "plan: approve",
            "Changed Paths",
            "Scope review:",
            "Required Checks",
            "Known Issues",
            "Limitations",
            "Next action:",
            "Third-Party Provenance",
            "Review Findings",
            "Reviewer type: self-review",
            "Roles and skills: none/unknown",
        ):
            self.assertIn(field, report)
        changed_section = report.split("### Changed Paths\n", 1)[1].split(
            "### Pre-existing Paths", 1
        )[0]
        for path in changed_paths:
            self.assertIn(path, changed_section)
        check_results = self._native_check_results(final_status)
        self.assertTrue(check_results, "Native status contains no actual check exit evidence.")
        for command, exit_code in check_results:
            self.assertIn(command, report)
            self.assertIn(f"exit code: {exit_code}", report)
        self.assertEqual(self._run_ids() - existing_runs, {run_id})

    def test_rejection_retry_preserves_run_and_completed_history(self):
        if os.environ.get("FACTORY_ACCEPTANCE_REJECTIONS") != "1":
            self.skipTest("Explicit rejection/retry acceptance authorization is required.")
        if input("Authorize a disposable rejection/retry test? Type yes: ").strip().casefold() != "yes":
            self.skipTest("Rejection/retry acceptance was not authorized.")
        request = os.environ.get("FACTORY_ACCEPTANCE_REQUEST", "Add a small retry acceptance feature")
        existing_runs = self._run_ids()
        started = self._factory("run", "--type", "feature", "--authorize-hosted-agent", request)
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        run_id = self._reported_run_id(started.stdout)
        self.assertEqual(self._status(run_id)["current_step"], "review-spec")

        before_rejection = self._status(run_id)
        completed_before_rejection = self._completed_step_ids(before_rejection)
        rejected = self._factory("resume", run_id, "--gate", "spec", "--decision", "reject")
        self.assertEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
        after_rejection = self._status(run_id)
        self.assertEqual(after_rejection["run_id"], run_id)
        self.assertEqual(after_rejection["status"], "paused")
        self.assertEqual(after_rejection["current_step"], "review-spec")
        self.assertTrue(completed_before_rejection.issubset(self._completed_step_ids(after_rejection)))

        approved = self._factory("resume", run_id, "--gate", "spec", "--decision", "approve")
        self.assertEqual(approved.returncode, 0, approved.stdout + approved.stderr)
        plan_pending = self._status(run_id)
        self.assertEqual(plan_pending["current_step"], "review-plan")
        completed_before_plan_rejection = self._completed_step_ids(plan_pending)

        plan_rejected = self._factory("resume", run_id, "--gate", "plan", "--decision", "reject")
        self.assertEqual(plan_rejected.returncode, 0, plan_rejected.stdout + plan_rejected.stderr)
        plan_still_pending = self._status(run_id)
        self.assertEqual(plan_still_pending["run_id"], run_id)
        self.assertEqual(plan_still_pending["status"], "paused")
        self.assertEqual(plan_still_pending["current_step"], "review-plan")
        self.assertTrue(
            completed_before_plan_rejection.issubset(
                self._completed_step_ids(plan_still_pending)
            )
        )

        plan_approved = self._factory("resume", run_id, "--gate", "plan", "--decision", "approve")
        self.assertEqual(plan_approved.returncode, 0, plan_approved.stdout + plan_approved.stderr)
        self.assertEqual(self._run_ids() - existing_runs, {run_id})

    def _factory(self, *arguments):
        return subprocess.run(
            ["uv", "run", "--project", str(FACTORY_ROOT), "factory", *arguments],
            cwd=self.repository,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )

    def _status(self, run_id):
        result = subprocess.run(
            ["specify", "workflow", "status", run_id, "--json"],
            cwd=self.repository,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        state = payload.get("run", payload)
        self.assertEqual(state.get("run_id", state.get("id")), run_id)
        return state

    def _run_ids(self):
        runs = self.repository / ".specify" / "workflows" / "runs"
        return {path.name for path in runs.iterdir() if path.is_dir()}

    def _completed_step_ids(self, state):
        return {
            str(step.get("step_id", step.get("id", step.get("step", ""))))
            for step in state.get("step_results", [])
            if isinstance(step, dict) and step.get("status") == "completed"
        }

    def _git_paths(self):
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=self.repository,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        paths = set()
        for entry in result.stdout.split("\0"):
            if len(entry) >= 4:
                paths.add(entry[3:])
        return paths

    def _native_check_results(self, state):
        results = []
        for step in state.get("step_results", []):
            if not isinstance(step, dict):
                continue
            command = step.get("command")
            exit_code = step.get("exit_code")
            if isinstance(command, str) and isinstance(exit_code, int):
                results.append((command, exit_code))
        return results

    def _request_gate_approval(self, gate, paths):
        print(f"\nReview the {gate} artifact before approval:")
        for path in paths:
            print(f"  {path}")
        answer = input(f"Approve the reviewed {gate} artifact? Type approve: ").strip().casefold()
        self.assertEqual(answer, "approve", f"The {gate} gate was not approved.")

    def _reported_run_id(self, output):
        match = re.search(r"^Native run: ([A-Za-z0-9][A-Za-z0-9._-]{0,127})", output, re.MULTILINE)
        self.assertIsNotNone(match, output)
        return match.group(1)


if __name__ == "__main__":
    unittest.main()