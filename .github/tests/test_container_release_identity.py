"""Exercise the real publication guard against disposable local Git histories."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


GUARD = Path(__file__).resolve().parents[1] / "scripts/check-container-release-identity.sh"


class ContainerReleaseIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hub-release-guard-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q", "-b", "master")
        self.git("config", "user.name", "Synthetic fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        package = self.repo / "hub/backend/pyproject.toml"
        package.parent.mkdir(parents=True)
        package.write_text('[project]\nname = "fixture"\nversion = "0.2.182"\n')
        self.git("add", ".")
        self.git("commit", "-qm", "Synthetic release source")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.git("tag", "v0.2.182")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True)

    def guard(self, **changes):
        env = os.environ | {
            "GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": "v0.2.182",
            "GITHUB_REF": "refs/tags/v0.2.182",
            "GITHUB_SHA": self.head, "REQUESTED_VERSION": "0.2.182",
            "RELEASE_TAG_NAME": "",
        } | changes
        return subprocess.run(["bash", str(GUARD)], cwd=self.repo, env=env,
                              capture_output=True, text=True, check=False).returncode

    def test_matching_manual_tag_passes(self):
        self.assertEqual(self.guard(), 0)

    def test_matching_release_event_passes_without_manual_input(self):
        self.assertEqual(self.guard(REQUESTED_VERSION="", RELEASE_TAG_NAME="v0.2.182"), 0)

    def test_moving_branches_fail_even_with_matching_package_version(self):
        for branch in ("master", "main"):
            with self.subTest(branch=branch):
                self.assertNotEqual(self.guard(GITHUB_REF_TYPE="branch", GITHUB_REF_NAME=branch), 0)

    def test_wrong_tag_or_manual_version_or_release_metadata_fails(self):
        for change in ({"GITHUB_REF_NAME": "v0.2.183"},
                       {"GITHUB_REF_NAME": "skills-v0.2.182"},
                       {"GITHUB_REF_NAME": "0.2.182"},
                       {"GITHUB_REF": "refs/heads/master"},
                       {"GITHUB_REF": "refs/tags/v0.2.183"},
                       {"REQUESTED_VERSION": "0.2.183"},
                       {"RELEASE_TAG_NAME": "v0.2.183"}):
            with self.subTest(fields=sorted(change)):
                self.assertNotEqual(self.guard(**change), 0)

    def test_tag_source_and_head_must_equal_workflow_sha(self):
        self.assertNotEqual(self.guard(GITHUB_SHA="0" * 40), 0)
        (self.repo / "new.txt").write_text("Synthetic changed source\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Synthetic later commit with same package version")
        later = self.git("rev-parse", "HEAD").strip()
        self.assertNotEqual(self.guard(), 0)  # HEAD differs from workflow/tag source.
        self.assertNotEqual(self.guard(GITHUB_SHA=later), 0)  # Tag differs from workflow source.

    def test_annotated_tag_resolves_to_its_commit(self):
        self.git("tag", "-d", "v0.2.182")
        self.git("tag", "-a", "v0.2.182", "-m", "Synthetic annotated release")
        self.assertEqual(self.guard(), 0)


if __name__ == "__main__":
    unittest.main()
