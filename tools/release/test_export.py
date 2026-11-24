import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from export_source import classification_findings, commit_snapshot, init_public_repository, main, prepare_public_base
from privacy import audit_file, public_bytes


class ExportTest(unittest.TestCase):
    def test_every_tracked_file_must_be_published_or_excluded(self):
        excluded = [{"pattern": "docs/*", "reason": "internal"}]
        self.assertEqual(classification_findings(["a.py", "b.py", "docs/x.md"], {"a.py"}, excluded), [{"file": "b.py", "kind": "unclassified"}])
        self.assertEqual(classification_findings(["docs/x.md"], {"docs/x.md"}, excluded), [{"file": "docs/x.md", "kind": "published-and-excluded"}])
        with self.assertRaisesRegex(ValueError, "reason"):
            classification_findings(["a.py"], {"a.py"}, [{"pattern": "b.py", "reason": ""}])

    def test_public_checkout_without_exclusions_requires_every_tracked_file_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            isolated = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            isolated.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
            subprocess.check_call(["git", "init", "-q", "-b", "main", str(root)], env=isolated)
            (root / "README.md").write_text("Public source\n")
            (root / "release-files.json").write_text(json.dumps({"files": ["README.md", "release-files.json"]}))
            subprocess.check_call(["git", "-C", str(root), "add", "--all"], env=isolated)
            with patch("export_source.ROOT", root), patch("sys.argv", ["export"]):
                main()
                (root / "extra.txt").write_text("not listed\n")
                subprocess.check_call(["git", "-C", str(root), "add", "extra.txt"], env=isolated)
                with self.assertRaises(SystemExit):
                    main()

    def test_public_base_export_requires_private_terms_and_committed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "source"
            isolated = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            isolated.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
            subprocess.check_call(["git", "init", "-q", "-b", "main", str(root)], env=isolated)
            (root / "README.md").write_text("Public source\n")
            (root / "release-files.json").write_text(json.dumps({"files": ["README.md", "release-files.json"]}))
            subprocess.check_call(["git", "-C", str(root), "add", "--all"], env=isolated)
            subprocess.check_call(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "seed"], env=isolated)
            terms = base / "terms.txt"
            argv = ["export", str(base / "out"), "--public-base", "https://example.invalid/repo.git"]
            with patch("export_source.ROOT", root), patch("export_source.DEFAULT_PRIVATE_TERMS", base / "missing.txt"), patch("sys.argv", argv):
                with self.assertRaisesRegex(SystemExit, "private terms"):
                    main()
            terms.write_text("someone\n")
            (root / "README.md").write_text("Edited but not committed\n")
            with patch("export_source.ROOT", root), patch("export_source.DEFAULT_PRIVATE_TERMS", terms), patch("sys.argv", argv):
                with self.assertRaisesRegex(SystemExit, "uncommitted"):
                    main()
            self.assertFalse((base / "out").exists())

    def test_public_markdown_discards_only_note_frontmatter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("---\ntitle: example\ntype: note\npermalink: internal/example\n---\n\n# Public documentation\n")
            self.assertEqual(public_bytes(root, "README.md"), b"# Public documentation\n")
            self.assertEqual(audit_file(root, "README.md"), [])
            (root / "README.md").write_text("# Public\n\nmemory://internal-note")
            self.assertEqual(audit_file(root, "README.md")[0]["kind"], "memory-content")

    def test_export_report_preserves_calver_name_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            source.mkdir()
            (source / "README.md").write_text("Public source\n")
            (source / "release-files.json").write_text(json.dumps({"files": ["README.md"]}))
            destination = base / "scena-v26.9.6-beta"
            report = base / "scena-v26.9.6-beta.sha256.json"
            with patch("export_source.ROOT", source), patch("sys.argv", ["export", "--draft", str(destination)]):
                report.write_text("existing evidence")
                with self.assertRaisesRegex(SystemExit, "Hash report already exists"):
                    main()
                self.assertFalse(destination.exists())
                self.assertEqual(report.read_text(), "existing evidence")
                report.unlink()
                main()
            self.assertEqual(list(json.loads(report.read_text())), ["README.md"])
            self.assertFalse((base / "scena-v26.9.sha256.json").exists())

    def test_new_git_history_does_not_inherit_committer_or_remotes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("Public source\n")
            metadata = {"author": "Example", "commitEmail": "example@users.noreply.github.com", "version": "26.9.6-beta"}
            with patch.dict(os.environ, {"GIT_AUTHOR_EMAIL": "private@example.invalid", "GIT_COMMITTER_EMAIL": "private@example.invalid", "GIT_COMMITTER_NAME": "Private"}):
                init_public_repository(root, metadata)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
            self.assertEqual(git("rev-list", "--count", "HEAD"), "1")
            self.assertEqual(git("show", "-s", "--format=%an|%ae|%cn|%ce"), "Example|example@users.noreply.github.com|Example|example@users.noreply.github.com")
            self.assertEqual(git("remote"), "")
            self.assertEqual(git("ls-files"), "README.md")

    def test_snapshot_appends_to_public_base_without_rewriting(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            isolated = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            isolated.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
            def git(cwd, *args):
                return subprocess.check_output(["git", "-C", str(cwd), *args], text=True, env=isolated).strip()
            seed = base / "seed"
            seed.mkdir()
            git(seed, "init", "-q", "-b", "main")
            (seed / "LICENSE").write_text("MIT\n")
            (seed / "stale.txt").write_text("old\n")
            git(seed, "add", "--all")
            git(seed, "-c", "user.name=Seed", "-c", "user.email=seed@example.invalid", "commit", "-q", "-m", "seed")
            public = base / "public.git"
            subprocess.check_call(["git", "clone", "-q", "--bare", str(seed), str(public)], env=isolated)
            base_sha = git(public, "rev-parse", "main")
            destination = base / "export"
            self.assertEqual(prepare_public_base(destination, str(public)), base_sha)
            self.assertEqual(sorted(path.name for path in destination.iterdir()), [".git"])
            (destination / "LICENSE").write_text("MIT\n")
            (destination / "src").mkdir()
            (destination / "src" / "app.py").write_text("print('public')\n")
            metadata = {"author": "Example", "commitEmail": "example@users.noreply.github.com", "version": "26.11.24"}
            with patch.dict(os.environ, {"GIT_AUTHOR_EMAIL": "private@example.invalid", "GIT_COMMITTER_NAME": "Private"}):
                commit_snapshot(destination, metadata)
            self.assertEqual(git(destination, "rev-parse", "HEAD~1"), base_sha)
            self.assertEqual(git(destination, "ls-files").splitlines(), ["LICENSE", "src/app.py"])
            self.assertEqual(git(destination, "show", "-s", "--format=%an|%ae|%cn|%ce|%s"), "Example|example@users.noreply.github.com|Example|example@users.noreply.github.com|Source snapshot v26.11.24")
            self.assertEqual(git(destination, "remote", "-v").split()[1], str(public))


if __name__ == "__main__":
    unittest.main()
