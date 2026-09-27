# Should Run Checks

変更されたファイルとスキップルールを照合し、CIのチェックを実行する必要があるか判定します。
Python標準ライブラリだけで実装し、TOMLを`tomllib`で読み込みます。実行時の外部Pythonパッケージ、npm依存、バンドル生成はありません。開発用チェックにはmypyとRuffを使用します。

## 使い方

Actionのサポート対象はUbuntuランナーです。`runs-on: ubuntu-latest`の判定専用ジョブで実行し、後続のチェックにはジョブ出力を渡してください。後続のチェックはmacOS・Windowsでも実行できます。Action自体をmacOS・Windowsで実行する使い方はサポート対象外です。

利用するリポジトリに`.github/ci-skip-rules.toml`を作成します。初期設定ではスキップ対象を指定しません。`.md`を含め、変更されたファイルがあればチェックを実行します。

```toml
skipExtensions = []
skipDirectories = []
alwaysRunFiles = []
```

設定ファイルがない場合はエラーです。暗黙のスキップルールへのフォールバックは行いません。

スキップする対象がある場合だけ、明示的に指定してください。例えば、次の設定は`.md`と`mockups`配下を対象にします。

```toml
# この拡張子・ディレクトリだけの変更ならスキップ
skipExtensions = [".md"]
skipDirectories = ["mockups"]
# 上の条件より優先して実行するファイル
alwaysRunFiles = ["docs/generated/api.md"]
```

3つのキーは必須です。不要なルールには`[]`を指定します。拡張子は`.`から始め、ディレクトリとファイルはリポジトリルートからの相対パスを`/`区切りで指定します。大文字小文字を区別します。`./`・末尾の`/`・globは使いません。

```yaml
jobs:
  scope:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    outputs:
      run_checks: ${{ steps.scope.outputs.run_checks }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          fetch-depth: 0
      # 本番ではリリースタグが指す40桁のコミットSHAに固定してください。
      - uses: nimiusrd/should-run-checks@v0.3.0
        id: scope
        with:
          config-path: .github/ci-skip-rules.toml
  test:
    needs: scope
    if: ${{ always() && needs.scope.outputs.run_checks != 'false' }}
    runs-on: ubuntu-latest
    steps:
      - run: echo 'ここでプロジェクトのチェックを実行'
```

呼び出し元でPythonのセットアップは不要です。Composite Action内部でSHA固定の`actions/setup-python`がPython 3.13を準備し、その実行ファイルを直接起動します。`update-environment: false`により呼び出し元のPATHは変更しません。Gitはランナーに必要です。

Action内のセットアップはランナーのツールキャッシュを使い、必要に応じてPythonをダウンロードします。Python本体の準備までゼロにする構成ではありません。

## 判定

- `alwaysRunFiles`はスキップ条件より優先します。対象外のファイルが1つでもあれば`run_checks=true`を返します。
- PRはmerge-baseからの差分、pushはイベントの`before`と`after`の差分を使います。削除とリネーム前後の両パスを判定します。
- 全変更がスキップ対象なら`false`、差分がない場合も`false`です。初回pushとPR・push以外のイベントでは`true`です。
- 設定やGit比較に失敗した場合は`true`を出力してActionも失敗します。利用側は上例の`always()`と`!= 'false'`で、判定失敗時にもチェックを省略しないようにします。
- 出力`reason`とActions Summaryにも判定理由を記録します。値は`changed-files`・`skip-only`・`no-changes`・`initial-push`・`unsupported-event`・`error`です。

## v0.2からの移行

既定パスは`.github/ci-skip-rules.toml`です。外部ライブラリをなくすためYAML対応を終了しました。YAML設定を上のTOML形式へ置き換えてください。`.json`を明示した既存のJSON設定は標準の`json`で読み込めます。

## リリース

