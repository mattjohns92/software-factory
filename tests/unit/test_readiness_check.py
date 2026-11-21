import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import check_factory_readiness as readiness  # noqa: E402


PROFILE_PATHS = (
    "factory-lead.agent.md",
    "architect.agent.md",
    "engineer.agent.md",
    "qa-engineer.agent.md",
    "code-reviewer.agent.md",
)
SECRET_POLICY_VALUE = "SECRET-POLICY-LOCATION-12345"
INTEGRATION_OK = {
    "status": "ok",
    "default_integration": "copilot",
    "installed_integrations": ["copilot"],
    "missing_managed_files": 0,
    "modified_managed_files": 0,
    "invalid_manifest_paths": 0,
    "unchecked_manifests": 0,
    "findings": [],
}


class FakeRunner:
    def __init__(self, version_output="specify 1.0.6\n", integration=None):
        self.version_output = version_output
        self.integration = INTEGRATION_OK if integration is None else integration
        self.version_returncode = 0
        self.integration_returncode = 0
        self.version_error = None
        self.integration_error = None
        self.calls = []

    def __call__(self, arguments, cwd=None, timeout=None):
        self.calls.append((list(arguments), timeout))
        if arguments[1:] == ["--version"]:
            if self.version_error:
                raise self.version_error
            return subprocess.CompletedProcess(
                arguments, self.version_returncode, self.version_output, ""
            )
        if arguments[1:] == ["integration", "status", "--json"]:
            if self.integration_error:
                raise self.integration_error
            return subprocess.CompletedProcess(
                arguments, self.integration_returncode, json.dumps(self.integration), ""
            )
        raise AssertionError(f"unexpected command: {arguments}")


def fake_which(*names):
    present = set(names)
    return lambda name: f"/bin/{name}" if name in present else None


class ReadinessCheckTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "checkout"
        self.root.mkdir()
        self.policy_file = Path(self.temporary_directory.name) / "policy.json"
        self.policy_file.write_text("{}", encoding="utf-8")
        self.build_fixture()
        self.runner = FakeRunner()
        self.which = fake_which("specify", "copilot")
        self.environment = {
            readiness.POLICY_VARIABLE: str(self.policy_file),
            "SECRET_TOKEN": SECRET_POLICY_VALUE,
        }

    # fixture helpers
    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_profile(self, name, frontmatter=None):
        if frontmatter is None:
            if name == "code-reviewer.agent.md":
                frontmatter = (
                    "name: Code Reviewer\ndescription: Reviews.\n"
                    "strict-tools-list: true\ntools: [read, grep, glob]"
                )
            else:
                frontmatter = f"name: {name}\ndescription: Specialist."
        self.write(f".github/agents/{name}", f"---\n{frontmatter}\n---\nBody.\n")

    def build_fixture(self):
        for relative in readiness.SPECKIT_FILES:
            self.write(relative, "content\n")
        (self.root / "specs" / "001-x").mkdir(parents=True)
        self.write(".specify/feature.json", json.dumps({"feature_directory": "specs\\001-x"}))
        for name in PROFILE_PATHS:
            self.write_profile(name)
        self.write(
            ".github/skills/factory-handoff/SKILL.md",
            "---\nname: factory-handoff\ndescription: Handoffs.\n---\nBody\n",
        )
        self.write(
            ".github/hooks/factory-policy.json",
            json.dumps(
                {
                    "version": 1,
                    "hooks": {
                        "preToolUse": [
                            {
                                "type": "command",
                                "powershell": '& ".\\scripts\\factory_pre_tool_use.ps1"',
                                "cwd": ".",
                            }
                        ]
                    },
                }
            ),
        )
        self.write(
            "scripts/factory_pre_tool_use.ps1",
            "$env:FACTORY_POLICY_PATH\n$env:FACTORY_REPOSITORY_ROOT\n",
        )

    def run_main(self, argv=None):
        stream = io.StringIO()
        code = readiness.main(
            ["--root", str(self.root)] if argv is None else argv,
            runner=self.runner,
            environment=self.environment,
            which=self.which,
            stdout=stream,
        )
        return code, stream.getvalue()

    def results(self):
        return {
            r.id: r
            for r in readiness.run_checks(
                self.root, self.runner, self.environment, self.which
            )
        }

    def assert_status(self, check_id, status):
        self.assertEqual(self.results()[check_id].status, status)

    def snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }

    # overall
    def test_ready_with_limitations(self):
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertIn("Verdict: ready with limitations", output)
        self.assert_status("tool-specify", readiness.PASS)
        self.assert_status("speckit-config", readiness.PASS)
        self.assert_status("specialist-profiles", readiness.PASS)

    def test_verdict_is_never_plain_ready(self):
        _, output = self.run_main()
        lines = output.splitlines()
        self.assertNotIn("Verdict: ready", lines)
        self.assertIn("Verdict: ready with limitations", lines)
        self.assertTrue(lines[-1].startswith("Limitations:"))

    def test_unverifiable_items_always_not_verified(self):
        result = self.results()["unverifiable"]
        self.assertEqual(result.status, readiness.NOT_VERIFIED)
        for word in ("authentication", "live dispatch", "sandbox"):
            self.assertIn(word, result.finding)

    # spec kit
    def test_each_missing_speckit_file_fails(self):
        for relative in readiness.SPECKIT_FILES + (".specify/feature.json",):
            with self.subTest(relative=relative):
                path = self.root / relative
                content = path.read_bytes()
                path.unlink()
                result = self.results()["speckit-config"]
                self.assertEqual(result.status, readiness.FAIL)
                self.assertIn(relative, result.finding)
                path.write_bytes(content)

    def test_invalid_feature_pointer_fails(self):
        self.write(".specify/feature.json", json.dumps({"feature_directory": "specs/nope"}))
        result = self.results()["speckit-config"]
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn("feature_directory", result.finding)
        self.write(".specify/feature.json", "{not json")
        self.assert_status("speckit-config", readiness.FAIL)

    def test_integration_status_findings_fail(self):
        self.runner.integration = dict(INTEGRATION_OK, missing_managed_files=2)
        self.assert_status("speckit-config", readiness.FAIL)
        self.runner.integration = dict(INTEGRATION_OK, installed_integrations=[])
        self.assert_status("speckit-config", readiness.FAIL)
        self.runner.integration = dict(INTEGRATION_OK, findings=["x"])
        self.assert_status("speckit-config", readiness.FAIL)
        self.runner.integration = dict(INTEGRATION_OK, status="error")
        self.assert_status("speckit-config", readiness.FAIL)

    def test_integration_status_nonzero_fails(self):
        self.runner.integration_returncode = 3
        self.assert_status("speckit-config", readiness.FAIL)

    # profiles
    def test_invalid_profile_fails(self):
        self.write_profile("architect.agent.md", "description: no name")
        result = self.results()["specialist-profiles"]
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn(".github/agents/architect.agent.md", result.finding)

    def test_invalid_reviewer_tools_fail(self):
        self.write_profile(
            "code-reviewer.agent.md",
            "name: R\ndescription: d\nstrict-tools-list: true\ntools: [read, grep, glob, edit]",
        )
        result = self.results()["specialist-profiles"]
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn("code-reviewer", result.finding)

    def test_missing_handoff_skill_fails(self):
        (self.root / ".github/skills/factory-handoff/SKILL.md").unlink()
        result = self.results()["specialist-profiles"]
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn("factory-handoff", result.finding)

    # specify
    def test_missing_specify_fails(self):
        self.which = fake_which("copilot")
        self.assert_status("tool-specify", readiness.FAIL)
        self.assertEqual(self.runner.calls, [])

    def test_specify_version_classification(self):
        cases = (
            ("specify 1.0.6\n", readiness.PASS),
            ("specify 1.0.5\n", readiness.NOT_VERIFIED),
            ("specify 2.3.0\n", readiness.NOT_VERIFIED),
            ("specify unknown\n", readiness.FAIL),
        )
        for output, status in cases:
            with self.subTest(output=output):
                self.runner.version_output = output
                self.assert_status("tool-specify", status)

    def test_known_incompatible_version_fails(self):
        with mock.patch.dict(
            readiness.COMPATIBILITY["specify"], {"incompatible": {"0.9.0"}}
        ):
            self.runner.version_output = "specify 0.9.0\n"
            result = self.results()["tool-specify"]
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn("incompatible", result.finding)

    def test_newer_version_is_never_pass(self):
        self.runner.version_output = "specify 1.0.7\n"
        result = self.results()["tool-specify"]
        self.assertEqual(result.status, readiness.NOT_VERIFIED)
        self.assertNotIn("(supported)", result.finding)

    def test_specify_timeout_and_nonzero_fail(self):
        self.runner.version_error = subprocess.TimeoutExpired(["specify"], 15)
        self.assert_status("tool-specify", readiness.FAIL)
        self.runner.version_error = None
        self.runner.version_returncode = 1
        self.assert_status("tool-specify", readiness.FAIL)

    def test_command_uses_fixed_queries_and_timeout(self):
        self.results()
        commands = [call[0][1:] for call in self.runner.calls]
        self.assertEqual(commands, [["--version"], ["integration", "status", "--json"]])
        for _, timeout in self.runner.calls:
            self.assertEqual(timeout, 15)

    def test_empty_path_lookup_finds_nothing(self):
        which = readiness.make_path_lookup({"PATH": ""})
        self.assertIsNone(which("copilot"))
        self.assertIsNone(which("copilot.ps1"))
        self.which = which
        self.assert_status("tool-copilot", readiness.FAIL)

    def test_default_runner_uses_list_args_no_shell_and_timeout(self):
        with mock.patch.object(readiness.subprocess, "run") as run:
            readiness.default_runner(("specify", "--version"), cwd=self.root, timeout=15)
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertIsInstance(args[0], list)
        self.assertEqual(args[0], ["specify", "--version"])
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], 15)

    # version parsing
    def test_non_exact_versions_are_never_pass(self):
        for output in ("specify 1.0.6.1\n", "specify 1.0.6-rc1\n", "1.0.6+build\n", "1.0\n"):
            with self.subTest(output=output):
                self.runner.version_output = output
                result = self.results()["tool-specify"]
                self.assertEqual(result.status, readiness.NOT_VERIFIED)
        self.runner.version_output = "1.0.6\n"
        self.assert_status("tool-specify", readiness.PASS)

    # integration status types
    def test_integration_status_type_strictness(self):
        bad = (
            dict(INTEGRATION_OK, installed_integrations="copilot"),
            dict(INTEGRATION_OK, missing_managed_files=False),
            dict(INTEGRATION_OK, unchecked_manifests=0.0),
            dict(INTEGRATION_OK, modified_managed_files="0"),
            ["not", "a", "dict"],
            "text",
        )
        for payload in bad:
            with self.subTest(payload=payload):
                self.runner.integration = payload
                self.assert_status("speckit-config", readiness.FAIL)

    # feature.json
    def test_feature_json_non_dict_fails(self):
        self.write(".specify/feature.json", json.dumps(["specs/001-x"]))
        self.assert_status("speckit-config", readiness.FAIL)

    def test_feature_directory_outside_root_fails(self):
        (Path(self.temporary_directory.name) / "outside").mkdir()
        for value in ("../outside", str(Path(self.temporary_directory.name) / "outside")):
            with self.subTest(value=value):
                self.write(".specify/feature.json", json.dumps({"feature_directory": value}))
                result = self.results()["speckit-config"]
                self.assertEqual(result.status, readiness.FAIL)
                self.assertIn("outside the repository", result.finding)

    def test_feature_json_is_file_oserror_handled(self):
        original = Path.is_file

        def flaky(path):
            if path.name == "feature.json":
                raise OSError("boom")
            return original(path)

        with mock.patch.object(Path, "is_file", flaky):
            result = self.results()["speckit-config"]
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn("feature.json", result.finding)

    # hook containment and coverage
    def write_hook(self, **entry):
        entry.setdefault("type", "command")
        self.write(
            ".github/hooks/factory-policy.json",
            json.dumps({"version": 1, "hooks": {"preToolUse": [entry]}}),
        )

    def test_hook_script_outside_root_fails(self):
        outside = Path(self.temporary_directory.name) / "evil.ps1"
        outside.write_text("x", encoding="utf-8")
        cases = (
            {"powershell": "& '..\\evil.ps1'", "cwd": "."},
            {"powershell": f"& '{outside}'", "cwd": "."},
            {"bash": "../evil.ps1"},
        )
        for entry in cases:
            with self.subTest(entry=entry):
                self.write_hook(**entry)
                result = self.results()["interactive-hooks"]
                self.assertEqual(result.status, readiness.FAIL)
                self.assertIn("outside the repository", result.finding)
                self.assertIn(".github/hooks/factory-policy.json", result.finding)

    def test_hook_cwd_outside_root_fails(self):
        self.write_hook(powershell="& 'scripts/factory_pre_tool_use.ps1'", cwd="..")
        result = self.results()["interactive-hooks"]
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn("cwd", result.finding)

    def test_hook_without_recognizable_script_is_not_verified_with_finding(self):
        self.write_hook(bash="echo hello")
        result = self.results()["interactive-hooks"]
        self.assertEqual(result.status, readiness.NOT_VERIFIED)
        self.assertIn("names no recognizable script", result.finding)
        self.assertIn("hooks.preToolUse.bash", result.finding)

    def test_hook_script_path_with_spaces_and_all_keys_checked(self):
        self.write("scripts/with space/hook.ps1", "$env:FACTORY_POLICY_PATH\n")
        self.write_hook(powershell="& 'scripts/with space/hook.ps1'", windows="missing/other.ps1")
        result = self.results()["interactive-hooks"]
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn("missing/other.ps1", result.finding)
        self.assertNotIn("with space", result.finding)
        self.write_hook(powershell="& 'scripts/with space/hook.ps1'")
        self.assert_status("interactive-hooks", readiness.NOT_VERIFIED)
        self.environment = {}
        self.assert_status("interactive-hooks", readiness.FAIL)

    def test_unreadable_settings_reported_and_not_disabled(self):
        self.environment = {}
        for content in ("{broken", json.dumps(["disableAllHooks"])):
            with self.subTest(content=content):
                self.write(".github/copilot/settings.local.json", content)
                result = self.results()["interactive-hooks"]
                # not treated as disabled: missing policy still fails
                self.assertEqual(result.status, readiness.FAIL)
        self.environment = {readiness.POLICY_VARIABLE: str(self.policy_file)}
        result = self.results()["interactive-hooks"]
        self.assertEqual(result.status, readiness.NOT_VERIFIED)
        self.assertIn("settings.local.json unreadable", result.finding)

    def test_disable_all_hooks_non_true_is_not_disabled(self):
        self.environment = {}
        for value in (False, "true", 1, None):
            with self.subTest(value=value):
                self.write(
                    ".github/copilot/settings.local.json", json.dumps({"disableAllHooks": value})
                )
                self.assert_status("interactive-hooks", readiness.FAIL)

    # exception handling
    def test_unexpected_exception_in_check_becomes_fail_and_report_renders(self):
        with mock.patch.object(readiness, "check_policy", side_effect=RuntimeError("x")):
            code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] runner-policy:", output)
        self.assertIn("Verdict: not ready", output)
        self.assertIn("[NOT VERIFIED] unverifiable:", output)

    def test_exception_in_specify_check_becomes_fail(self):
        with mock.patch.object(readiness, "check_specify", side_effect=ValueError("x")):
            code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] tool-specify:", output)
        self.assertIn("specify integration status: not queried", output)

    def test_pyyaml_missing_fails(self):
        fake = mock.Mock()
        fake.import_module.side_effect = ModuleNotFoundError("No module named 'yaml'", name="yaml")
        with mock.patch.object(readiness, "importlib", fake):
            result = self.results()["specialist-profiles"]
            code, output = self.run_main()
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn("PyYAML", result.finding)
        self.assertIn("uv sync --group validation", result.next_step)
        self.assertEqual(code, 1)

    def test_missing_validator_fails_naming_validator(self):
        fake = mock.Mock()
        fake.import_module.side_effect = ModuleNotFoundError(
            "No module named 'validate_specialist_profiles'", name="validate_specialist_profiles"
        )
        with mock.patch.object(readiness, "importlib", fake):
            result = self.results()["specialist-profiles"]
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn("validate_specialist_profiles.py", result.finding)
        self.assertNotIn("PyYAML", result.finding)

    def test_missing_private_frontmatter_fails(self):
        class Validator:
            @staticmethod
            def validate_profiles(root):
                return []

        fake = mock.Mock()
        fake.import_module.return_value = Validator
        with mock.patch.object(readiness, "importlib", fake):
            result = self.results()["specialist-profiles"]
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn("validate_specialist_profiles.py", result.finding)

    # copilot
    def test_copilot_missing_fails(self):
        self.which = fake_which("specify")
        self.assert_status("tool-copilot", readiness.FAIL)

    def test_copilot_present_is_not_verified_and_never_executed(self):
        self.assert_status("tool-copilot", readiness.NOT_VERIFIED)
        for arguments, _ in self.runner.calls:
            self.assertNotIn("copilot", " ".join(arguments).lower())

    def test_copilot_ps1_found_on_path(self):
        bin_dir = Path(self.temporary_directory.name) / "bin"
        bin_dir.mkdir()
        (bin_dir / "copilot.ps1").write_text("# stub", encoding="utf-8")
        which = readiness.make_path_lookup({"PATH": str(bin_dir)})
        self.which = which
        self.assertIsNone(which("specify"))
        self.assert_status("tool-copilot", readiness.NOT_VERIFIED)

    # hooks
    def test_no_hooks_passes(self):
        (self.root / ".github/hooks/factory-policy.json").unlink()
        self.assert_status("interactive-hooks", readiness.PASS)

    def test_malformed_hook_json_fails(self):
        self.write(".github/hooks/factory-policy.json", "{broken")
        self.assert_status("interactive-hooks", readiness.FAIL)

    def test_hook_without_hooks_structure_fails(self):
        self.write(".github/hooks/factory-policy.json", json.dumps({"version": 1}))
        self.assert_status("interactive-hooks", readiness.FAIL)

    def test_hook_missing_script_fails(self):
        (self.root / "scripts/factory_pre_tool_use.ps1").unlink()
        result = self.results()["interactive-hooks"]
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn("factory_pre_tool_use.ps1", result.finding)

    def test_active_hook_without_policy_fails_scoped_to_environment(self):
        self.environment = {}
        result = self.results()["interactive-hooks"]
        self.assertEqual(result.status, readiness.FAIL)
        self.assertIn("current shell/launching environment", result.finding)
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("Verdict: not ready", output)

    def test_policy_path_pointing_to_missing_file_fails(self):
        self.environment = {readiness.POLICY_VARIABLE: str(self.root / "absent.json")}
        self.assert_status("interactive-hooks", readiness.FAIL)

    def test_locally_disabled_hooks_not_verified(self):
        self.environment = {}
        self.write(".github/copilot/settings.local.json", json.dumps({"disableAllHooks": True}))
        result = self.results()["interactive-hooks"]
        self.assertEqual(result.status, readiness.NOT_VERIFIED)
        self.assertIn("locally disabled", result.finding)
        code, _ = self.run_main()
        self.assertEqual(code, 0)

    def test_policy_available_not_verified(self):
        self.assert_status("interactive-hooks", readiness.NOT_VERIFIED)

    # policy / git
    def test_missing_factory_policy_alone_is_not_a_failure(self):
        self.assertFalse((self.root / ".factory/policy.json").exists())
        result = self.results()["runner-policy"]
        self.assertEqual(result.status, readiness.INFO)
        code, _ = self.run_main()
        self.assertEqual(code, 0)

    # aggregation and exit codes
    def test_multiple_failures_reported_together(self):
        self.which = fake_which()
        (self.root / ".specify/memory/constitution.md").unlink()
        self.write_profile("architect.agent.md", "description: no name")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        for check_id in ("tool-specify", "tool-copilot", "speckit-config", "specialist-profiles"):
            self.assertIn(f"[FAIL] {check_id}:", output)
        self.assertIn("    expected:", output)
        self.assertIn("    next step:", output)

    def test_invalid_root_is_usage_error(self):
        code, _ = self.run_main(["--root", str(self.root / "missing")])
        self.assertEqual(code, 2)

    def test_unknown_option_is_usage_error(self):
        with mock.patch("sys.stderr", new=io.StringIO()):
            code, _ = self.run_main(["--bogus"])
        self.assertEqual(code, 2)

    # safety
    def test_run_leaves_fixture_unchanged(self):
        before = self.snapshot()
        self.run_main()
        self.assertEqual(self.snapshot(), before)

    def test_environment_values_never_printed(self):
        _, output = self.run_main()
        self.assertNotIn(SECRET_POLICY_VALUE, output)
        self.assertNotIn(str(self.policy_file), output)

    def test_injected_runner_is_only_subprocess_path(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("subprocess.run used")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("Popen used")):
            code, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(len(self.runner.calls), 2)


if __name__ == "__main__":
    unittest.main()
