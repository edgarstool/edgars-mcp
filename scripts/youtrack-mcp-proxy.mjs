import { spawn, execFileSync } from 'node:child_process';

let key = process.env.YOUTRACK_API_KEY || '';
if (!key && process.platform === 'win32') {
  key = execFileSync('powershell.exe', [
    '-NoProfile',
    '-Command',
    "[Environment]::GetEnvironmentVariable('YOUTRACK_API_KEY','User')",
  ], { encoding: 'utf8', windowsHide: true }).trim();
}
if (!key) {
  console.error('YOUTRACK_API_KEY missing');
  process.exit(2);
}

const env = { ...process.env, AUTH_HEADER: 'Bearer ' + key };
const child = spawn('npx', [
  '-y',
  'mcp-remote@latest',
  'https://edgars.youtrack.cloud/mcp',
  '--header',
  'Authorization:${AUTH_HEADER}',
], {
  env,
  shell: true,
  stdio: 'inherit',
  windowsHide: true,
});

child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
