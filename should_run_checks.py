"""標準ライブラリだけで設定とGit差分からCIの実行要否を判定する。"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from typing import Mapping

CONFIG_KEYS = ("skipExtensions", "skipDirectories", "alwaysRunFiles")
DEFAULT_CONFIG = ".github/ci-skip-rules.toml"


@dataclass(frozen=True)
class Config:
    skip_extensions: tuple[str, ...]
    skip_directories: tuple[str, ...]
    always_run_files: tuple[str, ...]


@dataclass(frozen=True)
class Result:
    run_checks: bool
    reason: str
    changed_file_count: int | None = None


def validate_config(data: object) -> Config:
    if not isinstance(data, dict):
        raise ValueError("設定はキーと値のマッピングで指定してください。")
    for key in data:
        if key not in CONFIG_KEYS:
            raise ValueError(f"未知の設定キー: {key}")
    for key in CONFIG_KEYS:
        values = data.get(key)
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise ValueError(f"{key} は空でない文字列の配列で指定してください。")
    for extension in data["skipExtensions"]:
        if (
            not extension.startswith(".")
            or len(extension) < 2
            or any(char in extension for char in '/\\*?[]{}!')
        ):
            raise ValueError(f"拡張子はドットから始まる文字列で指定してください: {extension}")
    for key in ("skipDirectories", "alwaysRunFiles"):
        for path in data[key]:
            if any(char in path for char in '\\*?[]{}!') or any(
                part in ("", ".", "..") for part in path.split("/")
            ):
                raise ValueError(f"{key} にはglobを使わず相対パスを指定してください: {path}")
    return Config(*(tuple(data[key]) for key in CONFIG_KEYS))


def unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重複した設定キー: {key}")
        result[key] = value
    return result


def parse_config(source: str, filename: str) -> Config:
    suffix = Path(filename).suffix.lower()
    if suffix == ".toml":
        data = tomllib.loads(source)
    elif suffix == ".json":
        data = json.loads(source, object_pairs_hook=unique_json_object)
    else:
        raise ValueError("設定には.tomlまたは.jsonを指定してください。YAMLには対応していません。")
    return validate_config(data)


def should_run_checks(changed_files: list[str], config: Config) -> bool:
    for path in changed_files:
        if path in config.always_run_files:
            return True
        if any(path.startswith(directory + "/") for directory in config.skip_directories):
            continue
        if not any(path.endswith(extension) for extension in config.skip_extensions):
            return True
    return False


def evaluate_changes(workspace: Path, event_name: str, event: dict, config: Config) -> Result:
    if event_name == "pull_request":
        pull_request = event.get("pull_request", {})
        base = pull_request.get("base", {}).get("sha")
        head = pull_request.get("head", {}).get("sha")
        separator = "..."
    elif event_name == "push":
        base, head = event.get("before"), event.get("after")
        if isinstance(base, str) and re.fullmatch(r"(?:0{40}|0{64})", base):
            return Result(True, "initial-push")
        separator = ".."
    else:
        return Result(True, "unsupported-event")
    for sha in (base, head):
        if not isinstance(sha, str) or not re.fullmatch(r"(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})", sha):
            raise ValueError("イベントに有効なbase/headコミットSHAがありません。")
    # 削除とリネーム前後を含め、空白・改行のあるパスもNUL区切りで保持する。
    diff = subprocess.run(
        ["git", "-C", str(workspace), "diff", "--no-renames", "--name-only", "-z",
         f"{base}{separator}{head}", "--"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout
    files = [os.fsdecode(path) for path in diff.split(b"\0") if path]
    run_checks = should_run_checks(files, config)
    reason = "no-changes" if not files else "changed-files" if run_checks else "skip-only"
    return Result(run_checks, reason, len(files))


def write_result(result: Result, env: Mapping[str, str]) -> None:
    value = str(result.run_checks).lower()
    output = f"run_checks={value}\nreason={result.reason}\n"
    if env.get("GITHUB_OUTPUT"):
        with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="\n") as stream:
            stream.write(output)
    print(output, end="")
    if env.get("GITHUB_STEP_SUMMARY"):
        summary = f"## Should Run Checks\n\n- チェックを実行: {value}\n- 判定理由: {result.reason}\n"
        if result.changed_file_count is not None:
            summary += f"- 変更パス数: {result.changed_file_count}\n"
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8", newline="\n") as stream:
            stream.write(summary)


def run(env: Mapping[str, str] | None = None) -> Result:
    if env is None:
        env = os.environ
    try:
        workspace = Path(env.get("GITHUB_WORKSPACE") or Path.cwd()).resolve()
        config_path = workspace / (env.get("SCOPE_CONFIG_PATH") or DEFAULT_CONFIG)
        config = parse_config(config_path.read_text(encoding="utf-8"), str(config_path))
        event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        result = evaluate_changes(workspace, env.get("GITHUB_EVENT_NAME", ""), event, config)
        write_result(result, env)
        return result
    except Exception:
        # 利用側がalways()で継続しても、判定失敗によってチェックを省略させない。
        write_result(Result(True, "error"), env)
        raise


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        message = str(error).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error::{message}", file=sys.stderr)
        sys.exit(1)
