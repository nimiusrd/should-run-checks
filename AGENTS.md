# 開発ルール

- 日本語で記述・回答する。
- Python 3.11以降の標準ライブラリだけで実装する。外部Pythonパッケージやnpm依存を追加しない。Action内でPython 3.13を準備し、呼び出し元のPATHを変更しない。
- プロジェクトのコマンドは `devcontainer exec --workspace-folder . <command>` で実行する。Git操作はホストで行う。
- 提出前に `python -m unittest discover -s tests -v`、`python -m compileall -q should_run_checks.py tests`、`git diff --check` を確認する。
- TOMLは標準の`tomllib`で読む。JSONは標準の`json`で読めるが、YAMLの独自パーサは実装しない。
- 判定できない場合にチェックを省略しない。設定不備やGitの失敗を `run_checks=false` に変換しない。
- 設定は利用側のリポジトリに置く。特定プロジェクトのディレクトリ名を実装へ埋め込まない。
- リリースはCIが成功したコミットにタグを付ける。利用側は40桁のコミットSHAに固定する。
