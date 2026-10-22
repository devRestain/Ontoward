"""Exercise archive coverage and rejection without importing the source runtime."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

from fixture_bundle import stage


ROOT = Path(__file__).resolve().parents[3]
PACKAGER = ROOT / "Dev/packaging"


class PackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="package-tests-", dir=ROOT / "Tmp")
        cls.fixture = Path(cls.workspace.name) / "fixture"
        stage(cls.fixture)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=self.workspace.name)
        self.addCleanup(self.work.cleanup)
        self.source = Path(self.work.name) / "submission"
        shutil.copytree(self.fixture, self.source)
        self.output = Path(self.work.name) / "submission.zip"

    def package(self):
        return subprocess.run([
            sys.executable, "-B", "-c",
            "from pathlib import Path; import sys; "
            "sys.path.insert(0, sys.argv[1]); from package_submission import main; "
            "main(Path(sys.argv[2]), Path(sys.argv[3]))",
            str(PACKAGER), str(self.source), str(self.output),
        ], capture_output=True, text=True)

    def test_current_modules_prompts_and_only_active_assets(self):
        # A new package module must be included without editing the packager.
        (self.source / "workflow/new_runtime.py").write_text("from .rules.dd import requirements\n")
        result = self.package()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        with ZipFile(self.output) as archive:
            names = set(archive.namelist())
            python = {path.relative_to(self.source).as_posix() for path in self.source.rglob("*.py")}
            self.assertLessEqual(python, names)
            prompts = json.loads((self.source / "config/prompts.json").read_text())
            self.assertLessEqual({part for parts in prompts.values() for part in parts}, names)
            manifest = json.loads((self.source / "knowledge/manifest.json").read_text())
            assets = {"knowledge/" + manifest[role]["path"] for role in
                      ("schema", "vocabulary", "clinical", "questions", "guidelines")}
            self.assertEqual({name for name in names if name.startswith("knowledge/")
                              and name.endswith((".ttl", ".json"))}, assets | {"knowledge/manifest.json"})
            self.assertFalse(any(Path(name).name in {"AGENTS.md", "README.md", "PROJECT_STATE.md"}
                                 or "__pycache__" in name for name in names))
            self.assertEqual(set(report["file_sha256"]), names)
            for name, digest in report["file_sha256"].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
        self.assertEqual(report["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(report["knowledge_build_id"], manifest["build_id"])

    def test_missing_import_preserves_previous_archive(self):
        (self.source / "workflow/rules/dd.py").unlink()
        self.output.write_bytes(b"previous accepted archive")
        result = self.package()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing runtime module: workflow.rules.dd", result.stderr)
        self.assertEqual(self.output.read_bytes(), b"previous accepted archive")

    def test_missing_prompt_fails(self):
        (self.source / "config/prompts/plan_disposition.txt").unlink()
        result = self.package()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing runtime files", result.stderr)

    def test_missing_parent_package_fails(self):
        nested = self.source / "workflow/extension/nested"
        nested.mkdir(parents=True)
        (nested / "__init__.py").write_text("")
        result = self.package()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing runtime package: workflow.extension", result.stderr)

    def test_modified_knowledge_fails(self):
        manifest = json.loads((self.source / "knowledge/manifest.json").read_text())
        path = self.source / "knowledge" / manifest["clinical"]["path"]
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
        result = self.package()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Knowledge digest mismatch", result.stderr)

    def test_unapproved_file_and_symlink_fail(self):
        extra = self.source / "private-key.txt"
        extra.write_text("synthetic test value")
        result = self.package()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unapproved submission file", result.stderr)
        extra.unlink()
        extra.symlink_to(self.source / "run.py")
        result = self.package()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Symlink is not allowed", result.stderr)


if __name__ == "__main__":
    unittest.main()
