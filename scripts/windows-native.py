#!/usr/bin/env python3
"""Dispatch a native Windows command from WSL or Windows, without a shell argv join."""
import argparse
import base64
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def prepared_argv(stage, packet, native_command):
    """Compose from already hash-verified stage/packet metadata; never launch."""
    from pathlib import PurePosixPath, PureWindowsPath
    def need(value, message):
        if not value:raise ValueError('prepared native dispatch: '+message)
    need(stage.get('schema')=='native-tiny-source-stage-v1' and stage.get('staged') is True and
        stage.get('admission') is False,'completed source stage required')
    role=packet['source_roles']['harness'];selected=stage['source']
    root=PureWindowsPath(role['root'])
    need(root.is_absolute() and root.drive.upper()=='C:' and '..' not in root.parts,'selected local C harness required')
    need(PureWindowsPath(selected['root'])==root and all(role[key]==selected[key]
        for key in ('commit','tree','sha256','git_blobs')),'packet/stage source role mismatch')
    prefix=list(stage['wsl_preparer_argv']);need(prefix.count('--')==1,'one emitted launcher boundary required')
    prefix=prefix[:prefix.index('--')+1]
    checkout=str(PurePosixPath('/mnt/c',*root.parts[1:]))
    need(len(prefix)==11 and prefix[0]=='/usr/bin/env' and prefix[3]=='-B' and
        PurePosixPath(prefix[2]).is_absolute() and PurePosixPath(prefix[4]).is_absolute() and
        PurePosixPath(prefix[4]).name=='windows-native.py' and
        prefix[5:]==['--checkout',checkout,'--expect-commit',role['commit'],'python','--'],
        'emitted launcher checkout/entry/revision mismatch')
    native=list(native_command)
    need(native and all(isinstance(value,str) for value in native),'literal native argv required')
    python=PureWindowsPath(packet['commands']['supervise'][0])
    need(PureWindowsPath(native[0])==python==PureWindowsPath(stage['preparer_argv'][0]) and
        prefix[1].startswith('CHOPPER_WINDOWS_PYTHON=') and
        PureWindowsPath(prefix[1].split('=',1)[1])==python,'selected Python mismatch')
    index=1
    while index<len(native) and native[index] in ('-B','-E','-s'):index+=1
    need(index<len(native),'native entry required')
    if native[index]!='-c':
        entry=PureWindowsPath(native[index])
        need(entry.parent==root/'scripts' and entry.name in ('native-scale-runner.py','acceptance-preflight.py'),
            'native entry outside selected harness')
    else:
        need(index+1<len(native),'literal inline metadata body required; caller must pin it')
    return prefix+native[1:]


def windows_checkout(value):
    if os.name != "nt" and value.startswith("/"):
        value = subprocess.check_output(["wslpath", "-w", value], text=True).strip()
    if not re.match(r"^[A-Za-z]:[\\/]", value):
        raise ValueError("Use a Windows drive checkout, not a WSL/UNC filesystem path")
    return ntpath.normpath(value)


