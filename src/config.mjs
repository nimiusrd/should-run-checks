import { readFileSync } from 'node:fs';
import { extname } from 'node:path';
import { parseDocument } from 'yaml';
import { validateConfig } from './scope.mjs';

export function parseConfig(source, filename) {
  const extension = extname(filename).toLowerCase();
  if (extension !== '.yml' && extension !== '.yaml') {
    return validateConfig(JSON.parse(source));
  }
  const document = parseDocument(source, { version: '1.2', uniqueKeys: true });
  const problem = document.errors[0] || document.warnings[0];
  if (problem) throw problem;
  return validateConfig(document.toJS({ maxAliasCount: 100 }));
}

export function loadConfig(filename) {
  return parseConfig(readFileSync(filename, 'utf8'), filename);
}
