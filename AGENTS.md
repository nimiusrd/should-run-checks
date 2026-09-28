# 開発ルール

- 日本語で記述・回答する。
- Python 3.11以降の標準ライブラリだけで実装する。実行時の外部Pythonパッケージやnpm依存を追加しない。開発用チェックに限り、`pyproject.toml`のdevグループに定義したmypy・Ruffをuvで管理し、`uv.lock`をコミットする。Action内でPython 3.13を準備し、呼び出し元のPATHを変更しない。
- ローカルの Dev Container では、プロジェクトのコマンドを `devcontainer exec --workspace-folder . <command>` で実行する。Cursor Cloud Agent では Dev Container を使わず、環境の uv 0.12.19 で同じ `uv run --locked ...` を直接実行する。Git操作はホストで行う。
- 提出前に `uv run --locked python -m unittest discover -s tests -v`、`uv run --locked python -m compileall -q should_run_checks.py tests`、`uv run --locked mypy`、`uv run --locked ruff check .`、`uv run --locked ruff format --check .`、`git diff --check` を確認する。
- TOMLは標準の`tomllib`で読む。JSONは標準の`json`で読めるが、YAMLの独自パーサは実装しない。
- 判定できない場合にチェックを省略しない。設定不備やGitの失敗を `run_checks=false` に変換しない。
- 設定は利用側のリポジトリに置く。特定プロジェクトのディレクトリ名を実装へ埋め込まない。
- リリースは、Cursor AutomationのPull request mergedで起動し、AutomationがCI成功済みのマージコミットのバージョンを決めてタグとGitHub Releaseを作成する。利用側は40桁のコミットSHAに固定する。
