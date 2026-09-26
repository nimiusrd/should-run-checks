import { appendFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { evaluateChanges } from './scope.mjs';
import { loadConfig } from './config.mjs';

function writeResult(result, env) {
  const output = `run_checks=${result.runChecks}\nreason=${result.reason}\n`;
  if (env.GITHUB_OUTPUT) appendFileSync(env.GITHUB_OUTPUT, output);
  process.stdout.write(output);
  if (env.GITHUB_STEP_SUMMARY) {
    appendFileSync(
      env.GITHUB_STEP_SUMMARY,
      `## Should Run Checks\n\n- チェックを実行: ${result.runChecks}\n- 判定理由: ${result.reason}\n` +
        (result.changedFileCount === undefined ? '' : `- 変更パス数: ${result.changedFileCount}\n`),
    );
  }
}

export function run(env = process.env) {
  try {
    const workspace = resolve(env.GITHUB_WORKSPACE || process.cwd());
    const configPath = resolve(workspace, env['INPUT_CONFIG-PATH'] || '.github/ci-skip-rules.json');
    const config = loadConfig(configPath);
    const event = JSON.parse(readFileSync(env.GITHUB_EVENT_PATH, 'utf8'));
    const result = evaluateChanges({ workspace, config, eventName: env.GITHUB_EVENT_NAME, event });
    writeResult(result, env);
    return result;
  } catch (error) {
    // 利用側がalways()で継続した場合にも、判定の失敗でチェックを省略させない。
    writeResult({ runChecks: true, reason: 'error' }, env);
    throw error;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    run();
  } catch (error) {
    const message = String(error.message)
      .replaceAll('%', '%25')
      .replaceAll('\r', '%0D')
      .replaceAll('\n', '%0A');
    process.stderr.write(`::error::${message}\n`);
    process.exitCode = 1;
  }
}
