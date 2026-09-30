const assert = require('node:assert/strict');
const { execFileSync, spawnSync } = require('node:child_process');
const { copyFileSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const { test } = require('node:test');
const { evaluateChanges, readInputs, shouldRunChecks } = require('../dist/index.js');

const INPUTS = {
  'INPUT_SKIP-EXTENSIONS': '.md',
  'INPUT_SKIP-DIRECTORIES': 'mockups',
  'INPUT_ALWAYS-RUN-FILES': '',
};
const CONFIG = readInputs(INPUTS);

// 実行時依存なしで、配布するJavaScript自体を検証する。
test('入力未指定ではMarkdownを含む全変更を実行する', () => {
  const config = readInputs({});
  assert.equal(shouldRunChecks(['README.md'], config), true);
  assert.equal(shouldRunChecks([], config), false);
});

test('改行区切り、CRLF、空行、前後の空白を扱う', () => {
  assert.deepEqual(readInputs({
    'INPUT_SKIP-EXTENSIONS': ' .md \r\n\n.txt\n',
    'INPUT_SKIP-DIRECTORIES': 'design drafts\n 日本語/資料\n',
    'INPUT_ALWAYS-RUN-FILES': 'docs/a#b.md\ndocs/a: b.md',
  }), {
    skipExtensions: ['.md', '.txt'],
    skipDirectories: ['design drafts', '日本語/資料'],
    alwaysRunFiles: ['docs/a#b.md', 'docs/a: b.md'],
  });
});

test('不正な拡張子・パス・旧設定入力を拒否する', () => {
  for (const extension of ['md', '.', '*.md', '.m/d', '.m\\d', '.md,.txt', '.md\r.txt']) {
    // カンマは拡張子に含められるため、リスト区切りとしては解釈しない。
    if (extension === '.md,.txt') {
      assert.deepEqual(readInputs({ 'INPUT_SKIP-EXTENSIONS': extension }).skipExtensions, [extension]);
      continue;
    }
    assert.throws(() => readInputs({ 'INPUT_SKIP-EXTENSIONS': extension }));
  }
  for (const key of ['INPUT_SKIP-DIRECTORIES', 'INPUT_ALWAYS-RUN-FILES']) {
    for (const path of ['./docs', 'docs/', '/docs', 'docs//a', '../docs', '**/*.md', 'a\\b']) {
      assert.throws(() => readInputs({ [key]: path }));
    }
  }
  assert.throws(() => readInputs({ 'INPUT_CONFIG-PATH': 'rules.toml' }), /config-path/);
});

test('全変更がスキップ対象の場合だけ省略する', () => {
  for (const files of [[], ['README.md'], ['AGENTS.md', 'docs/api.md'],
    ['.hidden.md', 'mockups/nested/app.js', 'docs/a file\nwith newline.md']]) {
    assert.equal(shouldRunChecks(files, CONFIG), false);
  }
  for (const path of ['src/app.ts', 'package.json', '.github/workflows/ci.yml', 'docs/chart.svg',
    'mockups-other/index.html', 'src/mockups/app.js', 'README.MD', 'docs/a.mdx']) {
    assert.equal(shouldRunChecks(['README.md', path, 'mockups/app.js'], CONFIG), true);
  }
});

test('複数ルールと必須ファイルの優先を扱う', () => {
  const config = readInputs({
    'INPUT_SKIP-EXTENSIONS': '.md\n.txt',
    'INPUT_SKIP-DIRECTORIES': 'mockups\ndesign/drafts',
    'INPUT_ALWAYS-RUN-FILES': 'docs/api.md\nmockups/important.md',
  });
  assert.equal(shouldRunChecks(['notes.txt', 'design/drafts/nested/screen.svg'], config), false);
  for (const path of config.alwaysRunFiles) {
    assert.equal(shouldRunChecks([path], config), true);
    assert.equal(shouldRunChecks(['other/' + path], config), false);
  }
});

function fixture(t) {
  const temporary = mkdtempSync(join(tmpdir(), 'should-run-checks-'));
  t.after(() => rmSync(temporary, { recursive: true, force: true }));
  const workspace = join(temporary, 'repository with spaces');
  mkdirSync(workspace);
  const git = (...args) => execFileSync('git', ['-C', workspace, ...args], {
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, GIT_CONFIG_GLOBAL: process.platform === 'win32' ? 'NUL' : '/dev/null', GIT_CONFIG_NOSYSTEM: '1' },
  }).trim();
  const write = (path, content = 'fixture\n') => {
    const target = join(workspace, path);
    mkdirSync(require('node:path').dirname(target), { recursive: true });
    writeFileSync(target, content);
  };
  const commit = () => {
    git('add', '.');
    git('-c', 'commit.gpgsign=false', 'commit', '-m', 'fixture');
    return git('rev-parse', 'HEAD');
  };
  git('init', '-b', 'main');
  git('config', 'user.name', 'CI fixture');
  git('config', 'user.email', 'fixture@example.invalid');
  write('src/app.ts');
  write('README.md');
  const base = commit();
  const evaluate = (head, eventName = 'push', compareBase = base) => evaluateChanges(workspace, eventName,
    eventName === 'push' ? { before: compareBase, after: head } :
      { pull_request: { base: { sha: compareBase }, head: { sha: head } } }, CONFIG);
  const execute = (event, inputs = INPUTS, eventName = 'push', rawEvent) => {
    const eventPath = join(temporary, 'event.json');
    const output = join(temporary, 'output');
    const summary = join(temporary, 'summary');
    writeFileSync(eventPath, rawEvent ?? JSON.stringify(event));
    writeFileSync(output, '');
    writeFileSync(summary, '');
    const entry = join(temporary, 'action.cjs');
    copyFileSync(resolve(__dirname, '../dist/index.js'), entry);
    const env = { ...process.env };
    for (const key of Object.keys(env)) if (key.startsWith('INPUT_')) delete env[key];
    const processResult = spawnSync(process.execPath, [entry], {
      cwd: temporary, encoding: 'utf8',
      env: { ...env, ...inputs, GITHUB_WORKSPACE: workspace, GITHUB_EVENT_PATH: eventPath,
        GITHUB_EVENT_NAME: eventName, GITHUB_OUTPUT: output, GITHUB_STEP_SUMMARY: summary },
    });
    return { ...processResult, output: readFileSync(output, 'utf8'), summary: readFileSync(summary, 'utf8') };
  };
  return { workspace, git, write, commit, base, evaluate, execute };
}

