import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, test } from 'node:test';
import { evaluateChanges, shouldRunChecks, validateConfig } from '../src/scope.mjs';

const config = { skipExtensions: ['.md'], skipDirectories: ['mockups'], alwaysRunFiles: [] };
const temporaryDirectories = [];
function tempDirectory() {
  const directory = mkdtempSync(join(tmpdir(), 'ci-skip-rules-'));
  temporaryDirectories.push(directory);
  return directory;
}
afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

for (const paths of [
  ['README.md'],
  ['AGENTS.md', 'docs/probability-model.md', '.agents/skills/test/SKILL.md', '.hidden.md'],
  ['mockups/index.html', 'mockups/nested/app.js', 'docs/space and\nnewline.md'],
  [],
]) {
  test(`スキップ対象だけなら実行しない: ${JSON.stringify(paths)}`, () => {
    assert.equal(shouldRunChecks(paths, config), false);
  });
}
for (const path of [
  'src/app.ts',
  'package.json',
  '.github/ci-skip-rules.json',
  'docs/chart.svg',
  'mockups-other/index.html',
  'src/mockups/app.js',
  'README.MD',
  'docs/a.mdx',
]) {
  test(`対象外が混ざる場合は実行する: ${path}`, () => {
    assert.equal(shouldRunChecks(['README.md', path, 'mockups/index.html'], config), true);
  });
}
test('利用側の設定だけでスキップする種類を追加できる', () => {
  const paths = ['notes.txt', 'design/drafts/nested/example.svg'];
  assert.equal(shouldRunChecks(paths, config), true);
  assert.equal(
    shouldRunChecks(paths, {
      ...config,
      skipExtensions: ['.md', '.txt'],
      skipDirectories: ['mockups', 'design/drafts'],
    }),
    false,
  );
});
test('明示ファイルは拡張子とディレクトリの両ルールより優先する', () => {
  const customized = { ...config, alwaysRunFiles: ['docs/api.md', 'mockups/important.md'] };
  for (const path of customized.alwaysRunFiles) {
    assert.equal(shouldRunChecks([path], customized), true);
    assert.equal(shouldRunChecks([`other/${path}`], customized), false);
  }
});
test('空のルールではすべての変更を実行対象にする', () => {
  const empty = { skipExtensions: [], skipDirectories: [], alwaysRunFiles: [] };
  assert.equal(shouldRunChecks(['README.md'], validateConfig(empty)), true);
});
test('未知のキー・不正な型・曖昧なパスを拒否する', () => {
  for (const invalid of [null, [], 'md', { ...config, skipExtension: ['.md'] }]) {
    assert.throws(() => validateConfig(invalid));
  }
  for (const key of Object.keys(config)) {
    for (const invalid of [undefined, '*.md', [null], ['']]) {
      assert.throws(() => validateConfig({ ...config, [key]: invalid }));
    }
  }
  for (const extension of ['md', '.', '*.md', '.m/d', '.m\\d']) {
    assert.throws(() => validateConfig({ ...config, skipExtensions: [extension] }));
  }
  for (const key of ['skipDirectories', 'alwaysRunFiles']) {
    for (const path of [
      './docs',
      'docs/',
      '/docs',
      'docs//test',
      '../docs',
      '**/*.md',
      'docs\\test',
    ]) {
      assert.throws(() => validateConfig({ ...config, [key]: [path] }));
    }
  }
});

