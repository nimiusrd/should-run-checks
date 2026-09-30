/** Node.js標準機能だけでworkflow入力とGit差分からCIの実行要否を判定する。 */
import { execFileSync } from 'node:child_process';
import { appendFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

export interface Config {
  skipExtensions: string[];
  skipDirectories: string[];
  alwaysRunFiles: string[];
}

export interface Result {
  runChecks: boolean;
  reason: 'changed-files' | 'skip-only' | 'no-changes' | 'initial-push' | 'unsupported-event' | 'error';
  changedFileCount?: number;
}

type Environment = Readonly<Record<string, string | undefined>>;

function lines(value: string | undefined): string[] {
  return (value ?? '').split(/\r?\n/).map(line => line.trim()).filter(Boolean);
}

export function readInputs(env: Environment): Config {
  if (env['INPUT_CONFIG-PATH']?.trim()) {
    throw new Error('config-pathは廃止しました。workflowのwithにルールを指定してください。');
  }
  const config: Config = {
    skipExtensions: lines(env['INPUT_SKIP-EXTENSIONS']),
    skipDirectories: lines(env['INPUT_SKIP-DIRECTORIES']),
    alwaysRunFiles: lines(env['INPUT_ALWAYS-RUN-FILES']),
  };
  for (const extension of config.skipExtensions) {
    if (!extension.startsWith('.') || extension.length < 2 || /[/\\*?\[\]{}!\r]/.test(extension)) {
      throw new Error(`skip-extensionsはドットから始まる拡張子を指定してください: ${extension}`);
    }
  }
  for (const key of ['skipDirectories', 'alwaysRunFiles'] as const) {
    for (const path of config[key]) {
      if (/[\\*?\[\]{}!\r]/.test(path) || path.split('/').some(part => ['', '.', '..'].includes(part))) {
        throw new Error(`${key}はglobを使わずリポジトリルートからの相対パスを指定してください: ${path}`);
      }
    }
  }
  return config;
}

export function shouldRunChecks(files: string[], config: Config): boolean {
  return files.some(path => {
    if (config.alwaysRunFiles.includes(path)) return true;
    if (config.skipDirectories.some(directory => path.startsWith(`${directory}/`))) return false;
    return !config.skipExtensions.some(extension => path.endsWith(extension));
  });
}

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('イベントはオブジェクトで指定してください。');
  }
  return value as Record<string, unknown>;
}

export function evaluateChanges(workspace: string, eventName: string, value: unknown, config: Config): Result {
  const event = object(value);
  let base: unknown;
  let head: unknown;
  let separator: string;
  if (eventName === 'pull_request') {
    const pr = object(event.pull_request);
    base = object(pr.base).sha;
    head = object(pr.head).sha;
    separator = '...';
  } else if (eventName === 'push') {
    base = event.before;
    head = event.after;
    if (typeof base === 'string' && /^(?:0{40}|0{64})$/.test(base)) {
      return { runChecks: true, reason: 'initial-push' };
    }
    separator = '..';
  } else {
    return { runChecks: true, reason: 'unsupported-event' };
  }
  for (const sha of [base, head]) {
    if (typeof sha !== 'string' || !/^(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})$/.test(sha)) {
      throw new Error('イベントに有効なbase/headコミットSHAがありません。');
    }
  }
  // 削除とリネーム前後の両パスを含め、空白・改行のあるパスもNUL区切りで保持する。
  const diff = execFileSync('git', [
    '-C', workspace, 'diff', '--no-renames', '--name-only', '-z', `${base}${separator}${head}`, '--',
  ], { stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 64 * 1024 * 1024 });
  // 不正なUTF-8を置換してスキップルールに誤一致させず、判定失敗として扱う。
  const files = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(diff).split('\0').filter(Boolean);
  const runChecks = shouldRunChecks(files, config);
  return {
    runChecks,
    reason: files.length === 0 ? 'no-changes' : runChecks ? 'changed-files' : 'skip-only',
    changedFileCount: files.length,
  };
}

export function writeResult(result: Result, env: Environment): void {
  const output = `run_checks=${result.runChecks}\nreason=${result.reason}\n`;
  if (env.GITHUB_OUTPUT) appendFileSync(env.GITHUB_OUTPUT, output, 'utf8');
  process.stdout.write(output);
  if (env.GITHUB_STEP_SUMMARY) {
    let summary = `## Should Run Checks\n\n- チェックを実行: ${result.runChecks}\n- 判定理由: ${result.reason}\n`;
    if (result.changedFileCount !== undefined) summary += `- 変更パス数: ${result.changedFileCount}\n`;
    appendFileSync(env.GITHUB_STEP_SUMMARY, summary, 'utf8');
  }
}

export function run(env: Environment = process.env): Result {
  try {
    const config = readInputs(env);
    if (!env.GITHUB_EVENT_PATH) throw new Error('GITHUB_EVENT_PATHがありません。');
    const event: unknown = JSON.parse(readFileSync(env.GITHUB_EVENT_PATH, 'utf8'));
    const result = evaluateChanges(resolve(env.GITHUB_WORKSPACE || '.'), env.GITHUB_EVENT_NAME ?? '', event, config);
    writeResult(result, env);
    return result;
  } catch (error) {
    writeResult({ runChecks: true, reason: 'error' }, env);
    throw error;
  }
}

if (require.main === module) {
  try {
    run();
  } catch (error) {
    const message = (error instanceof Error ? error.message : String(error))
      .replaceAll('%', '%25').replaceAll('\r', '%0D').replaceAll('\n', '%0A');
    process.stderr.write(`::error::${message}\n`);
    process.exitCode = 1;
  }
}