test('pushとPRでドキュメント・コード・空差分を判定する', t => {
  const f = fixture(t);
  f.write('docs/a file.md');
  const docs = f.commit();
  f.write('src/a file.ts');
  const code = f.commit();
  for (const event of ['push', 'pull_request']) {
    assert.equal(f.evaluate(docs, event).runChecks, false);
    assert.equal(f.evaluate(code, event).runChecks, true);
    assert.equal(f.evaluate(code, event, code).reason, 'no-changes');
  }
});

test('PRはmerge-baseからの差分で判定する', t => {
  const f = fixture(t);
  f.git('checkout', '-b', 'feature');
  f.write('docs/feature.md');
  const head = f.commit();
  f.git('checkout', 'main');
  f.write('src/base-only.ts');
  const base = f.commit();
  assert.equal(f.evaluate(head, 'pull_request', base).runChecks, false);
  assert.equal(f.evaluate(head, 'push', base).runChecks, true);
});

test('リネームの旧パスと削除したコードを判定する', t => {
  const f = fixture(t);
  mkdirSync(join(f.workspace, 'mockups'));
  renameSync(join(f.workspace, 'src/app.ts'), join(f.workspace, 'mockups/app.ts'));
  const result = f.evaluate(f.commit());
  assert.equal(result.runChecks, true);
  assert.equal(result.changedFileCount, 2);
  rmSync(join(f.workspace, 'mockups/app.ts'));
  assert.equal(f.evaluate(f.commit()).runChecks, true);
});

test('改行と日本語を含むパスを判定する', { skip: process.platform === 'win32' }, t => {
  const f = fixture(t);
  f.write('docs/日本語\nfile.md');
  assert.equal(f.evaluate(f.commit()).runChecks, false);
  f.write('src/日本語\nfile.ts');
  assert.equal(f.evaluate(f.commit()).runChecks, true);
});

test('初回pushと対象外イベントではチェックを実行する', () => {
  for (const length of [40, 64]) {
    assert.deepEqual(evaluateChanges('missing', 'push', { before: '0'.repeat(length) }, CONFIG),
      { runChecks: true, reason: 'initial-push' });
  }
  for (const eventName of ['workflow_dispatch', 'pull_request_target']) {
    assert.deepEqual(evaluateChanges('missing', eventName, {}, CONFIG),
      { runChecks: true, reason: 'unsupported-event' });
  }
});

test('不正なSHA・不足した履歴・イベント構造は失敗する', t => {
  const f = fixture(t);
  for (const sha of [undefined, '--output=bad', 'f'.repeat(40), 'a'.repeat(41)]) {
    assert.throws(() => f.evaluate(sha));
  }
  for (const event of [null, [], {}, { pull_request: {} }]) {
    assert.throws(() => evaluateChanges(f.workspace, 'pull_request', event, CONFIG));
  }
});

test('配布JavaScript単体で入力・出力・Summaryを扱う', t => {
  const f = fixture(t);
  f.write('docs/example.md');
  const event = { before: f.base, after: f.commit() };
  const result = f.execute(event);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.output, 'run_checks=false\nreason=skip-only\n');
  assert.match(result.summary, /skip-only/);
  assert.match(result.summary, /変更パス数: 1/);
  const defaultResult = f.execute(event, {});
  assert.equal(defaultResult.status, 0, defaultResult.stderr);
  assert.equal(defaultResult.output, 'run_checks=true\nreason=changed-files\n');
  const override = f.execute(event, { ...INPUTS, 'INPUT_ALWAYS-RUN-FILES': 'docs/example.md' });
  assert.equal(override.status, 0, override.stderr);
  assert.match(override.output, /reason=changed-files/);
});

test('入力不備・Git失敗・イベントJSON不備はtrueを出力して失敗する', t => {
  const f = fixture(t);
  for (const [event, inputs, raw] of [
    [{ before: '0'.repeat(40) }, { 'INPUT_SKIP-EXTENSIONS': '*.md' }],
    [{ before: f.base, after: 'f'.repeat(40) }, INPUTS],
    [{ before: '0'.repeat(40) }, { 'INPUT_CONFIG-PATH': 'rules.toml' }],
    [{}, INPUTS, '{'],
    [null, INPUTS],
  ]) {
    const result = f.execute(event, inputs, 'push', raw);
    assert.notEqual(result.status, 0);
    assert.equal(result.output, 'run_checks=true\nreason=error\n');
    assert.match(result.stderr, /::error::/);
  }
});

test('パス先頭のBOM文字を消さずにディレクトリ条件を照合する', t => {
  const f = fixture(t);
  f.write('\ufeffmockups/app.ts');
  assert.equal(f.evaluate(f.commit()).runChecks, true);
});

test('エラーの改行とパーセントをworkflowコマンド用にエスケープする', t => {
  const f = fixture(t);
  const result = f.execute({ before: '0'.repeat(40) }, { 'INPUT_SKIP-EXTENSIONS': 'bad%value' });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /bad%25value/);
});
