"""CIが成功したpull requestのマージコミットにGitHub Releaseを作成する。"""

import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

_VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_RUN_ID = re.compile(r"[1-9]\d*\Z")
_RELEASE_LABELS = {
    "release:major": "major",
    "release:minor": "minor",
    "release:patch": "patch",
}
_CURSOR_MARKERS = (
    "cursor.com/agents",
    "cursor.com/background-agent",
    "Open in Web",
    "Open in Cursor",
)


class ReleaseError(Exception):
    """リリースの前提が満たせず、タグを作らない。"""


class GitHubRequestError(ReleaseError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"GitHub APIが失敗しました ({status}): {message}")


class GitHubClient(Protocol):
    def get(self, path: str) -> object: ...

    def get_all(self, path: str) -> list[object]: ...

    def post(self, path: str, payload: Mapping[str, object]) -> object: ...


@dataclass(frozen=True)
class Tag:
    name: str
    sha: str


@dataclass(frozen=True)
class Pull:
    number: int
    title: str
    body: str
    base_ref: str
    merged: bool
    merge_commit_sha: str | None
    labels: tuple[str, ...]


@dataclass(frozen=True)
class CheckRun:
    name: str
    status: str
    conclusion: str
    head_sha: str
    event: str
    branch: str
    url: str
    run_number: int


@dataclass(frozen=True)
class Snapshot:
    repo: str
    sha: str
    event: str
    branch: str
    default_branch: str
    ci: CheckRun
    pyproject_version: str
    tags: tuple[Tag, ...]
    pulls: tuple[Pull, ...]
    subjects: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    tag: str | None = None
    name: str | None = None
    body: str | None = None
    sha: str | None = None


def validate_repo(value: str) -> str:
    if _REPOSITORY.fullmatch(value) is None:
        raise ReleaseError("リポジトリ名が不正です。")
    return value


def normalize_sha(value: str) -> str:
    sha = value.lower()
    if _SHA.fullmatch(sha) is None:
        raise ReleaseError("コミットは40桁のSHAで指定してください。")
    return sha


def parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value)
    if match is None:
        raise ReleaseError(f"バージョンはX.Y.Zで指定してください: {value}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def version_of_tag(name: str) -> tuple[int, int, int] | None:
    if not name.startswith("v"):
        return None
    match = _VERSION.fullmatch(name[1:])
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def format_tag(version: tuple[int, int, int]) -> str:
    major, minor, patch = version
    return f"v{major}.{minor}.{patch}"


def validate_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or ""
    if parsed.scheme == "https" and parsed.netloc:
        return base_url.rstrip("/")
    if parsed.scheme == "http" and host in {"127.0.0.1", "localhost"} and parsed.port:
        return base_url.rstrip("/")
    raise ReleaseError("GitHub APIのURLが不正です。")


def repo_path(repo: str) -> str:
    return f"/repos/{repo}"


def run_path(repo: str, run_id: str) -> str:
    return f"/repos/{repo}/actions/runs/{run_id}"


def runs_path(repo: str, sha: str, page: int) -> str:
    return f"/repos/{repo}/actions/workflows/ci.yml/runs?head_sha={sha}&per_page=100&page={page}"


def tags_path(repo: str) -> str:
    return f"/repos/{repo}/tags?per_page=100"


def pulls_path(repo: str, sha: str) -> str:
    return f"/repos/{repo}/commits/{sha}/pulls"


def compare_path(repo: str, tag: str, sha: str) -> str:
    quoted = urllib.parse.quote(tag, safe="")
    return f"/repos/{repo}/compare/{quoted}...{sha}"


def release_path(repo: str) -> str:
    return f"/repos/{repo}/releases"


def release_by_tag_path(repo: str, tag: str) -> str:
    return f"/repos/{repo}/releases/tags/{urllib.parse.quote(tag, safe='')}"


def git_ref_path(repo: str, tag: str) -> str:
    return f"/repos/{repo}/git/ref/tags/{urllib.parse.quote(tag, safe='')}"


def git_tag_path(repo: str, tag_sha: str) -> str:
    return f"/repos/{repo}/git/tags/{tag_sha}"


def expect_mapping(value: object, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseError(f"{what}がオブジェクトではありません。")
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ReleaseError(f"{what}のキーが文字列ではありません。")
        result[key] = item
    return result


def expect_string(value: object, what: str) -> str:
    if isinstance(value, str) and value:
        return value
    raise ReleaseError(f"{what}がありません。")


def read_pyproject_version(text: str) -> str:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ReleaseError("pyproject.tomlを解釈できません。") from error
    project = data.get("project")
    if not isinstance(project, dict):
        raise ReleaseError("pyproject.tomlにprojectがありません。")
    version = project.get("version")
    if not isinstance(version, str):
        raise ReleaseError("pyproject.tomlのversionが文字列ではありません。")
    parse_version(version)
    return version


def parse_run(item: object) -> CheckRun:
    data = expect_mapping(item, "CI")
    conclusion = data.get("conclusion")
    run_number = data.get("run_number")
    if not isinstance(run_number, int) or isinstance(run_number, bool):
        raise ReleaseError("CIのrun_numberが不正です。")
    return CheckRun(
        name=expect_string(data.get("name"), "CIの名前"),
        status=expect_string(data.get("status"), "CIの状態"),
        conclusion=conclusion if isinstance(conclusion, str) else "",
        head_sha=normalize_sha(expect_string(data.get("head_sha"), "CIのコミットSHA")),
        event=expect_string(data.get("event"), "CIのイベント"),
        branch=expect_string(data.get("head_branch"), "CIのブランチ"),
        url=expect_string(data.get("html_url"), "CIのURL"),
        run_number=run_number,
    )


def parse_tag(item: object) -> Tag | None:
    data = expect_mapping(item, "タグ")
    name = expect_string(data.get("name"), "タグ名")
    if version_of_tag(name) is None:
        return None
    commit = expect_mapping(data.get("commit"), "タグのcommit")
    return Tag(name, normalize_sha(expect_string(commit.get("sha"), "タグのコミットSHA")))


def parse_pull(item: object) -> Pull:
    data = expect_mapping(item, "pull request")
    number = data.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ReleaseError("pull request番号が不正です。")
    body = data.get("body")
    if body is None:
        body_text = ""
    elif isinstance(body, str):
        body_text = body
    else:
        raise ReleaseError("pull requestの本文が文字列ではありません。")
    merged_at = data.get("merged_at")
    raw_merge_sha = data.get("merge_commit_sha")
    if raw_merge_sha is None:
        merge_sha = None
    elif isinstance(raw_merge_sha, str):
        merge_sha = normalize_sha(raw_merge_sha)
    else:
        raise ReleaseError("merge_commit_shaが文字列ではありません。")
    base = expect_mapping(data.get("base"), "pull requestのbase")
    return Pull(
        number=number,
        title=expect_string(data.get("title"), "pull requestの題名"),
        body=body_text,
        base_ref=expect_string(base.get("ref"), "pull requestのマージ先"),
        merged=isinstance(merged_at, str) and bool(merged_at),
        merge_commit_sha=merge_sha,
        labels=parse_labels(data.get("labels")),
    )


def parse_labels(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ReleaseError("pull requestのラベルが配列ではありません。")
    names: list[str] = []
    for item in value:
        data = expect_mapping(item, "ラベル")
        names.append(expect_string(data.get("name"), "ラベル名"))
    return tuple(names)


def parse_subjects(payload: object) -> tuple[str, ...]:
    data = expect_mapping(payload, "比較結果")
    commits = data.get("commits")
    if not isinstance(commits, list):
        raise ReleaseError("比較結果にcommitsがありません。")
    subjects: list[str] = []
    for item in commits:
        commit = expect_mapping(item, "比較結果のcommit")
        detail = expect_mapping(commit.get("commit"), "比較結果のcommit.commit")
        message = detail.get("message")
        if not isinstance(message, str):
            raise ReleaseError("コミットメッセージがありません。")
        subject = message.splitlines()[0].strip() if message.splitlines() else ""
        if subject and not subject.startswith("Merge "):
            subjects.append(subject)
    omitted = 0
    total = data.get("total_commits")
    if isinstance(total, int) and not isinstance(total, bool) and total > len(commits):
        omitted = total - len(commits)
    if len(subjects) > 100:
        omitted += len(subjects) - 100
        subjects = subjects[:100]
    if omitted:
        subjects.append(f"ほか{omitted}件")
    return tuple(subjects)


def highest_tag(tags: tuple[Tag, ...]) -> Tag | None:
    best: Tag | None = None
    best_version: tuple[int, int, int] | None = None
    for tag in tags:
        version = version_of_tag(tag.name)
        if version is None:
            continue
        if best_version is None or version > best_version:
            best = tag
            best_version = version
    return best


def parse_runs_page(payload: object) -> tuple[int, tuple[CheckRun, ...]]:
    data = expect_mapping(payload, "CI一覧")
    total = data.get("total_count")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ReleaseError("CI一覧の件数が不正です。")
    runs = data.get("workflow_runs")
    if not isinstance(runs, list):
        raise ReleaseError("CI一覧が配列ではありません。")
    return total, tuple(parse_run(item) for item in runs)


def choose_run(runs: tuple[CheckRun, ...], sha: str, branch: str) -> CheckRun:
    matching = tuple(
        run
        for run in runs
        if run.name == "CI" and run.head_sha == sha and run.event == "push" and run.branch == branch
    )
    if not matching:
        raise ReleaseError("デフォルトブランチへのpushに対するCIが見つかりません。")
    if any(run.status != "completed" for run in matching):
        raise ReleaseError("CIが完了していないため、リリースしません。")
    return max(matching, key=lambda run: run.run_number)


def find_run(client: GitHubClient, repo: str, sha: str, branch: str) -> CheckRun:
    collected: list[CheckRun] = []
    total = 0
    for page in range(1, 11):
        page_total, runs = parse_runs_page(client.get(runs_path(repo, sha, page)))
        if page == 1:
            total = page_total
        elif page_total != total:
            raise ReleaseError("CI一覧の件数が一致しません。")
        if not runs and len(collected) < total:
            raise ReleaseError("CIの実行一覧を読み切れませんでした。")
        collected.extend(runs)
        if len(collected) >= total:
            break
    else:
        raise ReleaseError("CIの実行一覧を読み切れませんでした。")
    return choose_run(tuple(collected), sha, branch)


def load_snapshot(
    client: GitHubClient,
    *,
    repo: str,
    sha: str,
    event: str,
    branch: str,
    run_id: str | None,
    pyproject_text: str,
) -> Snapshot:
    repository = validate_repo(repo)
    commit = normalize_sha(sha)
    if not event or not branch:
        raise ReleaseError("RELEASE_EVENTとRELEASE_BRANCHが必要です。")
    repository_info = expect_mapping(client.get(repo_path(repository)), "リポジトリ")
    default_branch = expect_string(repository_info.get("default_branch"), "デフォルトブランチ")
    if run_id is None:
        check = find_run(client, repository, commit, default_branch)
    else:
        if _RUN_ID.fullmatch(run_id) is None:
            raise ReleaseError("CIの実行IDが不正です。")
        check = parse_run(client.get(run_path(repository, run_id)))
    tags = tuple(
        tag
        for item in client.get_all(tags_path(repository))
        if (tag := parse_tag(item)) is not None
    )
    pulls = tuple(parse_pull(item) for item in client.get_all(pulls_path(repository, commit)))
    latest = highest_tag(tags)
    subjects: tuple[str, ...] = ()
    if latest is not None and latest.sha != commit:
        subjects = parse_subjects(client.get(compare_path(repository, latest.name, commit)))
    return Snapshot(
        repo=repository,
        sha=commit,
        event=event,
        branch=branch,
        default_branch=default_branch,
        ci=check,
        pyproject_version=read_pyproject_version(pyproject_text),
        tags=tags,
        pulls=pulls,
        subjects=subjects,
    )


def bump_kind(labels: tuple[str, ...]) -> str:
    kinds = {_RELEASE_LABELS[label] for label in labels if label in _RELEASE_LABELS}
    if len(kinds) > 1:
        raise ReleaseError("releaseのラベルが複数あるため、バージョンを決められません。")
    if not kinds:
        return "patch"
    return next(iter(kinds))


def bump_version(version: tuple[int, int, int], kind: str) -> tuple[int, int, int]:
    major, minor, patch = version
    if kind == "major":
        return (major + 1, 0, 0)
    if kind == "minor":
        return (major, minor + 1, 0)
    if kind == "patch":
        return (major, minor, patch + 1)
    raise ReleaseError(f"未知のリリース種別です: {kind}")


def choose_tag(
    pyproject: tuple[int, int, int],
    latest: tuple[int, int, int] | None,
    kind: str,
    taken: set[str],
) -> str:
    version = pyproject if latest is None or pyproject > latest else bump_version(latest, kind)
    tag = format_tag(version)
    if tag in taken:
        raise ReleaseError(f"タグ{tag}は既に別のコミットにあります。")
    return tag


def clean_pr_body(body: str) -> str:
    without_comments = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    kept: list[str] = []
    for line in without_comments.splitlines():
        stripped = line.strip()
        if any(marker in stripped for marker in _CURSOR_MARKERS):
            continue
        if stripped.startswith("検証:") or stripped.startswith("固定参照:"):
            continue
        if re.fullmatch(r"</?(?:div|picture|source|img|a)(?:\s[^>]*)?>", stripped):
            continue
        kept.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept).strip())


def render_body(
    repo: str,
    sha: str,
    ci_url: str,
    pr_body: str,
    subjects: tuple[str, ...],
) -> str:
    parts: list[str] = []
    cleaned = clean_pr_body(pr_body)
    if cleaned:
        parts.append(cleaned)
    if subjects:
        parts.append("\n".join(f"- {subject}" for subject in subjects))
    parts.append(f"検証: {ci_url}")
    parts.append(f"固定参照: `{repo}@{sha}`")
    return "\n\n".join(parts) + "\n"


def release_name(tag: str, title: str) -> str:
    prefix = f"{tag} — "
    compact = " ".join(title.split())
    room = 250 - len(prefix)
    if len(compact) > room:
        compact = compact[: room - 1].rstrip() + "…"
    return prefix + compact


def select_pull(pulls: tuple[Pull, ...], default_branch: str, sha: str) -> Pull | None:
    merged = tuple(pull for pull in pulls if pull.merged and pull.base_ref == default_branch)
    matched = tuple(pull for pull in merged if pull.merge_commit_sha == sha)
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        raise ReleaseError(
            "マージコミットに複数のpull requestが紐づいているため、リリースできません。"
        )
    if len(merged) == 1:
        return merged[0]
    if not merged:
        return None
    raise ReleaseError("複数のpull requestが紐づいているため、リリースできません。")


def decide(snapshot: Snapshot) -> Decision:
    if snapshot.event != "push":
        return Decision("skip", "push以外のイベントではリリースしません。")
    if snapshot.branch != snapshot.default_branch:
        raise ReleaseError("デフォルトブランチ以外のpushはリリースできません。")
    ci = snapshot.ci
    if ci.name != "CI":
        raise ReleaseError("CIワークフロー以外の成功ではリリースしません。")
    if ci.head_sha != snapshot.sha:
        raise ReleaseError("CIの対象コミットとリリース対象が一致しません。")
    if ci.event != "push" or ci.branch != snapshot.default_branch:
        raise ReleaseError("デフォルトブランチへのpushに対するCIだけをリリースに使います。")
    if ci.status != "completed" or ci.conclusion != "success":
        raise ReleaseError("CIが成功していないコミットにはタグを付けません。")
    if not ci.url.startswith("https://"):
        raise ReleaseError("CIの検証URLがありません。")
    existing = tuple(
        sorted(
            tag.name
            for tag in snapshot.tags
            if tag.sha == snapshot.sha and version_of_tag(tag.name)
        )
    )
    if existing:
        names = ", ".join(existing)
        return Decision("skip", f"このコミットには既にリリースタグがあります: {names}")
    pull = select_pull(snapshot.pulls, snapshot.default_branch, snapshot.sha)
    if pull is None:
        return Decision("skip", "マージされたpull requestがないためリリースしません。")
    kind = bump_kind(pull.labels)
    latest = highest_tag(snapshot.tags)
    tag = choose_tag(
        parse_version(snapshot.pyproject_version),
        None if latest is None else version_of_tag(latest.name),
        kind,
        {item.name for item in snapshot.tags if version_of_tag(item.name)},
    )
    return Decision(
        "create",
        "CIが成功したマージコミットです。",
        tag,
        release_name(tag, pull.title),
        render_body(snapshot.repo, snapshot.sha, ci.url, pull.body, snapshot.subjects),
        snapshot.sha,
    )


def resolve_tag_sha(client: GitHubClient, repo: str, tag: str) -> str:
    ref = expect_mapping(client.get(git_ref_path(repo, tag)), "タグ参照")
    obj = expect_mapping(ref.get("object"), "タグ参照のobject")
    kind = expect_string(obj.get("type"), "タグ種別")
    sha = normalize_sha(expect_string(obj.get("sha"), "タグSHA"))
    if kind == "commit":
        return sha
    if kind != "tag":
        raise ReleaseError("タグの種別を解釈できません。")
    annotated = expect_mapping(client.get(git_tag_path(repo, sha)), "注釈タグ")
    target = expect_mapping(annotated.get("object"), "注釈タグのobject")
    if expect_string(target.get("type"), "注釈タグの種別") != "commit":
        raise ReleaseError("注釈タグの参照先がコミットではありません。")
    return normalize_sha(expect_string(target.get("sha"), "注釈タグのコミットSHA"))


def publish(client: GitHubClient, repo: str, decision: Decision) -> str:
    if (
        decision.tag is None
        or decision.name is None
        or decision.body is None
        or decision.sha is None
    ):
        raise ReleaseError("リリース内容が不足しています。")
    payload: dict[str, object] = {
        "tag_name": decision.tag,
        "target_commitish": decision.sha,
        "name": decision.name,
        "body": decision.body,
        "draft": False,
        "prerelease": False,
        "generate_release_notes": False,
    }
    try:
        created = expect_mapping(client.post(release_path(repo), payload), "リリース")
    except GitHubRequestError as error:
        if error.status != 422:
            raise
        existing = resolve_tag_sha(client, repo, decision.tag)
        if existing != decision.sha:
            raise ReleaseError(f"タグ{decision.tag}は別のコミットを指しています。") from error
        created = expect_mapping(client.get(release_by_tag_path(repo, decision.tag)), "リリース")
    return expect_string(created.get("html_url"), "リリースURL")


def execute(
    client: GitHubClient,
    *,
    dry_run: bool,
    repo: str,
    sha: str,
    event: str,
    branch: str,
    run_id: str | None,
    pyproject_text: str,
) -> int:
    decision = decide(
        load_snapshot(
            client,
            repo=repo,
            sha=sha,
            event=event,
            branch=branch,
            run_id=run_id,
            pyproject_text=pyproject_text,
        )
    )
    if decision.action == "skip":
        print(f"リリースを省略します: {decision.reason}")
        return 0
    if decision.tag is None or decision.sha is None or decision.body is None:
        raise ReleaseError("リリース内容が不足しています。")
    if dry_run:
        print(f"確認のみ: {decision.tag} を {decision.sha} に作成します。")
        print(decision.body, end="")
        return 0
    url = publish(client, validate_repo(repo), decision)
    print(f"リリースを作成しました: {url}")
    return 0


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        raise ReleaseError(f"GitHub APIがリダイレクトを返しました ({code})。")


def next_page(link_header: str, base_url: str) -> str | None:
    match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
    if match is None:
        return None
    target = urllib.parse.urlparse(match.group(1))
    base = urllib.parse.urlparse(base_url)
    if target.scheme != base.scheme or target.netloc != base.netloc:
        raise ReleaseError("GitHub APIのページURLが不正です。")
    return match.group(1)


def _error_message(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text[:500] or "応答が空です。"
    if isinstance(parsed, dict):
        message = parsed.get("message")
        if isinstance(message, str) and message:
            return message
    return text[:500] or "応答が空です。"


class HttpGitHub:
    def __init__(self, token: str, base_url: str) -> None:
        if not token:
            raise ReleaseError("GITHUB_TOKENがありません。")
        self._token = token
        self.base_url = validate_base_url(base_url)
        self._opener = urllib.request.build_opener(_RejectRedirect)

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            raise ReleaseError("GitHub APIのパスが不正です。")
        return self.base_url + path

    def _read(
        self, method: str, url: str, payload: Mapping[str, object] | None
    ) -> tuple[object, str]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("User-Agent", "release-on-merge")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self._opener.open(request, timeout=30) as response:
                raw = response.read()
                link_value = response.headers.get("Link", "")
                link = link_value if isinstance(link_value, str) else ""
        except urllib.error.HTTPError as error:
            code = error.code if isinstance(error.code, int) else 0
            raise GitHubRequestError(code, _error_message(error.read())) from error
        except urllib.error.URLError as error:
            raise ReleaseError("GitHub APIに接続できません。") from error
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReleaseError("GitHub APIの応答を解釈できません。") from error
        return parsed, link

    def get(self, path: str) -> object:
        payload, _link = self._read("GET", self._url(path), None)
        return payload

    def get_all(self, path: str) -> list[object]:
        url: str | None = self._url(path)
        items: list[object] = []
        while url is not None:
            payload, link = self._read("GET", url, None)
            if not isinstance(payload, list):
                raise ReleaseError("GitHub APIの一覧が配列ではありません。")
            items.extend(payload)
            url = next_page(link, self.base_url)
        return items

    def post(self, path: str, payload: Mapping[str, object]) -> object:
        body, _link = self._read("POST", self._url(path), payload)
        return body


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args not in ([], ["--dry-run"]):
        print("使い方: create_release.py [--dry-run]", file=sys.stderr)
        return 2
    try:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        if not token:
            raise ReleaseError("GITHUB_TOKENがありません。")
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        return execute(
            HttpGitHub(token, os.environ.get("GITHUB_API_URL", "https://api.github.com")),
            dry_run=args == ["--dry-run"],
            repo=os.environ.get("GITHUB_REPOSITORY", ""),
            sha=os.environ.get("RELEASE_SHA", ""),
            event=os.environ.get("RELEASE_EVENT", ""),
            branch=os.environ.get("RELEASE_BRANCH", ""),
            run_id=os.environ.get("RELEASE_CI_RUN_ID") or None,
            pyproject_text=pyproject,
        )
    except ReleaseError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError as error:
        print(f"pyproject.tomlを読めません: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