`main` へ pull request がマージされ、そのコミットで CI ワークフローが成功すると、Release ワークフローが `create_release.py` を実行します。成功したコミットそのものにセマンティックバージョンのタグと GitHub Release を作成します。本文の固定参照は40桁のコミットSHAです。利用側はそのSHAに Action を固定します。

`pyproject.toml` の `version` が最新のリリースタグより新しいときは、その値をタグにします。それ以外は最新タグから上げます。上げ幅は patch です。マージされた pull request に `release:minor` または `release:major` ラベルがあるときは、その単位で上げます。ラベルが両方ある場合はリリースしません。

同じコミットにリリースタグがある場合は新しく作りません。CI が成功していないコミットと、マージされた pull request がない push はリリースしません。

Cursor Automation の Pull request merged はマージ直後に起動します。タグを付けるのは、その後に CI が成功してから実行する `create_release.py` です。同じ条件で繰り返してもタグは一つです。確認だけ行う場合は `python3 create_release.py --dry-run` を使います。

## 開発

Python 3.11以降とGitを使います。テストも標準の`unittest`で実行できます。
Dev Containerにuv 0.12.19を組み込み、作成時に`uv sync --locked`で開発環境を準備します。mypy・Ruffは`pyproject.toml`のdevグループで管理し、推移的依存関係も含めて`uv.lock`に固定します。既存コンテナは再ビルドしてuvを導入してください。依存関係の同期とチェックには次のコマンドを使います。

```bash
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . uv sync --locked
devcontainer exec --workspace-folder . uv run --locked python -m unittest discover -s tests -v
devcontainer exec --workspace-folder . uv run --locked python -m compileall -q should_run_checks.py create_release.py tests
devcontainer exec --workspace-folder . uv run --locked mypy
devcontainer exec --workspace-folder . uv run --locked ruff check .
devcontainer exec --workspace-folder . uv run --locked ruff format --check .
git diff --check
```

`pyproject.toml`で本体とテストにmypyのstrictチェックを設定し、Ruffでlint・import順序・Python 3.11向けの記法とフォーマットを確認します。整形する場合は`devcontainer exec --workspace-folder . uv run --locked ruff format .`を実行してください。設定項目は[mypy公式ドキュメント](https://mypy.readthedocs.io/en/stable/config_file.html)と[Ruff公式ドキュメント](https://docs.astral.sh/ruff/configuration/)を参照してください。

CIはUbuntuのPython 3.11・3.13の2ジョブでテストとmypy・Ruffのチェックを実行します。3.11は最低対応バージョン、3.13はActionで使うバージョンの確認用です。3.13のジョブでは、テスト用Pythonや開発用ツールのセットアップ前にActionを実行し、有効な出力が得られることと呼び出し元のPATHが変わらないことも確認します。

### Codexアプリのローカル環境

ホストでDockerとDev Container CLIを利用できる状態にして、Dockerを起動してください。
Codex用の設定は`.codex/environments/environment.toml`に保存しています。
新しいworktreeのセットアップではDev Containerを起動し、uvのバージョンを確認して開発環境を同期します。
既存のチェックアウトでは「コンテナ起動」アクションを実行してください。

- 「テスト」: コンテナ内でユニットテストを実行します。
- 「提出前チェック」: コンテナ内でユニットテスト・構文チェック・mypy・Ruffを順に実行し、ホストで`git diff --check`を確認します。失敗した場合はそこで停止します。

プロジェクトの実行コマンドには`devcontainer exec --workspace-folder .`を使い、Git操作はホストで行います。
設定方法の詳細は[Codexのローカル環境](https://learn.chatgpt.com/docs/environments/local-environment)を参照してください。

テストが`No space left on device`で失敗した場合は、Dockerの空き容量を確認してください。
一時的な検証には、コンテナの`/dev/shm`に空きがあれば次のコマンドを使えます。
これはDockerのディスク容量不足そのものを解消するものではありません。

```bash
devcontainer exec --workspace-folder . env TMPDIR=/dev/shm uv run --locked python -m unittest discover -s tests -v
```

[MIT License](LICENSE)
