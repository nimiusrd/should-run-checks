# リリース手順

このActionは、ビルド済みの`dist/index.js`を含むGitコミットをタグで配布し、GitHub Releaseで変更内容を案内します。`package.json`は`private: true`で、npmへの公開は行いません。リリース専用のGitHub Actions workflowは置かず、タグとReleaseはCursor Automationが作成します。

作業はリポジトリルートで行います。手順1でバージョンを更新したpull requestをデフォルトブランチへマージすると、Cursor Automationが手順2から手順5を実行します。手元で公開する場合も同じコマンドを使い、同じタグを二重に作りません。手順6は公開後の別のpull requestです。

ローカルのnpmコマンドはDev Container内で実行します。Cursor Cloud AgentとAutomationではDev Containerを使わず、Node.js 24で同じnpmコマンドを直接実行します。GitとGitHub CLI（`gh`）はホストで実行します。タグのpushはGitの認証、Releaseの作成は`gh`の認証を使います。`gh`がReleaseを作成できない場合は、Cloud Agentのシークレット`GH_TOKEN`または`GITHUB_TOKEN`にcontentsの書き込みができるトークンを設定します。各コマンドが失敗した場合は原因を解消し、次の段階へ進みません。

## Cursor Automationで公開する

AutomationはCursorアカウント側の設定です。このリポジトリのファイルだけでは作成されないため、[cursor.com/automations](https://cursor.com/automations)で保存します。

- 名前: Should Run Checksのリリース
- トリガー: Pull request merged
- 対象リポジトリ: `nimiusrd/should-run-checks`
- Pull requestを作成するツール: 無効
- メモリ: 無効

プロンプトは次のとおりです。

```text
nimiusrd/should-run-checks で、デフォルトブランチへマージされた pull request を RELEASE.md の手順2から手順5だけ実行して公開する。手順1のバージョン更新と手順6の利用側更新はしない。コード、package.json、package-lock.json、READMEは変更しない。pull requestは開かず、別ブランチへもpushしない。既存タグは移動も削除もしない。失敗したコマンドの次へ進まない。

1. マージ先がデフォルトブランチであることを確認する。違う場合、またはマージされた pull request がない場合は何も作らず終了する。
2. トリガーが示すマージコミットの40桁 SHA を release_sha にする。短い SHA や、その後に進んだブランチ先端は使わない。手順2の origin/main から SHA を取り出すコマンドは実行しない。
3. RELEASE.md の手順2の共有コマンドに従い、release_sha の package.json と package-lock.json の version が一致することを確認する。タグ名は v にその version を付けたものにする。不一致、または X.Y.Z でない場合は何も作らず終了する。
4. 同じ名前のタグが別のコミットを指している場合は何も作らず終了する。v0.3.0 を付け直さない。タグが release_sha を指し、GitHub Release も既にある場合は終了する。タグが release_sha を指していて Release だけがない場合は、タグを作り直さず手順5の Release 作成だけを行う。
5. タグがまだない場合は、RELEASE.md の手順3に従い、ci.yml の CI が release_sha へのデフォルトブランチ push として成功するまで待つ。実行が見つからない、失敗した、または headSha、status、conclusion が手順3の条件を満たさない場合は、タグも GitHub Release も作らず終了する。
6. タグがまだない場合は、RELEASE.md の手順4に従い、release_sha へ注釈付きタグを作成してそのタグだけを push する。タグが指すコミット SHA が release_sha と一致することを確認してから先へ進む。
7. RELEASE.md の手順5に従い、日本語のリリースノートを --verify-tag で GitHub Release として公開する。--target やブランチ名でタグを作らない。配布アセットは付けず、npm へも公開しない。
   公開する履歴が設定ファイル方式の v0.3.0 から TypeScript と workflow 入力への移行を含む場合は、手順1に列挙されたリリースノートの項目を含める。それ以外は直前のリリースタグからの変更を書く。成功した CI の URL と release_sha を本文に含める。
8. Release の URL と、利用側が固定する40桁のコミット SHA を結果に残す。タグオブジェクト自身の SHA は案内しない。
```

## 1. リリース用の変更をPRにまとめる

次のバージョンを決め、`package.json`と`package-lock.json`を同時に更新します。以下の`0.4.0`は例です。タグ名はパッケージのバージョンに`v`を付けます。

ローカルではDev Containerで実行します。

```bash
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . npm version 0.4.0 --no-git-tag-version
devcontainer exec --workspace-folder . npm ci
devcontainer exec --workspace-folder . npm run build
devcontainer exec --workspace-folder . npm test
devcontainer exec --workspace-folder . npm run check
git diff --check
```

Cursor Cloud AgentではDev Containerを使わず、同じnpmコマンドを直接実行します。

```bash
npm version 0.4.0 --no-git-tag-version
npm ci
npm run build
npm test
npm run check
git diff --check
```

`--no-git-tag-version`を指定し、CIの確認前にコミットやタグを自動作成しないようにします。Automationはここでバージョンを決めません。

バージョン更新、ソースの変更、生成した`dist/index.js`、必要なREADMEの変更をコミットし、PRのCI成功を確認して`main`へ取り込みます。ビルドで`dist/index.js`が変わった場合は、その変更も必ず含めてください。

現在の移行版は、旧`v0.3.0`のPython Composite Actionと設定ファイル方式からの互換性を壊す変更を含みます。新しいバージョンで公開し、`v0.3.0`を付け直さないでください。リリースノートには以下を含めます。

- TypeScript実装・Node.js 24 Actionへの移行と、ビルド済みJavaScriptの同梱。
- TOML・JSON設定ファイルの廃止と、`skip-extensions`・`skip-directories`・`always-run-files`への移行。各入力は1行に1つ指定すること。
- `config-path`に値を指定するとエラーになること。
- 判定用ジョブのサポート対象はUbuntuであることと、利用側でPython・Node.jsのセットアップが不要であること。
- 公開対象の40桁のコミットSHAと、[READMEの移行方法](README.md#設定ファイル方式からの移行)へのリンク。

## 2. 公開するコミットを固定する

Automationは、トリガーが示すマージコミットの40桁を`release_sha`にします。手元で公開する場合は、作業ツリーに未コミットの変更がないことと、公開したいコミットが`origin/main`の先端であることを確認してから、そのSHAを保存します。

```bash
git status --short
git fetch origin main --tags
release_sha="$(git rev-parse refs/remotes/origin/main)"
```

以降は同じシェルで実行します。後からブランチ先端が進んでも、保存した`release_sha`だけを使います。

```bash
git fetch origin "$release_sha" --tags
package_version="$(git show "${release_sha}:package.json" | node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).version')"
lock_version="$(git show "${release_sha}:package-lock.json" | node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).version')"
test "$package_version" = "$lock_version"
printf '%s\n' "$package_version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'
release_tag="v${package_version}"
git show --no-patch --format=fuller "$release_sha"
git show "${release_sha}:package.json"
git show "${release_sha}:package-lock.json"
```

対象コミットに意図した変更が含まれることを確認します。両ファイルの`version`が一致しない、または`X.Y.Z`でない場合は終了します。

同名タグが別のコミットを指している場合は、タグを残したまま終了します。そのコミットを公開するには、手順1で新しいバージョンをマージします。

```bash
git tag --list "$release_tag"
git ls-remote --tags origin "refs/tags/${release_tag}" "refs/tags/${release_tag}^{}"
existing_sha="$(
  git ls-remote --tags origin "refs/tags/${release_tag}" "refs/tags/${release_tag}^{}" |
    awk '/\^\{\}$/ { peeled=$1 } !/\^\{\}$/ { direct=$1 } END { if (peeled != "") print peeled; else print direct }'
)"
if [ -n "$existing_sha" ] && [ "$existing_sha" != "$release_sha" ]; then
  echo "タグ ${release_tag} は ${existing_sha} を指しています"
  exit 0
fi
```

## 3. 対象コミットのCI成功を確認する

手順2で終了しなかった場合に確認します。[CI](.github/workflows/ci.yml)は`main`へのpush、PR、手動実行が対象で、タグのpushでは実行されません。PRでの成功に加えて、公開対象の`main`のコミットに対するCI成功を確認します。

```bash
release_ci_run_id="$(gh run list --repo nimiusrd/should-run-checks \
  --workflow ci.yml --branch main --event push --commit "$release_sha" \
  --limit 1 --json databaseId --jq '.[0].databaseId // empty')"
test -n "$release_ci_run_id"
gh run watch "$release_ci_run_id" --repo nimiusrd/should-run-checks --exit-status
gh run view "$release_ci_run_id" --repo nimiusrd/should-run-checks \
  --json headSha,status,conclusion,url
```

実行が見つからない場合や失敗した場合はタグを作成しません。最後の出力が`headSha = release_sha`、`status = completed`、`conclusion = success`であることを確認します。

CIでは、Node.jsのセットアップ前に同梱Actionを実行し、出力とPATHの不変を確認します。その後、Node.js 24で`npm ci`、ビルド、再ビルドによる`dist/index.js`の差分なし、テスト、型・構文チェック、`git diff --check`を検証します。

## 4. 確認したSHAにタグを付ける

既存タグは移動、上書き、削除をしません。手順2で`existing_sha`が空のときだけ、CIが成功したSHAを明示して注釈付きタグを作成し、そのタグだけをpushします。`release_sha`を指すタグが既にある場合は、この作成を飛ばして手順5へ進みます。

```bash
if [ -z "$existing_sha" ]; then
  git tag -a "$release_tag" "$release_sha" -m "$release_tag"
  git push origin "refs/tags/${release_tag}"
fi
git rev-parse "${release_tag}^{commit}"
git ls-remote --tags origin "refs/tags/${release_tag}" "refs/tags/${release_tag}^{}" |
  awk '/\^\{\}$/ { peeled=$1 } !/\^\{\}$/ { direct=$1 } END { if (peeled != "") print peeled; else print direct }'
```

最後の2つの出力に含まれるコミットSHAが、両方とも`release_sha`と一致することを確認します。注釈付きタグ自身のSHAではなく、`^{commit}`で取得したコミットSHAを利用側へ案内します。

## 5. GitHub Releaseを公開する

変更内容、互換性を壊す変更、移行方法、成功したCIのURL、`release_sha`を日本語のリリースノートに記載し、ホスト上のMarkdownファイルへ保存します。`release_notes_file`には、そのファイルのパスを指定してください。

```bash
if gh release view "$release_tag" --repo nimiusrd/should-run-checks >/dev/null 2>&1; then
  gh release view "$release_tag" --repo nimiusrd/should-run-checks
  exit 0
fi
release_notes_file=/tmp/should-run-checks-release-notes.md
gh release create "$release_tag" --repo nimiusrd/should-run-checks \
  --verify-tag --title "$release_tag" --notes-file "$release_notes_file"
gh release view "$release_tag" --repo nimiusrd/should-run-checks
```

`--verify-tag`でリモートに既存のタグがあることを必須にし、Release作成時に最新の`main`へタグが自動作成されるのを防ぎます。Releaseのタグとリリースノートを確認します。Actionの実行ファイルはタグ先のリポジトリに含まれているため、別の配布アセットは不要です。

## 6. 利用側を更新する

利用側のworkflowは、タグ名ではなく`release_sha`の40桁の値へ更新します。バージョン名はコメントで添えます。

```yaml
- uses: nimiusrd/should-run-checks@<40桁のコミットSHA> # v0.4.0
```

公開したAutomationは手順6を実行しません。移行版の初回リリースでは、READMEの利用例にあるSHAのプレースホルダーも公開済みの値へ置き換え、別のPRで更新します。公開後に不具合が見つかった場合は、修正コミットのCIを確認して新しいバージョンを公開してください。利用側を戻す場合は、直前の動作確認済みSHAへ戻し、過去のタグは付け直しません。
