"""Boundary tests for the WSL/native Windows dispatcher; no Windows host required."""
import base64
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("windows_native", Path(__file__).with_name("windows-native.py"))
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class WindowsNativeTests(unittest.TestCase):
    def test_prepared_dispatch_reuses_complete_stage_prefix_and_denies_copied_checkout(self):
        import copy
        root='C:/frozen/h-native103-r3';python='C:/Python/python.exe'
        role=dict(root=root,commit='a'*40,tree='b'*40,sha256={'script':'c'*64},git_blobs={'script':'d'*40})
        prefix=['/usr/bin/env','CHOPPER_WINDOWS_PYTHON='+python,'/usr/bin/python3','-B',
            '/frozen/linux/scripts/windows-native.py','--checkout','/mnt/c/frozen/h-native103-r3',
            '--expect-commit',role['commit'],'python','--']
        stage=dict(schema='native-tiny-source-stage-v1',staged=True,admission=False,source=role,
            wsl_preparer_argv=prefix+['-B',root+'/scripts/native-scale-runner.py','prepare'],preparer_argv=[python])
        command=[python,'-B',root+'/scripts/native-scale-runner.py','supervise','C:/prep/operator.json','--sha256','e'*64,'--execute']
        packet=dict(source_roles=dict(harness=copy.deepcopy(role)),commands=dict(supervise=command))
        with patch.object(native.subprocess,'run') as run,patch.object(native.subprocess,'check_output') as query:
            self.assertEqual(native.prepared_argv(stage,packet,command),prefix+command[1:])
            for field in ('checkout','revision','entry','Python','role','native-entry'):
                changed=copy.deepcopy(stage);selected=copy.deepcopy(packet);argv=list(command)
                if field=='checkout':changed['wsl_preparer_argv'][6]='/mnt/c/frozen/h-native103-r1'
                elif field=='revision':changed['wsl_preparer_argv'][8]='f'*40
                elif field=='entry':changed['wsl_preparer_argv'][4]='relative/other.py'
                elif field=='Python':changed['wsl_preparer_argv'][1]='CHOPPER_WINDOWS_PYTHON=C:/wrong/python.exe'
                elif field=='role':selected['source_roles']['harness']['sha256']['script']='f'*64
                else:argv[2]='C:/old/scripts/native-scale-runner.py'
                with self.subTest(field=field),self.assertRaises(ValueError):native.prepared_argv(changed,selected,argv)
            run.assert_not_called();query.assert_not_called()

    def test_rejects_unc_and_relative_checkouts(self):
        for path in (r"\\wsl.localhost\Ubuntu\home\user\chopper", "relative/chopper", "C:relative"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                native.windows_checkout(path)

    def test_payload_keeps_arguments_out_of_powershell_source(self):
        arguments = ['space value', 'quote"value', "$(touch wrong)", "a&b|c;d", "trailing\\", "café"]
        request = {"checkout": r"C:\User's files\chopper", "args": arguments}
        source = base64.b64decode(native.encoded_command(request)).decode("utf-16le")
        self.assertIn("C:\\User''s files\\chopper\\scripts\\windows-native.py", source)
        payload = source.split("$chopperRequestBase64 = '", 1)[1].split("'", 1)[0]
        self.assertEqual(json.loads(base64.b64decode(payload)), request)
        self.assertNotIn("$(touch wrong)", source)

    def test_long_argument_payload_is_encoded_once_within_windows_limit(self):
        request = dict(checkout=r'C:\source', args=['x'*5000], tool='python',
                       overrides={'CHOPPER_WINDOWS_PYTHON': r'D:\Python\python.exe'},
                       expected_commit='a'*40, allow_dirty=False)
        encoded = native.encoded_command(request)
        command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]
        self.assertLessEqual(len(subprocess.list2cmdline(command).encode('utf-16le'))//2+1, 32767)
        source = base64.b64decode(encoded).decode('utf-16le')
        payload = source.split("$chopperRequestBase64 = '", 1)[1].split("'", 1)[0]
        self.assertEqual(json.loads(base64.b64decode(payload)), request)
        self.assertEqual(source.count(payload), 1)
        self.assertIn('FromBase64String($chopperRequestBase64)', source)
        self.assertIn('--request-base64 $chopperRequestBase64', source)

    @unittest.skipIf(native.os.name == 'nt', 'Tests the WSL parent dispatch')
    def test_oversized_encoded_command_denies_before_native_start(self):
        with patch.object(native, 'encoded_command', return_value='A'*32768), patch.object(
                native.subprocess, 'run') as run, patch('sys.stderr', new=io.StringIO()) as error:
            with self.assertRaises(SystemExit) as denied:
                native.main(['--checkout', 'C:/source', 'doctor'])
        self.assertEqual(denied.exception.code, 2)
        self.assertIn('32767 UTF-16 unit limit', error.getvalue())
        run.assert_not_called()

    def test_native_arguments_reach_process_without_a_shell(self):
        arguments = ["-c", "print('quoted text')", "a&b", 'embedded"quote', "last\\"]
        with patch.object(native, "native_tool", return_value="C:/Python/python.exe"):
            self.assertEqual(native.native_argv("python", arguments, {}), ["C:/Python/python.exe", *arguments])

    @unittest.skipUnless(shutil.which('git'), 'Git is required for the index-preservation regression')
    def test_revision_checks_preserve_the_selected_checkout_index(self):
        git = shutil.which('git')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'crates/chopper').mkdir(parents=True)
            (root/'crates/chopper/Cargo.toml').touch()
            (root/'Cargo.lock').touch()
            source = root/'source.py'
            source.write_text('unchanged source\n')
            environment = dict(os.environ, GIT_OPTIONAL_LOCKS='1', GIT_CONFIG_NOSYSTEM='1',
                               GIT_CONFIG_GLOBAL=os.devnull)
            subprocess.run([git, 'init', '--quiet', str(root)], env=environment, check=True)
            subprocess.run([git, '-C', str(root), 'add', '.'], env=environment, check=True)
            subprocess.run([git, '-C', str(root), '-c', 'user.name=Control',
                            '-c', 'user.email=control@example.invalid', '-c', 'commit.gpgsign=false',
                            '-c', 'core.hooksPath='+str(root/'empty-hooks'),
                            'commit', '--quiet', '-m', 'fixture'], env=environment, check=True)
            commit = subprocess.check_output([git, '-C', str(root), 'rev-parse', 'HEAD'],
                                             env=environment, text=True).strip()
            observed = source.stat()
            os.utime(source, ns=(observed.st_atime_ns, observed.st_mtime_ns-10_000_000_000))
            index = root/'.git/index'
            before = (index.read_bytes(), index.stat().st_mtime_ns)
            request = dict(checkout='C:/selected', expected_commit=commit,
                           overrides={}, tool='python', args=['-B', 'control.py'], allow_dirty=False)
            real_run = subprocess.run
            def run_selected(argv, **kwargs):
                if argv[0] == git:
                    return real_run(argv, **kwargs)
                return subprocess.CompletedProcess(argv, 0)
            with patch.object(native.os, 'name', 'nt'), \
                 patch.object(native, 'Path', return_value=root), \
                 patch.object(native, 'windows_checkout', return_value=str(root)), \
                 patch.object(native, 'native_environment', return_value=environment), \
                 patch.object(native, 'native_argv', side_effect=lambda tool, args, env: [git if tool == 'git' else 'selected-python', *args]), \
                 patch.object(native.subprocess, 'check_output', wraps=subprocess.check_output) as capture, \
                 patch.object(native.subprocess, 'run', side_effect=run_selected) as run:
                self.assertEqual(native.native_main(request), 0)
            self.assertEqual((index.read_bytes(), index.stat().st_mtime_ns), before)
            self.assertEqual(capture.call_count, 2)
            for call in capture.call_args_list:
                self.assertEqual(call.kwargs['env']['GIT_OPTIONAL_LOCKS'], '0')
            self.assertEqual(run.call_args.kwargs['env'], environment)
            self.assertEqual(environment['GIT_OPTIONAL_LOCKS'], '1')

    def test_linux_overrides_are_removed_but_windows_settings_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = {"USERPROFILE": directory, "LOCALAPPDATA": directory, "PATH": "C:/Windows",
                           "CARGO_HOME": "/home/user/.cargo", "CC": "/usr/bin/cc", "CARGO_TARGET_DIR": "D:/build"}
            with patch.dict(native.os.environ, environment, clear=True):
                result = native.native_environment(Path(directory))
            self.assertNotIn("CARGO_HOME", result)
            self.assertNotIn("CC", result)
            self.assertEqual(result["CARGO_TARGET_DIR"], "D:/build")
            self.assertIn(".EXE", result["PATHEXT"])

    def test_explicit_cargo_override_does_not_select_local_rust_homes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / '.tools/cargo/bin'
            local.mkdir(parents=True)
            (local / 'cargo.exe').touch()
            selected = root / 'selected/bin'
            selected.mkdir(parents=True)
            cargo = selected / 'cargo.exe'
            cargo.touch()
            environment = {"USERPROFILE": directory, "LOCALAPPDATA": directory, "PATH": "C:/Windows"}
            with patch.dict(native.os.environ, environment, clear=True):
                result = native.native_environment(root, {"CHOPPER_WINDOWS_CARGO": str(cargo)})
            self.assertEqual(result['PATH'].split(';')[0], str(selected))
            self.assertNotIn('CARGO_HOME', result)
            self.assertNotIn('RUSTUP_HOME', result)

    @unittest.skipIf(native.os.name == "nt", "Tests the WSL parent dispatch")
    def test_wsl_parent_forwards_explicit_windows_executable_paths(self):
        selected = r'D:\Python\python.exe'
        with patch.dict(native.os.environ, {'CHOPPER_WINDOWS_PYTHON': selected}):
            with patch.object(native.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                native.main(["--checkout", "C:/src/chopper", "doctor"])
        source = base64.b64decode(run.call_args.args[0][-1]).decode('utf-16le')
        payload = source.split("$chopperRequestBase64 = '", 1)[1].split("'", 1)[0]
        request = json.loads(base64.b64decode(payload))
        self.assertEqual(request['overrides']['CHOPPER_WINDOWS_PYTHON'], selected)
        self.assertIn('$request.overrides.CHOPPER_WINDOWS_PYTHON', source)
        self.assertIn("$env:GIT_OPTIONAL_LOCKS = '0'", source)

    @unittest.skipIf(native.os.name == "nt", "Tests the WSL parent dispatch")
    def test_windows_exit_status_is_propagated(self):
        with patch.object(native.subprocess, "run", return_value=subprocess.CompletedProcess([], 42)) as run, patch("sys.stderr", new=io.StringIO()) as stderr:
            self.assertEqual(native.main(["--checkout", "C:/src/chopper", "doctor"]), 42)
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertEqual(run.call_args.kwargs["cwd"], "/mnt/c")
            self.assertEqual(stderr.getvalue(), "Native Windows command exited with status 42.\n")


if __name__ == "__main__":
    unittest.main()