function repository() {
  const workspace = tempDirectory();
  const git = (...args) =>
    execFileSync('git', ['-C', workspace, ...args], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1' },
    }).trim();
  git('init', '-b', 'main');
  git('config', 'user.name', 'CI fixture');
  git('config', 'user.email', 'fixture@example.invalid');
  const write = (path, content = 'fixture\n') => {
    mkdirSync(dirname(join(workspace, path)), { recursive: true });
    writeFileSync(join(workspace, path), content);
  };
  const commit = () => {
    git('add', '.');
    git('-c', 'commit.gpgsign=false', 'commit', '-m', 'fixture');
    return git('rev-parse', 'HEAD');
  };
  write('src/app.js');
  write('README.md');
  const base = commit();
  return { workspace, git, write, commit, base };
}
function evaluate(repo, head, eventName = 'push', base = repo.base) {
  const event =
    eventName === 'push'
      ? { before: base, after: head }
      : { pull_request: { base: { sha: base }, head: { sha: head } } };
  return evaluateChanges({ workspace: repo.workspace, config, eventName, event });
}
for (const eventName of ['push', 'pull_request']) {
  test(`${eventName}: Markdownのみ、コード混在、差分なしを実際のGitで判定する`, () => {
    const repo = repository();
    repo.write('docs/a file\nwith newline.md');
    const docs = repo.commit();
    assert.equal(evaluate(repo, docs, eventName).runChecks, false);
    repo.write('src/new file\nwith newline.js');
    const code = repo.commit();
    assert.equal(evaluate(repo, code, eventName).runChecks, true);
    assert.equal(evaluate(repo, code, eventName, code).reason, 'no-changes');
  });
}
test('PRはbaseブランチだけの変更を差分へ含めない', () => {
  const repo = repository();
  repo.git('checkout', '-b', 'feature');
  repo.write('docs/feature.md');
  const head = repo.commit();
  repo.git('checkout', 'main');
  repo.write('src/base-only.js');
  const base = repo.commit();
  assert.equal(evaluate(repo, head, 'pull_request', base).runChecks, false);
  assert.equal(evaluate(repo, head, 'push', base).runChecks, true);
});
test('コードを除外先へ移動した場合も、移動前の削除でチェックを実行する', () => {
  const repo = repository();
  mkdirSync(join(repo.workspace, 'mockups'));
  renameSync(join(repo.workspace, 'src/app.js'), join(repo.workspace, 'mockups/app.js'));
  const result = evaluate(repo, repo.commit());
  assert.equal(result.runChecks, true);
  assert.equal(result.changedFileCount, 2);
});
test('コードの削除を実行対象にする', () => {
  const repo = repository();
  rmSync(join(repo.workspace, 'src/app.js'));
  assert.equal(evaluate(repo, repo.commit()).runChecks, true);
});
test('初回pushと手動イベントでは比較を省略してチェックを実行する', () => {
  for (const [eventName, event, reason] of [
    ['push', { before: '0'.repeat(40) }, 'initial-push'],
    ['workflow_dispatch', {}, 'unsupported-event'],
    ['pull_request_target', {}, 'unsupported-event'],
  ]) {
    assert.deepEqual(evaluateChanges({ workspace: '/missing', config, eventName, event }), {
      runChecks: true,
      reason,
    });
  }
});
test('不足したSHAや取得していない履歴は失敗にする', () => {
  const repo = repository();
  assert.throws(() => evaluate(repo, undefined));
  assert.throws(() => evaluate(repo, '--output=bad'));
  assert.throws(() => evaluate(repo, 'f'.repeat(40)));
});

function runAction(repo, event, customConfig = config, configPath = '.github/ci-skip-rules.json') {
  const files = tempDirectory();
  const eventPath = join(files, 'event.json');
  const output = join(files, 'output');
  const summary = join(files, 'summary');
  writeFileSync(eventPath, JSON.stringify(event));
  if (customConfig !== null) repo.write(configPath, JSON.stringify(customConfig));
  const result = spawnSync(
    process.execPath,
    [fileURLToPath(new URL('../src/index.mjs', import.meta.url))],
    {
      cwd: files,
      encoding: 'utf8',
      env: {
        ...process.env,
        GITHUB_WORKSPACE: repo.workspace,
        GITHUB_EVENT_NAME: 'push',
        GITHUB_EVENT_PATH: eventPath,
        GITHUB_OUTPUT: output,
        GITHUB_STEP_SUMMARY: summary,
        'INPUT_CONFIG-PATH': configPath,
      },
    },
  );
  return {
    ...result,
    output: readFileSync(output, 'utf8'),
    summary: readFileSync(summary, 'utf8'),
  };
}
test('Actionは利用側の設定を読み、false出力とサマリーを生成する', () => {
  const repo = repository();
  repo.write('docs/example.md');
  const result = runAction(
    repo,
    { before: repo.base, after: repo.commit() },
    config,
    'custom/rules.json',
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.output, 'run_checks=false\nreason=skip-only\n');
  assert.match(result.summary, /skip-only/);
});
test('Actionの判定失敗は非ゼロ終了とtrue出力になる', () => {
  const repo = repository();
  for (const [event, rules, path] of [
    [{ before: repo.base, after: 'f'.repeat(40) }, config, 'config.json'],
    [{ before: repo.base, after: repo.base }, {}, 'config.json'],
    [{ before: repo.base, after: repo.base }, null, 'missing.json'],
  ]) {
    const result = runAction(repo, event, rules, path);
    assert.notEqual(result.status, 0);
    assert.equal(result.output, 'run_checks=true\nreason=error\n');
  }
});
