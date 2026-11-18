"""Frozen host-observer compatibility rules for the retained qualification campaign.

These recorded hashes, exclusions and exact AST normalizations preserve the
existing campaign only. Do not expand them for current tooling edits: collect a
fresh host observation and preparation receipt instead. Frozen checkouts retain
their own original evaluator; no source is copied into acceptance trees.
"""
import ast

REVIEWED_CONSUMERS = {'scripts/validation-runner.py': 'f3190e060ba9966035e1052ed7947d8e8480292f36c8a57b29bc8ea8c2734fda', 'scripts/scale_acceptance/browser_scale_guard.py': 'ba6f3200e6bfa1574fa59a0fac2093b3a4827abf3f6ebfced48c04453d25f83a', 'scripts/scale_acceptance/browser_scale_watchdog.py': 'c25c2e3f20f857c1c42bebb0e89a9a6d6a051f9a7d0dbbdc76a0af246b7f7d23', 'scripts/scale_acceptance/browser_scale_identity.py': '3c290762d06e8e8c9623d71fdccb38906607ad255169642e269949c8734383aa', 'scripts/scale_acceptance/browser_scale_plan.py': '7471ed3f2d8e863909a0568b62655a9a7bceb24626078d63f3521066257c80d6', 'scripts/scale_acceptance/guard.py': '7a8fb147a98a64d2916e68a3832f1565c200e6db42fb736ee23fef90aa82d9ef', 'scripts/scale_acceptance/generate.py': 'c063f082abb985489ca7d91c099f7b013a68a712332b0ccc1ead913a84ed3bb0', 'scripts/scale_acceptance/native_preflight.py': '1538006c57de384543f21632ceb47fecec97d8c976da92ee8cf38cf21e795395', 'scripts/scale_acceptance/native_tiny.py': '3e56b3d6ac6e5266cd9eb7c45b7856c8714f795202963b59e000f774ab6da07f', 'scripts/acceptance-preflight.py': '93ce0b775b55da63ff13a35fbf98d3482579998416ef14750cd3bd6ed0d58a35', 'scripts/scale_acceptance/native_scale_identity.py': 'ef8fefb1cb3ff94719473d29c60f59d3553908375413e12fc2f0d94335ff97ee', 'scripts/scale_acceptance/native_scale_windows.py': 'bf172cdd5b8dcabec9a1564ab2187bd6d3be60f5be32e059037c3a293a125b1b', 'scripts/hosted_picker/config.py': '13005fdfb73e1b1647e9a02d4a2439cb9e2b0bd4e4016822576af19d4dff85db', 'scripts/hosted_picker/control.py': '8f31e9ce846ff441f050819241f71a7c6d1214895ae8857aa5720233b6754f5b', 'scripts/hosted_picker/tests/test_ffi.py': 'a1991987233e17673201bb772f90ad3a61d524025808ec6daa918733d445fb14'}

UNRELATED = {'scripts/acceptance-preflight.py':{'inspect'},
               'scripts/scale_acceptance/native_scale_host.py':set(),
               'scripts/scale_acceptance/native_scale_identity.py':{'frozen_metadata'},
               'scripts/scale_acceptance/hosted_qualification.py':{'host_implementation','borrowed_input_stamp','batch_admission','execution_selection','batch_inputs','check_borrowed_input','prepare_batch_definition','picker_case','qualified_batch','check_qualified_batch','batch_projection','prepare_packet','packet_declarations','current_process_facts','retained_packet_roots','browser_scale_time_inputs','browser_scale_time_context','browser_scale_time_reservation','browser_scale_time_available','browser_scale_make_reservation','retire_browser_scale_active','materialize_packet','browser_scale_paths','browser_scale_future_capacity','browser_scale_projection','browser_scale_packet_declarations',
                   'browser_scale_host_bindings','prepare_browser_scale_packet','materialize_browser_scale','browser_scale_after_exit','independent_observation','after_exit'},
               'scripts/browser-small-runner.py':{'command_specs','qualify','main','observation_io','write_control_json',
                   'error_causes','StatusReader','StatusWriter','worker','supervise','finish_supervision',
                   'sample_resources','run_supervision','census_child','Storage','resource_state','Receipts'},
               'scripts/browser-small-windows.py':{'ControlFileError','ControlFileCloseError','_control_api',
                   '_control_ancestors','_control_close','_control_open','read_control_snapshot',
                   '_control_rename_information','replace_control_snapshot','job_processes'},
               'scripts/validation-runner.py':set()}

ADDED_IMPORTS = {'scripts/browser-small-windows.py':('import stat','from pathlib import Path')}

def relevant(body,ignored,name):
        tree=ast.parse(body)
        if name=='scripts/scale_acceptance/native_scale_host.py':
            # Exact optional-root extension; the observer calls only the
            # unchanged default. Any other loader edit still denies reuse.
            selected = ast.parse("""def module(name, *, scripts=None):
    root = HERE if scripts is None else Path(scripts)
    spec = importlib.util.spec_from_file_location('native_'+name.replace('-', '_'), root / (name+'.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value
""").body[0]
            original = ast.parse("""def module(name):
    spec = importlib.util.spec_from_file_location('native_'+name.replace('-', '_'), HERE / (name+'.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value
""").body[0]
            exact = ast.dump(selected,include_attributes=False)
            tree.body=[original if ast.dump(node,include_attributes=False)==exact else node for node in tree.body]
        if name=='scripts/validation-runner.py':
            expected=ast.dump(ast.parse('(os.replace if replace is None else replace)(temporary,path)').body[0],include_attributes=False)
            for node in tree.body:
                if (isinstance(node,ast.FunctionDef) and node.name=='write_json'
                        and len(node.args.kwonlyargs)==1 and node.args.kwonlyargs[0].arg=='replace'
                        and node.args.kwonlyargs[0].annotation is None
                        and len(node.args.kw_defaults)==1 and isinstance(node.args.kw_defaults[0],ast.Constant)
                        and node.args.kw_defaults[0].value is None
                        and ast.dump(node.body[-1],include_attributes=False)==expected):
                    # Normalize only this reviewed callback extension. The full
                    # default writer body/signature still compares exactly.
                    node.args.kwonlyargs=[];node.args.kw_defaults=[]
                    node.body[-1]=ast.parse('os.replace(temporary,path)').body[0]
        imports={ast.dump(ast.parse(text).body[0],include_attributes=False) for text in ADDED_IMPORTS.get(name,())}
        tree.body=[node for node in tree.body
                   if not(isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and node.name in ignored)
                   and ast.dump(node,include_attributes=False) not in imports]
        return ast.dump(tree,include_attributes=False)
