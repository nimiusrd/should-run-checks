# Should Run Checks

変更されたファイルとYAMLまたはJSONのスキップルールを照合し、CIのチェックを実行する必要があるか判定するGitHub Actionです。
ドキュメントだけの変更ではテストを省略し、コードを含む変更では実行する、といった設定を利用側で管理できます。

Node.js 24のJavaScript Actionです。YAMLパーサは配布ファイルに同梱するため、利用側の`setup-node`や`npm install`は不要です。

## 使い方

利用するリポジトリに`.github/ci-skip-rules.yml`を作成します。YAMLでは設定の意図をコメントで残せます。

```yaml
# この拡張子・ディレクトリだけの変更ならスキップ
skipExtensions:
  - .md
skipDirectories:
  - mockups
# 上の条件より優先して実行するファイル
alwaysRunFiles:
  - docs/generated/api.md
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
      - uses: nimiusrd/should-run-checks@v0.2.0
        id: scope
        with:
          config-path: .github/ci-skip-rules.yml
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

入力`config-path`は既存の利用を維持するため、既定で`.github/ci-skip-rules.json`です。YAMLを使う場合は例のように`.yml`または`.yaml`のパスを明示します。拡張子が`.yml`・`.yaml`ならYAML、それ以外は従来どおりJSONとして読みます。チェックアウトしたリポジトリからの相対パスを指定してください。

YAMLのコメント、引用文字列、ブロック形式とインライン形式の配列に対応します。単一文書のマッピングを指定し、同名キーの重複や不正な型はエラーにします。空配列は`[]`を明記してください。

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
- 設定ファイルの欠落、YAML・JSONやルールの不備も失敗として報告します。前述の`always()`と`!= 'false'`により、判定ジョブに失敗しても後続のチェックを実行します。
- `pull_request_target`など権限の強いイベントをPRコードのチェックアウトと組み合わせないでください。通常の`pull_request`と`contents: read`で利用します。

## 開発

```bash
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . npm run build
devcontainer exec --workspace-folder . npm test
devcontainer exec --workspace-folder . npm run lint
devcontainer exec --workspace-folder . npm run format:check
```

Node.js標準のテストランナーで設定の判定、実際のGit履歴、Actionの入出力を検証します。`npm run build`でソースとYAMLパーサを`dist/`へ同梱し、配布物もコミットします。CIでは再ビルドした配布物に差分がないことと、`node_modules`を持たない一時ディレクトリでの動作も確認します。

リリースはCI成功を確認したコミットへバージョンタグを付けます。利用側ではそのコミットのSHAを固定してください。

## ライセンス

[MIT](LICENSE)