def encoded_command(request):
    payload = base64.b64encode(json.dumps(request).encode("utf-8")).decode("ascii")
    script = ntpath.join(request["checkout"], "scripts", "windows-native.py")
    # Only a literal path and base64 data enter PowerShell; native Python owns argv.
    literal = script.replace("'", "''")
    source = """$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:PATHEXT = '.COM;.EXE;.BAT;.CMD;.CPL'
    $env:GIT_OPTIONAL_LOCKS = '0'
    $chopperRequestBase64 = 'PAYLOAD'
    $request = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($chopperRequestBase64)) | ConvertFrom-Json
    $python = $request.overrides.CHOPPER_WINDOWS_PYTHON
    if (!$python) { $python = $env:CHOPPER_WINDOWS_PYTHON }
    if (!$python) { $python = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe' }
    if (!(Test-Path -LiteralPath $python)) {
        $python = (Get-Command python.exe -ErrorAction Stop).Source
        if ($python -like '*\\Microsoft\\WindowsApps\\*') { throw 'Select a real Windows interpreter with CHOPPER_WINDOWS_PYTHON.' }
    }
""" + f"& $python '{literal}' --request-base64 $chopperRequestBase64\nexit $LASTEXITCODE\n" + """} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""
    source = source.replace("PAYLOAD", payload, 1)
    return base64.b64encode(source.encode("utf-16le")).decode("ascii")


def native_environment(root, overrides=None):
    env = dict(os.environ)
    env.update(overrides or {})
    # Discard inherited Linux overrides, preserving explicit Windows settings.
    for name in ("CARGO_HOME", "RUSTUP_HOME", "CARGO_TARGET_DIR", "RUSTC", "RUSTC_WRAPPER", "CC", "AR"):
        if env.get(name, "").startswith("/"):
            env.pop(name)
    cargo = Path(env["USERPROFILE"]) / ".cargo/bin"
    if not env.get("CHOPPER_WINDOWS_CARGO") and (root / ".tools/cargo/bin/cargo.exe").is_file():
        cargo = root / ".tools/cargo/bin"
        env.update(CARGO_HOME=str(root / ".tools/cargo"), RUSTUP_HOME=str(root / ".tools/rustup"))
    node = Path(env["LOCALAPPDATA"]) / "Chopper/tools/node-v22.23.4-win-x64"
    directories = []
    for name in ("RUSTC", "NODE", "PYTHON", "CARGO", "GIT", "NPM"):
        override = env.get("CHOPPER_WINDOWS_" + name)
        if override:
            if not Path(override).is_file():
                raise ValueError(f"Missing {name.lower()} override: {override}")
            directories.append(str(Path(override).parent))
    if env.get("CHOPPER_WINDOWS_RUSTC"):
        env["RUSTC"] = env["CHOPPER_WINDOWS_RUSTC"]
    path = ";".join([*directories, str(cargo), str(node), env.get("PATH", "")])
    env.update(PATH=path, PATHEXT=".COM;.EXE;.BAT;.CMD;.CPL",
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return env


def native_tool(name, env):
    override = env.get("CHOPPER_WINDOWS_" + name.upper())
    if override:
        if not Path(override).is_file():
            raise ValueError(f"Missing {name} override: {override}")
        return override
    if name == "python":
        return sys.executable
    extension = ".cmd" if name == "npm" else ".exe"
    return shutil.which(name + extension, path=env["PATH"])


def native_argv(name, args, env):
    exe = native_tool(name, env)
    if not exe:
        raise ValueError(f"Native Windows {name} is missing; see docs/windows-wsl-workflow.md")
    if name == "npm":
        # Execute npm's JS entry with Node, avoiding cmd.exe metacharacter parsing.
        directory = Path(exe).parent
        entry = directory / "node_modules/npm/bin/npm-cli.js"
        node = Path(native_tool("node", env) or directory / "node.exe")
        if not entry.is_file() or not node.is_file():
            raise ValueError("npm requires node.exe and node_modules/npm/bin/npm-cli.js beside npm.cmd")
        return [str(node), str(entry), *args]
    return [exe, *args]


def native_main(request):
    if os.name != "nt":
        raise ValueError("Native dispatch must execute with Windows Python")
    root = Path(windows_checkout(request["checkout"]))
    if not (root / "crates/chopper/Cargo.toml").is_file() or not (root / "Cargo.lock").is_file():
        raise ValueError("Selected checkout is not a Chopper workspace")
    env = native_environment(root, request.get("overrides"))

    def capture(tool, *args):
        return subprocess.check_output(native_argv(tool, list(args), env), cwd=root,
                                       env={**env, 'GIT_OPTIONAL_LOCKS': '0'}, text=True).strip()

    commit = capture("git", "rev-parse", "HEAD")
    dirty = capture("git", "status", "--porcelain=v1", "--untracked-files=normal")
    if request["expected_commit"] and commit.lower() != request["expected_commit"].lower():
        raise ValueError(f"Windows checkout is {commit}, expected {request['expected_commit']}")
    if request["tool"] == "doctor":
        tools, missing = {}, []
        for name in ("git", "cargo", "rustc", "python", "node", "npm"):
            try:
                tools[name] = {"path": native_tool(name, env), "version": capture(name, "--version")}
            except (ValueError, OSError, subprocess.CalledProcessError) as error:
                tools[name] = {"error": str(error)}
                missing.append(name)
        vswhere = Path(env.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
        msvc = subprocess.check_output([str(vswhere), "-products", "*", "-requires",
                 "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                 text=True).strip() if vswhere.is_file() else ""
        if not msvc:
            missing.append("MSVC build tools")
        print(json.dumps({"checkout": str(root), "commit": commit, "dirty_paths": len(dirty.splitlines()),
                          "tools": tools, "msvc": msvc, "missing": missing}, indent=2))
        return int(bool(missing))
    if request["tool"] not in ("cargo", "python", "node", "npm"):
        raise ValueError("Unsupported Windows tool")
    if dirty and not request["allow_dirty"]:
        raise ValueError("Windows checkout has uncommitted inputs; use a clean revision or --allow-dirty with source provenance")
    return subprocess.run(native_argv(request["tool"], request["args"], env), cwd=root, env=env).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", required=True, help="Windows checkout, e.g. /mnt/c/src/chopper")
    parser.add_argument("--expect-commit", help="Require this full commit SHA before dispatch")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow execution against uncommitted inputs")
    parser.add_argument("tool", choices=["doctor", "cargo", "python", "node", "npm"])
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Tool arguments; use Windows paths")
    args = parser.parse_args(argv)
    if args.expect_commit and not re.fullmatch(r"[0-9a-fA-F]{40}", args.expect_commit):
        parser.error("--expect-commit must be a full 40-character commit SHA")
    try:
        request = {"checkout": windows_checkout(args.checkout), "expected_commit": args.expect_commit,
                   "allow_dirty": args.allow_dirty, "tool": args.tool,
                   "overrides": {name: os.environ[name] for name in
                       ("CHOPPER_WINDOWS_" + tool for tool in ("PYTHON", "CARGO", "RUSTC", "NODE", "NPM", "GIT"))
                       if name in os.environ},
                   "args": args.args[1:] if args.args[:1] == ["--"] else args.args}
        if os.name == "nt":
            return native_main(request)
        command = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                   "-EncodedCommand", encoded_command(request)]
        if len(subprocess.list2cmdline(command).encode('utf-16le')) // 2 + 1 > 32767:
            raise ValueError("Encoded Windows command exceeds the 32767 UTF-16 unit limit; shorten arguments")
        result = subprocess.run(command, cwd="/mnt/c" if os.name != "nt" else request["checkout"])
        if result.returncode:
            print(f"Native Windows command exited with status {result.returncode}.", file=sys.stderr)
        return result.returncode
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"windows-native: {error}\n")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--request-base64":
        try:
            sys.exit(native_main(json.loads(base64.b64decode(sys.argv[2]))))
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            sys.exit(f"windows-native: {error}")
    sys.exit(main())
