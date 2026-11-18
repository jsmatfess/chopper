import {browserEngineAsset} from './browser-artifacts.mjs';
import {spawnSync} from 'node:child_process';
import {copyFileSync, existsSync, mkdirSync} from 'node:fs';
import {delimiter, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const args = process.argv.slice(2);
if (args.some(arg => arg.includes('experimental-input-snapshots'))) {
  throw new Error('Direct compact/IPC input snapshots were removed; use direct CSV input. experimental-input-snapshots is unsupported.');
}
if (args.some(arg => arg.includes('experimental-parallel-groups') || arg === '--parallel-groups')) {
  throw new Error('Independent-parent batching/replay was removed; experimental-parallel-groups is unsupported.');
}

// The copy below owns a fixed package/target/profile. Cargo must not redirect it.
const cargoArgs = [];
for (let i = 0; i < args.length; i++) {
  const arg = args[i];
  if (arg === '--resource-contracts') continue;
  if (arg === '--features' || arg === '-F') {
    if (!args[i + 1] || args[i + 1].startsWith('-')) throw new Error(`${arg} requires a feature list`);
    cargoArgs.push(arg, args[++i]);
  } else if (/^(--features=.+|-F.+|--all-features|--no-default-features|--offline|--locked|--frozen|--verbose|--quiet|-[vq]+)$/.test(arg)) {
    cargoArgs.push(arg);
  } else {
    throw new Error(`Unsupported browser build argument: ${arg}. Use CARGO_TARGET_DIR for the output directory; package, target and release profile are fixed.`);
  }
}
const resourceContracts = args.includes('--resource-contracts');
if (resourceContracts) cargoArgs.push('--features', 'resource-contract-tests');

const root = fileURLToPath(new URL('../', import.meta.url));
const env = {...process.env};
const windows = process.platform === 'win32';
const localCargo = join(root, '.tools', windows ? 'cargo' : 'linux/cargo');
if (existsSync(join(localCargo, 'bin', windows ? 'cargo.exe' : 'cargo'))) {
  env.CARGO_HOME = localCargo;
  env.RUSTUP_HOME = join(root, '.tools', windows ? 'rustup' : 'linux/rustup');
  const bins = [join(localCargo, 'bin')];
  if (windows) bins.push(join(root, '.tools/mingw64/bin'));
  env.PATH = [...bins, env.PATH ?? ''].join(delimiter);
  if (!windows) env.CARGO_TARGET_DIR ??= join(root, '.tools/linux/target');
}
const arch = {x64: 'x86_64', arm64: 'arm64'}[process.arch];
const platform = {win32: 'windows', darwin: 'macos', linux: 'linux'}[process.platform];
const sdk = resolve(root, env.WASI_SDK_PATH || join('.tools', windows ? 'windows' : 'linux', `wasi-sdk-33.0-${arch}-${platform}`));
const clang = join(sdk, 'bin', windows ? 'clang.exe' : 'clang');
const ar = join(sdk, 'bin', windows ? 'llvm-ar.exe' : 'llvm-ar');
if (!existsSync(clang) || !existsSync(ar)) {
  console.error('WASI SDK not found. Set WASI_SDK_PATH to an extracted WASI SDK 33 directory (see docs/browser.md).');
  process.exit(1);
}
env.CC_wasm32_wasip1 = clang;
env.AR_wasm32_wasip1 = ar;
env.CFLAGS_wasm32_wasip1 = `--sysroot="${join(sdk, 'share/wasi-sysroot')}"`;
const flags = ['-C', 'link-arg=-zstack-size=1048576', '-C', 'link-arg=--max-memory=2147483648'];
if (env.CARGO_ENCODED_RUSTFLAGS !== undefined) {
  env.CARGO_ENCODED_RUSTFLAGS = [...env.CARGO_ENCODED_RUSTFLAGS.split('\x1f').filter(Boolean), ...flags].join('\x1f');
} else {
  env.RUSTFLAGS = `${env.RUSTFLAGS ?? ''} ${flags.join(' ')}`.trim();
}
// Override Cargo configuration as well as CLI redirects: build and copy must
// use the same absolute directory even when no target environment was supplied.
const target = resolve(root, env.CARGO_TARGET_DIR || 'target');
env.CARGO_TARGET_DIR = target;
env.CARGO_BUILD_TARGET_DIR = target;
const result = spawnSync('cargo', ['build', '--release', '--locked', '-p', 'chopper-browser', '--target', 'wasm32-wasip1', ...cargoArgs], {cwd: root, env, stdio: 'inherit'});
if (result.error) {
  console.error(`Could not start Cargo: ${result.error.message}. Install Rust and add Cargo to PATH.`);
  process.exit(1);
}
if (result.status !== 0) process.exit(result.status ?? 1);
mkdirSync(join(root, 'ui/dist'), {recursive: true});
copyFileSync(join(target, 'wasm32-wasip1/release/chopper_browser.wasm'), join(root, 'ui/dist', browserEngineAsset(args)));
