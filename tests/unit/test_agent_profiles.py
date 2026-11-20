import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPOSITORY_ROOT / "scripts" / "validate_specialist_profiles.py"
PROFILE_PATHS = (
    "factory-lead.agent.md",
    "architect.agent.md",
    "engineer.agent.md",
    "qa-engineer.agent.md",
    "code-reviewer.agent.md",
)


class SpecialistProfileValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.agent_directory = self.root / ".github" / "agents"
        self.agent_directory.mkdir(parents=True)
        for profile_path in PROFILE_PATHS:
            self.write_profile(profile_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_profile(self, profile_path, frontmatter=None):
        if frontmatter is None:
            if profile_path == "code-reviewer.agent.md":
                frontmatter = (
                    "name: Code Reviewer\n"
                    "description: Reviews approved changes.\n"
                    "strict-tools-list: true\n"
                    "tools: [read, grep, glob]"
                )
            else:
                frontmatter = (
                    f"name: {profile_path.removesuffix('.agent.md')}\n"
                    "description: Specialist profile."
                )
        path = self.agent_directory / profile_path
        path.write_text(f"---\n{frontmatter}\n---\nProfile instructions.\n", encoding="utf-8")
        return path

    def run_validator(self, root=None):
        return subprocess.run(
            [sys.executable, str(VALIDATOR), "--root", str(root or self.root)],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_repository_profiles_are_valid(self):
        result = self.run_validator(REPOSITORY_ROOT)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("valid", result.stdout.lower())

    def test_valid_fixture_passes(self):
        result = self.run_validator()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("valid", result.stdout.lower())

    def test_reports_multiple_missing_profiles(self):
        for profile_path in ("architect.agent.md", "engineer.agent.md"):
            (self.agent_directory / profile_path).unlink()

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/agents/architect.agent.md", result.stderr)
        self.assertIn(".github/agents/engineer.agent.md", result.stderr)

    def test_reports_malformed_yaml_and_non_mapping_frontmatter(self):
        self.write_profile("factory-lead.agent.md", "name: [unfinished")
        self.write_profile("architect.agent.md", "- a sequence, not a mapping")

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/agents/factory-lead.agent.md", result.stderr)
        self.assertIn(".github/agents/architect.agent.md", result.stderr)

    def test_reports_absent_and_unclosed_frontmatter(self):
        absent_path = self.agent_directory / "factory-lead.agent.md"
        absent_path.write_text("Profile without metadata.\n", encoding="utf-8")
        unclosed_path = self.agent_directory / "architect.agent.md"
        unclosed_path.write_text(
            "---\nname: Architect\ndescription: Specialist profile.\n",
            encoding="utf-8",
        )

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/agents/factory-lead.agent.md", result.stderr)
        self.assertIn(".github/agents/architect.agent.md", result.stderr)
        self.assertGreaterEqual(result.stderr.count("frontmatter"), 2)

    def test_rejects_missing_empty_and_wrong_type_required_metadata(self):
        self.write_profile(
            "factory-lead.agent.md",
            "description: Missing name.",
        )
        self.write_profile(
            "architect.agent.md",
            "name: ''\ndescription: Empty name.",
        )
        self.write_profile(
            "engineer.agent.md",
            "name: 42\ndescription: Specialist profile.",
        )
        self.write_profile(
            "qa-engineer.agent.md",
            "name: QA Engineer\ndescription: 42",
        )

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        for profile_path in PROFILE_PATHS[:4]:
            self.assertIn(f".github/agents/{profile_path}", result.stderr)

    def test_rejects_missing_and_empty_descriptions(self):
        self.write_profile("architect.agent.md", "name: Architect")
        self.write_profile(
            "engineer.agent.md",
            "name: Engineer\ndescription: ''",
        )

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/agents/architect.agent.md", result.stderr)
        self.assertIn(".github/agents/engineer.agent.md", result.stderr)
        self.assertGreaterEqual(result.stderr.count("'description'"), 2)

    def test_rejects_invalid_reviewer_strict_flag_and_additional_tools(self):
        self.write_profile(
            "code-reviewer.agent.md",
            "name: Code Reviewer\n"
            "description: Reviews approved changes.\n"
            "strict-tools-list: false\n"
            "tools: [read, grep, glob, edit]",
        )

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/agents/code-reviewer.agent.md", result.stderr)
        self.assertIn("strict-tools-list", result.stderr)
        self.assertIn("tools", result.stderr.lower())

    def test_rejects_missing_reviewer_tools(self):
        self.write_profile(
            "code-reviewer.agent.md",
            "name: Code Reviewer\n"
            "description: Reviews approved changes.\n"
            "strict-tools-list: true",
        )

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/agents/code-reviewer.agent.md", result.stderr)
        self.assertIn("tools", result.stderr.lower())

    def test_rejects_non_list_reviewer_tools(self):
        self.write_profile(
            "code-reviewer.agent.md",
            "name: Code Reviewer\n"
            "description: Reviews approved changes.\n"
            "strict-tools-list: true\n"
            "tools: read",
        )

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/agents/code-reviewer.agent.md", result.stderr)
        self.assertIn("tools", result.stderr.lower())

    def test_rejects_non_string_reviewer_tool_entries(self):
        self.write_profile(
            "code-reviewer.agent.md",
            "name: Code Reviewer\n"
            "description: Reviews approved changes.\n"
            "strict-tools-list: true\n"
            "tools: [read, 42, glob]",
        )

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/agents/code-reviewer.agent.md", result.stderr)
        self.assertIn("every entry in 'tools' must be a string", result.stderr)

    def test_rejects_incomplete_reviewer_tools(self):
        self.write_profile(
            "code-reviewer.agent.md",
            "name: Code Reviewer\n"
            "description: Reviews approved changes.\n"
            "strict-tools-list: true\n"
            "tools: [read, grep]",
        )

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/agents/code-reviewer.agent.md", result.stderr)
        self.assertIn("exactly read, grep, and glob", result.stderr)

    def test_rejects_duplicate_reviewer_tools(self):
        self.write_profile(
            "code-reviewer.agent.md",
            "name: Code Reviewer\n"
            "description: Reviews approved changes.\n"
            "strict-tools-list: true\n"
            "tools: [read, grep, glob, read]",
        )

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/agents/code-reviewer.agent.md", result.stderr)
        self.assertIn("duplicate", result.stderr.lower())

    def test_invalid_root_returns_usage_error(self):
        result = self.run_validator(self.root / "missing")

        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr)

    def test_existing_directory_without_agent_directory_returns_usage_error(self):
        empty_root = Path(self.temporary_directory.name, "empty-repository")
        empty_root.mkdir()
        result = self.run_validator(empty_root)

        self.assertEqual(result.returncode, 2)
        self.assertIn(".github/agents", result.stderr)


if __name__ == "__main__":
    unittest.main()
