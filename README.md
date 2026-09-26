# Should Run Checks

変更されたファイルとJSONのスキップルールを照合し、CIのチェックを実行する必要があるか判定するGitHub Actionです。
ドキュメントだけの変更ではテストを省略し、コードを含む変更では実行する、といった設定を利用側で管理できます。

Node.js 24のJavaScript Actionで、実行時のnpm依存やビルド成果物はありません。利用側の`setup-node`や`npm install`も不要です。

## 使い方

利用するリポジトリに`.github/ci-skip-rules.json`を作成します。

```json
{
  "skipExtensions": [".md"],
  "skipDirectories": ["mockups"],
  "alwaysRunFiles": ["docs/generated/api.md"]
}
```

| 設定              | 意味                                                                 |
| ----------------- | -------------------------------------------------------------------- |
| `skipExtensions`  | 指定した拡張子で終わるパスをスキップ。ルートや隠しディレクトリも対象 |
| `skipDirectories` | 指定ディレクトリ配下を再帰的にスキップ                               |
| `alwaysRunFiles`  | 上のスキップ条件より優先してチェックを実行するファイル               |

3つのキーはすべて必須です。不要なルールには空配列`[]`を指定します。拡張子は`.`から始め、パスはリポジトリルートからの相対パスを`/`区切りで指定します。大文字小文字を区別します。`./`・末尾の`/`・globは使いません。

この例では`README.md`と`mockups/screen.html`だけの変更はスキップし、`src/app.ts`や`docs/generated/api.md`を含む変更ではチェックを実行します。スキップ条件に当てはまらないパスが1つでもあれば実行します。

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  scope:
    runs-on: ubuntu-latest
    outputs:
      run_checks: ${{ steps.scope.outputs.run_checks }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          fetch-depth: 0
      # 本番では、リリースタグが指す40桁のコミットSHAに固定してください。
      - uses: nimiusrd/should-run-checks@v0.1.1
        id: scope
        with:
          config-path: .github/ci-skip-rules.json
  test:
    needs: scope
    if: ${{ always() && needs.scope.outputs.run_checks != 'false' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0
        with:
          node-version: 24
      - run: npm ci
      - run: npm test
```

ワークフローを`paths`で絞らず起動し、ジョブの`if`で省略する構成です。必須チェックに設定されたジョブにも結果を返せます。Action自身はジョブやチェックを停止せず、判定結果を返します。どのジョブを省略するかは利用側の`needs`と`if`で指定してください。

## 入出力

入力`config-path`は既定で`.github/ci-skip-rules.json`です。チェックアウトしたリポジトリからの相対パスを使い、JSONはそのチェックアウトの内容を読みます。

出力`run_checks`は文字列の`true`または`false`です。出力`reason`とActions Summaryには次の判定理由を記録します。

| `reason`            | `run_checks` | 判定                                             |
| ------------------- | ------------ | ------------------------------------------------ |
| `changed-files`     | `true`       | スキップ対象以外の変更がある                     |
| `skip-only`         | `false`      | 全変更がスキップ対象                             |
| `no-changes`        | `false`      | 比較対象間にファイル変更がない                   |
| `initial-push`      | `true`       | 初回pushで比較元がない                           |
| `unsupported-event` | `true`       | 手動実行など、push・PR以外のイベント             |
| `error`             | `true`       | 設定不備・コミット不足など。Action自体も失敗する |

## 差分とエラーの扱い

- PRはbaseとheadのmerge-baseからの差分、pushはイベントの`before`と`after`の差分を使います。
- 削除したパスも対象です。リネームは変更前後の両パスを判定するため、コードをスキップ対象へ移動してもチェックを実行します。
- Gitのローカル差分を使うため、ファイル数のAPIページングはありません。空白や改行を含むパスはNUL区切りで扱います。
- 必要な履歴は`actions/checkout`の`fetch-depth: 0`で取得してください。コミットが存在しない場合は失敗し、チェックを省略しません。
- 設定ファイルの欠落、JSONやルールの不備も失敗として報告します。前述の`always()`と`!= 'false'`により、判定ジョブに失敗しても後続のチェックを実行します。
- `pull_request_target`など権限の強いイベントをPRコードのチェックアウトと組み合わせないでください。通常の`pull_request`と`contents: read`で利用します。

## 開発

```bash
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . npm test
devcontainer exec --workspace-folder . npm run lint
devcontainer exec --workspace-folder . npm run format:check
```

Node.js標準のテストランナーで設定の判定、実際のGit履歴、Actionの入出力を検証します。`src/`をそのまま配布するためビルドは不要です。

リリースはCI成功を確認したコミットへバージョンタグを付けます。利用側ではそのコミットのSHAを固定してください。

## ライセンス

[MIT](LICENSE)
