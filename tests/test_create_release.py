import json
import os
import threading
import unittest
from collections.abc import Mapping
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
from pathlib import Path
from typing import Any
from unittest import mock

import create_release as release

SHA = "a" * 40
OTHER = "b" * 40
THIRD = "c" * 40
CI_URL = "https://github.com/example/repo/actions/runs/99"
PYPROJECT = '[project]\nname = "example"\nversion = "0.3.0"\n'
REPO = "example/repo"


def sample_check(**overrides: object) -> release.CheckRun:
    data: dict[str, object] = {
        "name": "CI",
        "status": "completed",
        "conclusion": "success",
        "head_sha": SHA,
        "event": "push",
        "branch": "main",
        "url": CI_URL,
        "run_number": 4,
    }
    data.update(overrides)
    return release.CheckRun(
        name=str(data["name"]),
        status=str(data["status"]),
        conclusion=str(data["conclusion"]),
        head_sha=str(data["head_sha"]),
        event=str(data["event"]),
        branch=str(data["branch"]),
        url=str(data["url"]),
        run_number=int(str(data["run_number"])),
    )


def sample_pull(**overrides: object) -> release.Pull:
    data: dict[str, object] = {
        "number": 5,
        "title": "判定を直す",
        "body": "本文です。\n",
        "base_ref": "main",
        "merged": True,
        "merge_commit_sha": SHA,
        "labels": (),
    }
    data.update(overrides)
    labels = data["labels"]
    if not isinstance(labels, tuple):
        raise AssertionError
    merge_sha = data["merge_commit_sha"]
    return release.Pull(
        number=int(str(data["number"])),
        title=str(data["title"]),
        body=str(data["body"]),
        base_ref=str(data["base_ref"]),
        merged=bool(data["merged"]),
        merge_commit_sha=merge_sha if isinstance(merge_sha, str) else None,
        labels=labels,
    )


def make_snapshot(**overrides: object) -> release.Snapshot:
    data: dict[str, object] = {
        "repo": REPO,
        "sha": SHA,
        "event": "push",
        "branch": "main",
        "default_branch": "main",
        "ci": sample_check(),
        "pyproject_version": "0.3.0",
        "tags": (release.Tag("v0.3.0", OTHER),),
        "pulls": (sample_pull(),),
        "subjects": ("判定を直す",),
    }
    data.update(overrides)
    ci = data["ci"]
    tags = data["tags"]
    pulls = data["pulls"]
    subjects = data["subjects"]
    if not isinstance(ci, release.CheckRun):
        raise AssertionError
    if (
        not isinstance(tags, tuple)
        or not isinstance(pulls, tuple)
        or not isinstance(subjects, tuple)
    ):
        raise AssertionError
    return release.Snapshot(
        repo=str(data["repo"]),
        sha=str(data["sha"]),
        event=str(data["event"]),
        branch=str(data["branch"]),
        default_branch=str(data["default_branch"]),
        ci=ci,
        pyproject_version=str(data["pyproject_version"]),
        tags=tags,
        pulls=pulls,
        subjects=subjects,
    )


def run_payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": "CI",
        "status": "completed",
        "conclusion": "success",
        "head_sha": SHA,
        "event": "push",
        "head_branch": "main",
        "html_url": CI_URL,
        "run_number": 4,
    }
    data.update(overrides)
    return data


def pull_payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "number": 5,
        "title": "判定を直す",
        "body": (
            "<!-- CURSOR_AGENT_PR_BODY_BEGIN -->\n"
            "本文です。\n"
            "検証: https://example.invalid/old\n"
            "<!-- CURSOR_AGENT_PR_BODY_END -->\n"
            '<div><a href="https://cursor.com/agents/x">Open in Web</a></div>\n'
        ),
        "merged_at": "2026-09-27T14:14:18Z",
        "merge_commit_sha": SHA,
        "base": {"ref": "main"},
        "labels": [],
    }
    data.update(overrides)
    return data


class FakeGitHub:
    def __init__(self) -> None:
        self.gets: dict[str, object] = {}
        self.lists: dict[str, list[object]] = {}
        self.posts: list[tuple[str, Mapping[str, object]]] = []
        self.post_error: release.GitHubRequestError | None = None
        self.post_result: object = {"html_url": "https://example.test/releases/v0.3.1"}

    def get(self, path: str) -> object:
        if path not in self.gets:
            raise AssertionError(path)
        return self.gets[path]

    def get_all(self, path: str) -> list[object]:
        if path not in self.lists:
            raise AssertionError(path)
        return self.lists[path]

    def post(self, path: str, payload: Mapping[str, object]) -> object:
        self.posts.append((path, payload))
        if self.post_error is not None:
            raise self.post_error
        return self.post_result


