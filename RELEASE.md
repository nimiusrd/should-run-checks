# リリース手順

このActionは、ビルド済みの`dist/index.js`を含むGitコミットをタグで配布し、GitHub Releaseで変更内容を案内します。`package.json`は`private: true`で、npmへの公開は行いません。リリース専用のworkflowはなく、タグとReleaseは以下の手順で作成します。

作業はリポジトリルートで行います。ローカルのnpmコマンドはDev Container内、GitとGitHub CLI（`gh`）の操作はホストで実行します。`gh`はリポジトリへの書き込み権限があるアカウントで認証しておきます。各コマンドが失敗した場合は原因を解消し、次の段階へ進みません。

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

`--no-git-tag-version`を指定し、CIの確認前にコミットやタグを自動作成しないようにします。

バージョン更新、ソースの変更、生成した`dist/index.js`、必要なREADMEの変更をコミットし、PRのCI成功を確認して`main`へ取り込みます。ビルドで`dist/index.js`が変わった場合は、その変更も必ず含めてください。

現在の移行版は、旧`v0.3.0`のPython Composite Actionと設定ファイル方式からの互換性を壊す変更を含みます。新しいバージョンで公開し、`v0.3.0`を付け直さないでください。リリースノートには以下を含めます。

- TypeScript実装・Node.js 24 Actionへの移行と、ビルド済みJavaScriptの同梱。
- TOML・JSON設定ファイルの廃止と、`skip-extensions`・`skip-directories`・`always-run-files`への移行。各入力は1行に1つ指定すること。
- `config-path`に値を指定するとエラーになること。
- 判定用ジョブのサポート対象はUbuntuであることと、利用側でPython・Node.jsのセットアップが不要であること。
- 公開対象の40桁のコミットSHAと、[READMEの移行方法](README.md#設定ファイル方式からの移行)へのリンク。

## 2. 公開するコミットを固定する

作業ツリーに未コミットの変更がないことを`git status --short`で確認します。その後、最新の`main`とタグを取得し、公開対象のSHAを保存します。以降のコマンドは同じシェルで実行します。後から`main`が進んでも、保存した`release_sha`を使います。

```bash
git status --short
git fetch origin main --tags
release_sha="$(git rev-parse refs/remotes/origin/main)"
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

移行版の初回リリースでは、READMEの利用例にあるSHAのプレースホルダーも公開済みの値へ置き換え、別のPRで更新します。公開後に不具合が見つかった場合は、修正コミットのCIを確認して新しいバージョンを公開してください。利用側を戻す場合は、直前の動作確認済みSHAへ戻し、過去のタグは付け直しません。
