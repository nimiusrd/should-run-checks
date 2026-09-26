# Should Run Checks

変更されたファイルとスキップルールを照合し、CIのチェックを実行する必要があるか判定します。
Python標準ライブラリだけで実装し、TOMLを`tomllib`で読み込みます。外部Pythonパッケージ、npm依存、バンドル生成はありません。

## 使い方

利用するリポジトリに`.github/ci-skip-rules.toml`を作成します。

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

## 開発

Python 3.11以降とGitを使います。テストも標準の`unittest`で実行できます。

```bash
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . python -m unittest discover -s tests -v
devcontainer exec --workspace-folder . python -m compileall -q should_run_checks.py tests
```

Linux・macOS・Windowsでテストし、Pythonセットアップを呼び出し元に置かないActionの実行もCIで確認します。

[MIT License](LICENSE)