def happy_client() -> FakeGitHub:
    client = FakeGitHub()
    client.gets[release.repo_path(REPO)] = {"default_branch": "main"}
    client.gets[release.run_path(REPO, "99")] = run_payload()
    client.gets[release.compare_path(REPO, "v0.3.0", SHA)] = {
        "total_commits": 2,
        "commits": [
            {"commit": {"message": "Merge pull request #5 from example/branch\n"}},
            {"commit": {"message": "判定を直す\n\n本文"}},
        ],
    }
    client.lists[release.tags_path(REPO)] = [
        {"name": "v0.3.0", "commit": {"sha": OTHER}},
        {"name": "nightly", "commit": {"sha": "not-a-sha"}},
    ]
    client.lists[release.pulls_path(REPO, SHA)] = [pull_payload()]
    return client


def execute(
    client: FakeGitHub,
    *,
    dry_run: bool = False,
    run_id: str | None = "99",
    event: str = "push",
    branch: str = "main",
    sha: str = SHA,
    pyproject: str = PYPROJECT,
) -> tuple[int, str]:
    stdout = StringIO()
    with redirect_stdout(stdout):
        code = release.execute(
            client,
            dry_run=dry_run,
            repo=REPO,
            sha=sha,
            event=event,
            branch=branch,
            run_id=run_id,
            pyproject_text=pyproject,
        )
    return code, stdout.getvalue()


class DecideTests(unittest.TestCase):
    def test_patch_release_pins_full_sha(self) -> None:
        decision = release.decide(make_snapshot())
        self.assertEqual(decision.action, "create")
        self.assertEqual(decision.tag, "v0.3.1")
        self.assertEqual(decision.name, "v0.3.1 — 判定を直す")
        self.assertIsNotNone(decision.body)
        body = decision.body or ""
        self.assertIn(f"固定参照: `{REPO}@{SHA}`", body)
        self.assertIn(f"検証: {CI_URL}", body)
        self.assertIn("- 判定を直す", body)
        self.assertEqual(len(SHA), 40)

    def test_pyproject_version_wins_when_newer(self) -> None:
        decision = release.decide(
            make_snapshot(
                pyproject_version="0.5.0",
                pulls=(sample_pull(labels=("release:patch",)),),
            )
        )
        self.assertEqual(decision.tag, "v0.5.0")

    def test_labels_bump_minor_and_major(self) -> None:
        minor = release.decide(make_snapshot(pulls=(sample_pull(labels=("release:minor",)),)))
        major = release.decide(make_snapshot(pulls=(sample_pull(labels=("release:major",)),)))
        self.assertEqual(minor.tag, "v0.4.0")
        self.assertEqual(major.tag, "v1.0.0")

    def test_conflicting_labels_fail(self) -> None:
        with self.assertRaises(release.ReleaseError):
            release.decide(
                make_snapshot(pulls=(sample_pull(labels=("release:minor", "release:major")),))
            )

    def test_first_release_uses_pyproject(self) -> None:
        decision = release.decide(make_snapshot(tags=()))
        self.assertEqual(decision.tag, "v0.3.0")

    def test_existing_tag_name_is_not_reused(self) -> None:
        with self.assertRaises(release.ReleaseError):
            release.choose_tag((0, 4, 0), (0, 3, 0), "patch", {"v0.4.0"})

    def test_failed_ci_does_not_release(self) -> None:
        with self.assertRaises(release.ReleaseError):
            release.decide(make_snapshot(ci=sample_check(conclusion="failure")))

    def test_ci_sha_must_match(self) -> None:
        with self.assertRaises(release.ReleaseError):
            release.decide(make_snapshot(ci=sample_check(head_sha=OTHER)))

    def test_already_tagged_commit_is_skipped(self) -> None:
        decision = release.decide(make_snapshot(tags=(release.Tag("v0.3.0", SHA),)))
        self.assertEqual(decision.action, "skip")
        self.assertIn("v0.3.0", decision.reason)

    def test_push_without_merged_pr_is_skipped(self) -> None:
        decision = release.decide(make_snapshot(pulls=()))
        self.assertEqual(decision.action, "skip")

    def test_non_push_event_is_skipped(self) -> None:
        decision = release.decide(
            make_snapshot(event="pull_request", ci=sample_check(conclusion="failure"))
        )
        self.assertEqual(decision.action, "skip")

    def test_non_default_branch_fails(self) -> None:
        with self.assertRaises(release.ReleaseError):
            release.decide(make_snapshot(branch="feature"))

    def test_single_squash_pr_is_released(self) -> None:
        decision = release.decide(make_snapshot(pulls=(sample_pull(merge_commit_sha=THIRD),)))
        self.assertEqual(decision.tag, "v0.3.1")

    def test_ambiguous_pulls_fail(self) -> None:
        pulls = (
            sample_pull(number=5, merge_commit_sha=THIRD),
            sample_pull(number=6, merge_commit_sha=OTHER),
        )
        with self.assertRaises(release.ReleaseError):
            release.decide(make_snapshot(pulls=pulls))

    def test_http_verification_url_fails(self) -> None:
        with self.assertRaises(release.ReleaseError):
            release.decide(make_snapshot(ci=sample_check(url="http://example.test/run")))

    def test_release_notes_drop_cursor_footer(self) -> None:
        body = release.clean_pr_body(str(pull_payload()["body"]))
        self.assertIn("本文です。", body)
        self.assertNotIn("cursor.com", body)
        self.assertNotIn("検証:", body)

    def test_long_title_is_bounded(self) -> None:
        decision = release.decide(make_snapshot(pulls=(sample_pull(title="あ" * 300),)))
        self.assertIsNotNone(decision.name)
        self.assertLessEqual(len(decision.name or ""), 250)


