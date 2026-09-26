import ast
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from should_run_checks import (
    DEFAULT_CONFIG,
    Config,
    Result,
    evaluate_changes,
    parse_config,
    run,
    should_run_checks,
    validate_config,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = {"skipExtensions": [".md"], "skipDirectories": ["mockups"], "alwaysRunFiles": []}
CONFIG = validate_config(DATA)
TOML = '''# ドキュメントだけなら省略
skipExtensions = [".md"] # Markdown
skipDirectories = ["mockups"]
alwaysRunFiles = []
'''


class ConfigTests(unittest.TestCase):
    def test_toml_and_json_have_same_rules(self):
        for filename in ("rules.toml", "RULES.TOML"):
            with self.subTest(filename=filename):
                self.assertEqual(parse_config(TOML, filename), CONFIG)
        self.assertEqual(parse_config(json.dumps(DATA), "rules.json"), CONFIG)

    def test_toml_multiline_arrays_and_quoted_paths(self):
        config = parse_config('''skipExtensions = [
          '.md', # comment
        ]
        skipDirectories = []
        alwaysRunFiles = ['docs/a#b.md', "docs/a: b.md"]
        ''', "rules.toml")
        self.assertTrue(should_run_checks(["docs/a#b.md"], config))
        self.assertTrue(should_run_checks(["docs/a: b.md"], config))

    def test_invalid_documents(self):
        sources = (
            "", "skipExtensions = [", TOML + "skipExtensions = []\n",
            TOML.replace('[".md"]', 'false'),
            TOML.replace('[".md"]', '[1]'),
            TOML.replace('[".md"]', '".md"'),
            TOML + "unknown = []\n",
        )
        for source in sources:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    parse_config(source, "rules.toml")
        with self.assertRaises(ValueError):
            parse_config('{"skipExtensions": [], "skipExtensions": [".md"]}', "rules.json")

    def test_yaml_and_unknown_formats_are_rejected(self):
        for filename in ("rules.yml", "rules.yaml", "rules.txt", "rules"):
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    parse_config(TOML, filename)

    def test_invalid_config_types(self):
        for value in (None, [], "md", {**DATA, "skipExtension": [".md"]}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_config(value)
        for key in DATA:
            for value in (None, "*.md", [None], [""], [False]):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        validate_config({**DATA, key: value})
            with self.assertRaises(ValueError):
                validate_config({name: value for name, value in DATA.items() if name != key})

    def test_invalid_extensions_and_paths(self):
        for value in ("md", ".", "*.md", ".m/d", ".m\\d"):
            with self.subTest(extension=value):
                with self.assertRaises(ValueError):
                    validate_config({**DATA, "skipExtensions": [value]})
        for key in ("skipDirectories", "alwaysRunFiles"):
            for value in ("./docs", "docs/", "/docs", "docs//a", "../docs", "**/*.md", "a\\b"):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        validate_config({**DATA, key: [value]})

    def test_only_skipped_paths(self):
        for paths in (
            [], ["README.md"], ["AGENTS.md", "docs/generated/api.md", ".agents/a/SKILL.md"],
            [".hidden.md", "mockups/nested/app.js", "docs/a file\nwith newline.md"],
        ):
            with self.subTest(paths=paths):
                self.assertFalse(should_run_checks(paths, CONFIG))

    def test_mixed_paths(self):
        for path in (
            "src/app.ts", "package.json", ".github/ci-skip-rules.toml", "docs/chart.svg",
            "mockups-other/index.html", "src/mockups/app.js", "README.MD", "docs/a.mdx",
        ):
            with self.subTest(path=path):
                self.assertTrue(should_run_checks(["README.md", path, "mockups/app.js"], CONFIG))

    def test_custom_rules(self):
        paths = ["notes.txt", "design/drafts/nested/screen.svg"]
        self.assertTrue(should_run_checks(paths, CONFIG))
        customized = Config((".md", ".txt"), ("mockups", "design/drafts"), ())
        self.assertFalse(should_run_checks(paths, customized))

    def test_explicit_files_override_both_skip_rules(self):
        customized = Config((".md",), ("mockups",), ("docs/api.md", "mockups/important.md"))
        for path in customized.always_run_files:
            self.assertTrue(should_run_checks([path], customized))
            self.assertFalse(should_run_checks(["other/" + path], customized))

    def test_empty_rules_run_all_changes(self):
        self.assertTrue(should_run_checks(["README.md"], validate_config({key: [] for key in DATA})))

    def test_uses_only_standard_library(self):
        tree = ast.parse((ROOT / "should_run_checks.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module]
            else:
                continue
            for name in names:
                self.assertIn(name.split(".")[0], sys.stdlib_module_names)


class GitAndActionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="should-run-checks-")
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / "repository with spaces"
        self.workspace.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "CI fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write("src/app.py")
        self.write("README.md")
        self.base = self.commit()

    def git(self, *args):
        result = subprocess.run(
            ["git", "-C", str(self.workspace), *args],
            check=True, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
        )
        return result.stdout.strip()

    def write(self, path, content="fixture\n"):
        target = self.workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self):
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def evaluate(self, head, event_name="push", base=None):
        base = self.base if base is None else base
        event = {"before": base, "after": head} if event_name == "push" else {
            "pull_request": {"base": {"sha": base}, "head": {"sha": head}}
        }
        return evaluate_changes(self.workspace, event_name, event, CONFIG)

    def test_docs_code_and_empty_diff_for_push_and_pr(self):
        self.write("docs/a file.md")
        docs = self.commit()
        self.write("src/a file.py")
        code = self.commit()
        for event in ("push", "pull_request"):
            self.assertFalse(self.evaluate(docs, event).run_checks)
            self.assertTrue(self.evaluate(code, event).run_checks)
            self.assertEqual(self.evaluate(code, event, code).reason, "no-changes")

    @unittest.skipIf(os.name == "nt", "Windowsのファイル名に改行は使用できない")
    def test_newlines_in_paths(self):
        self.write("docs/file\nname.md")
        self.assertFalse(self.evaluate(self.commit()).run_checks)
        self.write("src/file\nname.py")
        self.assertTrue(self.evaluate(self.commit()).run_checks)

    def test_pr_uses_merge_base(self):
        self.git("checkout", "-b", "feature")
        self.write("docs/feature.md")
        head = self.commit()
        self.git("checkout", "main")
        self.write("src/base-only.py")
        base = self.commit()
        self.assertFalse(self.evaluate(head, "pull_request", base).run_checks)
        self.assertTrue(self.evaluate(head, "push", base).run_checks)

    def test_rename_into_excluded_directory(self):
        (self.workspace / "mockups").mkdir()
        (self.workspace / "src/app.py").rename(self.workspace / "mockups/app.py")
        result = self.evaluate(self.commit())
        self.assertTrue(result.run_checks)
        self.assertEqual(result.changed_file_count, 2)

    def test_deleted_code(self):
        (self.workspace / "src/app.py").unlink()
        self.assertTrue(self.evaluate(self.commit()).run_checks)

    def test_initial_push_and_other_events(self):
        for event_name, event, reason in (
            ("push", {"before": "0" * 40}, "initial-push"),
            ("workflow_dispatch", {}, "unsupported-event"),
            ("pull_request_target", {}, "unsupported-event"),
        ):
            result = evaluate_changes(Path("missing"), event_name, event, CONFIG)
            self.assertEqual(result, Result(True, reason))

    def test_invalid_sha_and_missing_history_fail(self):
        for sha in (None, "--output=bad", "f" * 40):
            with self.subTest(sha=sha):
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    self.evaluate(sha)

    def action_environment(self, event):
        directory = Path(self.temporary.name)
        event_path = directory / "event.json"
        event_path.write_text(json.dumps(event), encoding="utf-8")
        return {
            **os.environ,
            "GITHUB_WORKSPACE": str(self.workspace), "GITHUB_EVENT_NAME": "push",
            "GITHUB_EVENT_PATH": str(event_path), "GITHUB_OUTPUT": str(directory / "output"),
            "GITHUB_STEP_SUMMARY": str(directory / "summary"), "SCOPE_CONFIG_PATH": "",
        }

    def execute(self, event, source=TOML, filename=DEFAULT_CONFIG):
        self.write(filename, source)
        env = self.action_environment(event)
        env["SCOPE_CONFIG_PATH"] = filename
        # サイトパッケージを無効化した独立プロセスで、ソース単体の実行を検証する。
        entry = Path(self.temporary.name) / "should_run_checks.py"
        shutil.copyfile(ROOT / "should_run_checks.py", entry)
        result = subprocess.run(
            [sys.executable, "-I", "-S", str(entry)],
            cwd=self.temporary.name, env=env, capture_output=True, text=True, encoding="utf-8",
        )
        output = Path(env["GITHUB_OUTPUT"])
        self.assertTrue(output.exists(), result.stderr)
        return result, output.read_text(encoding="utf-8"), env

    def test_toml_entrypoint_without_packages(self):
        self.write("docs/example.md")
        result, output, env = self.execute({"before": self.base, "after": self.commit()})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, "run_checks=false\nreason=skip-only\n")
        self.assertIn("skip-only", Path(env["GITHUB_STEP_SUMMARY"]).read_text(encoding="utf-8"))

    def test_json_entrypoint(self):
        result, output, _ = self.execute(
            {"before": "0" * 40}, json.dumps(DATA), "custom/rules.json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run_checks=true", output)

    def test_entrypoint_respects_explicit_exception(self):
        self.write("docs/example.md")
        rules = TOML.replace("alwaysRunFiles = []", 'alwaysRunFiles = ["docs/example.md"]')
        result, output, _ = self.execute({"before": self.base, "after": self.commit()}, rules)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reason=changed-files", output)

    def test_entrypoint_reports_invalid_toml_as_error(self):
        result, output, _ = self.execute({"before": "0" * 40}, TOML + "skipExtensions = []\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, "run_checks=true\nreason=error\n")

    def test_missing_config_reports_true_before_failure(self):
        env = self.action_environment({"before": "0" * 40})
        with redirect_stdout(io.StringIO()), self.assertRaises(FileNotFoundError):
            run(env)
        self.assertEqual(Path(env["GITHUB_OUTPUT"]).read_text(), "run_checks=true\nreason=error\n")

    def test_default_toml_path(self):
        self.write(DEFAULT_CONFIG, TOML)
        with redirect_stdout(io.StringIO()):
            result = run(self.action_environment({"before": "0" * 40}))
        self.assertEqual(result, Result(True, "initial-push"))


if __name__ == "__main__":
    unittest.main()
