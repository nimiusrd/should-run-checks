# Should Run Checks

変更されたファイルとworkflowの`with`に指定したスキップルールを照合し、CIのチェックを実行する必要があるか判定します。
TypeScriptで実装し、コンパイル済みJavaScriptを同梱するNode.js 24 Actionです。実行時の外部パッケージや設定ファイル用パーサはありません。

## 使い方

Actionのサポート対象はUbuntuランナーです。`runs-on: ubuntu-latest`の判定専用ジョブで実行し、後続のチェックにはジョブ出力を渡してください。後続のチェックはmacOS・Windowsでも実行できます。

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
      # 移行版のリリース後、そのタグが指す40桁のコミットSHAに置き換えてください。
      - uses: nimiusrd/should-run-checks@<40桁のコミットSHA>
        id: scope
        with:
          skip-extensions: |
            .md
            .txt
          skip-directories: |
            mockups
            design/drafts
          always-run-files: |
            docs/generated/api.md
  test:
    needs: scope
    if: ${{ always() && needs.scope.outputs.run_checks != 'false' }}
    runs-on: ubuntu-latest
    steps:
      - run: echo 'ここでプロジェクトのチェックを実行'
```

設定ファイルは不要です。各入力は任意で、未指定または空文字列の場合は対象なしになります。`with`全体を省略すれば、Markdownを含め変更されたファイルがあればチェックを実行します。

| 入力 | 用途 |
| --- | --- |
| `skip-extensions` | この拡張子のファイルだけならスキップ |
| `skip-directories` | このディレクトリ配下の変更だけならスキップ |
| `always-run-files` | スキップ条件より優先して実行するファイル |

各入力は**1行に1つ**指定します。空行と各行の前後の空白は無視します。カンマ区切り、JSON配列、YAML配列ではなく、上例の`|`による複数行文字列を使ってください。内部の空白や日本語は使用できます。改行や前後の空白を含む名前をルールへ指定することはできません。

拡張子は`.`から始め、ディレクトリとファイルはリポジトリルートからの相対パスを`/`区切りで指定します。大文字小文字を区別します。`./`・末尾の`/`・globは使いません。

呼び出し元でPython・Node.jsのセットアップや`npm install`は不要です。GitHub Actionsが用意するNode.js 24で同梱の`dist/index.js`を実行し、呼び出し元のPATHは変更しません。Gitと比較対象の履歴が必要です。

## 判定

- `always-run-files`はスキップ条件より優先します。スキップ対象外のファイルが1つでもあれば`run_checks=true`を返します。
- PRはmerge-baseからの差分、pushはイベントの`before`と`after`の差分を使います。削除とリネーム前後の両パスを判定します。
- 全変更がスキップ対象なら`false`、差分がない場合も`false`です。初回pushとPR・push以外のイベントでは`true`です。
- 入力やGit比較に失敗した場合は`true`を出力してActionも失敗します。利用側は上例の`always()`と`!= 'false'`で、判定失敗時にもチェックを省略しないようにします。
- 出力`reason`とActions Summaryにも判定理由を記録します。値は`changed-files`・`skip-only`・`no-changes`・`initial-push`・`unsupported-event`・`error`です。

## 設定ファイル方式からの移行

この移行版では、Python Composite ActionとTOML・JSON設定ファイルの読み込みを廃止します。旧リリースのv0.3.0は設定ファイル方式のままです。

| 旧設定キー | 新しい`with`入力 |
| --- | --- |
| `skipExtensions` | `skip-extensions` |
| `skipDirectories` | `skip-directories` |
| `alwaysRunFiles` | `always-run-files` |

配列の各要素を入力の各行へ移し、`config-path`を削除してください。`config-path`に値を指定すると`run_checks=true`と`reason=error`を出力して失敗します。設定ファイルは読み込みません。暗黙に既定の設定ファイルを使っていた場合も、ルールを`with`へ移してください。

## 開発

Node.js 24とGitを使います。開発依存はTypeScriptコンパイラとNode.jsの型定義だけで、`package-lock.json`で固定します。テストはNode.js標準のテストランナーを使います。

```bash
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . npm ci
devcontainer exec --workspace-folder . npm run build
devcontainer exec --workspace-folder . npm test
devcontainer exec --workspace-folder . npm run check
git diff --check
```

ソースを変更したら`npm run build`で生成する`dist/index.js`もコミットしてください。テストは配布JavaScriptに対して実行し、CIでは再ビルドによる差分がないことも検証します。CIはUbuntuで、呼び出し元のセットアップ前にActionの出力とPATHが変わらないことを確認します。

### Codexアプリのローカル環境

DockerとDev Container CLIを利用できる状態にして、Dockerを起動してください。Codex用の設定は`.codex/environments/environment.toml`に保存しています。
既存のPython用コンテナから移行する場合は、`devcontainer up --workspace-folder . --remove-existing-container`で作り直してください。

- 「コンテナ起動」: Dev Containerを起動します。
- 「テスト」: 同梱JavaScriptのテストを実行します。ソース変更後は先にビルドしてください。
- 「提出前チェック」: 依存インストール、ビルド、テスト、型・構文チェックと`git diff --check`を実行します。

## リリース

バージョン更新と提出前チェックを済ませ、`main`の対象コミットでCIが成功したことを確認してからタグとGitHub Releaseを作成します。利用側はタグが指す40桁のコミットSHAに固定してください。

具体的なコマンド、リリースノートに含める内容、公開後の確認は[リリース手順](RELEASE.md)にまとめています。

[MIT License](LICENSE)