class LoadTests(unittest.TestCase):
    def test_dry_run_does_not_post(self) -> None:
        client = happy_client()
        code, output = execute(client, dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(client.posts, [])
        self.assertIn(f"確認のみ: v0.3.1 を {SHA} に作成します。", output)
        self.assertIn(f"固定参照: `{REPO}@{SHA}`", output)
        self.assertNotIn("https://example.invalid/old", output)
        self.assertNotIn("cursor.com", output)

    def test_publish_targets_the_ci_commit(self) -> None:
        client = happy_client()
        code, output = execute(client)
        self.assertEqual(code, 0)
        self.assertIn("https://example.test/releases/v0.3.1", output)
        path, payload = client.posts[0]
        self.assertEqual(path, release.release_path(REPO))
        self.assertEqual(payload["tag_name"], "v0.3.1")
        self.assertEqual(payload["target_commitish"], SHA)
        self.assertEqual(payload["draft"], False)
        self.assertEqual(payload["prerelease"], False)
        self.assertEqual(payload["generate_release_notes"], False)

    def test_existing_release_for_same_sha_is_kept(self) -> None:
        client = happy_client()
        client.post_error = release.GitHubRequestError(422, "Validation Failed")
        client.gets[release.git_ref_path(REPO, "v0.3.1")] = {
            "object": {"type": "tag", "sha": THIRD}
        }
        client.gets[release.git_tag_path(REPO, THIRD)] = {"object": {"type": "commit", "sha": SHA}}
        client.gets[release.release_by_tag_path(REPO, "v0.3.1")] = {
            "html_url": "https://example.test/releases/tag/v0.3.1"
        }
        code, output = execute(client)
        self.assertEqual(code, 0)
        self.assertIn("https://example.test/releases/tag/v0.3.1", output)

    def test_tag_on_another_commit_fails(self) -> None:
        client = happy_client()
        client.post_error = release.GitHubRequestError(422, "Validation Failed")
        client.gets[release.git_ref_path(REPO, "v0.3.1")] = {
            "object": {"type": "commit", "sha": OTHER}
        }
        with self.assertRaises(release.ReleaseError):
            execute(client)

    def test_lists_ci_runs_when_run_id_is_absent(self) -> None:
        client = happy_client()
        client.gets[release.runs_path(REPO, SHA, 1)] = {
            "total_count": 2,
            "workflow_runs": [run_payload(run_number=3)],
        }
        client.gets[release.runs_path(REPO, SHA, 2)] = {
            "total_count": 2,
            "workflow_runs": [run_payload(run_number=4)],
        }
        code, _output = execute(client, run_id=None)
        self.assertEqual(code, 0)

    def test_newer_failed_run_blocks_release(self) -> None:
        client = happy_client()
        client.gets[release.runs_path(REPO, SHA, 1)] = {
            "total_count": 2,
            "workflow_runs": [
                run_payload(run_number=5, conclusion="failure"),
                run_payload(run_number=4),
            ],
        }
        with self.assertRaises(release.ReleaseError):
            execute(client, run_id=None)

    def test_incomplete_ci_blocks_release(self) -> None:
        client = happy_client()
        client.gets[release.runs_path(REPO, SHA, 1)] = {
            "total_count": 1,
            "workflow_runs": [run_payload(status="in_progress", conclusion="")],
        }
        with self.assertRaises(release.ReleaseError):
            execute(client, run_id=None)

    def test_short_sha_fails(self) -> None:
        with self.assertRaises(release.ReleaseError):
            execute(happy_client(), sha="abc")

    def test_invalid_pyproject_fails(self) -> None:
        with self.assertRaises(release.ReleaseError):
            execute(happy_client(), pyproject='[project]\nversion = "0.3"\n')


class AutomationTests(unittest.TestCase):
    def test_pull_request_merged_runs_create_release(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / ".cursor/automations/release-on-merge.md").read_text(encoding="utf-8")
        self.assertIn("Pull request merged", text)
        self.assertIn("python3 create_release.py", text)
        self.assertIn("RELEASE_SHA", text)
        self.assertIn("RELEASE_CI_RUN_ID", text)
        self.assertIn("40桁", text)
        self.assertIn("git tag", text)
        self.assertIn("gh release create", text)
        self.assertFalse((root / ".github/workflows/release.yml").exists())

    def test_cli_token_is_used_when_environment_is_empty(self) -> None:
        with (
            mock.patch.dict(os.environ, {"GITHUB_TOKEN": "", "GH_TOKEN": ""}, clear=False),
            mock.patch.object(release, "github_token_from_cli", return_value="from-cli") as lookup,
        ):
            self.assertEqual(release.resolve_github_token(), "from-cli")
        lookup.assert_called_once_with()


class HttpTests(unittest.TestCase):
    def test_rejects_non_https_api(self) -> None:
        with self.assertRaises(release.ReleaseError):
            release.HttpGitHub("token", "http://example.test")

    def test_rejects_next_page_on_another_host(self) -> None:
        with self.assertRaises(release.ReleaseError):
            release.next_page(
                '<https://evil.example/tags>; rel="next"',
                "https://api.github.com",
            )

    def test_paginates_and_posts_on_local_api(self) -> None:
        posted: list[bytes] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.headers.get("Authorization") != "Bearer test-token":
                    self.send_response(401)
                    self.end_headers()
                    return
                if self.path == "/repos/example/repo/tags?per_page=100":
                    body = json.dumps([{"name": "v0.1.0", "commit": {"sha": OTHER}}]).encode()
                    link = f'<{base_url}/next>; rel="next"'
                elif self.path == "/next":
                    body = json.dumps([{"name": "v0.2.0", "commit": {"sha": SHA}}]).encode()
                    link = ""
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self._send(200, body, link)

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                posted.append(self.rfile.read(length))
                self._send(201, b'{"html_url":"https://example.test/releases/v0.2.0"}', "")

            def _send(self, status: int, body: bytes, link: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                if link:
                    self.send_header("Link", link)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        base_url = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            client = release.HttpGitHub("test-token", base_url)
            tags = client.get_all("/repos/example/repo/tags?per_page=100")
            created = client.post("/repos/example/repo/releases", {"tag_name": "v0.2.0"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(len(tags), 2)
        self.assertEqual(created, {"html_url": "https://example.test/releases/v0.2.0"})
        self.assertEqual(json.loads(posted[0].decode()), {"tag_name": "v0.2.0"})


class MainTests(unittest.TestCase):
    def test_usage(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr):
            code = release.main(["--help"])
        self.assertEqual(code, 2)
        self.assertIn("--dry-run", stderr.getvalue())

    def test_missing_token(self) -> None:
        stderr = StringIO()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                release,
                "github_token_from_cli",
                side_effect=release.ReleaseError("GITHUB_TOKENがありません。"),
            ),
            redirect_stderr(stderr),
        ):
            code = release.main([])
        self.assertEqual(code, 1)
        self.assertIn("GITHUB_TOKEN", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
