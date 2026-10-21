import { existsSync } from 'node:fs';

// Use the project's virtualenv when it exists, so hooks work without activating it
const bin = (tool) => {
  if (existsSync(`.venv/bin/${tool}`)) return `.venv/bin/${tool}`;
  if (existsSync(`.venv/Scripts/${tool}.exe`)) return `.venv/Scripts/${tool}.exe`;
  return tool;
};

export default {
  '*.py': [`${bin('ruff')} check --fix`, `${bin('ruff')} format`],
  '*.{json,md,yml,yaml}': ['prettier --write'],
};
