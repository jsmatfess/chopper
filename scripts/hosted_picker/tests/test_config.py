"""Tiny source/definition controls in task-owned scratch; no native execution."""
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import config
import control


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_runtime_merge_requires_actual_bound_matching_tools_and_keeps_cold_git_out(self):
        import copy
        tool=dict(path=str(self.root/'tool'),sha256='a'*64)
        runtime=dict(path=str(self.root/'runtime'),sha256='b'*64)
        cold=dict(path=str(self.root/'cold-git'),sha256='c'*64)
        observed=dict(schema='chopper-hosted-host-v1',status='passed',host={'os':'Windows'},channel='chrome',workload_started=False,original_acquired=False,controller_started=False,tools={role:tool for role in ('python','node','browser')},inputs=[runtime],preparation_code=[],input_directories={str(self.root/'runtime-root'):[runtime['path']]},preparation={'inputs':[cold]})
        file=self.root/'host.json';file.write_text(json.dumps(observed));digest=hashlib.sha256(file.read_bytes()).hexdigest()
        plan=dict(channel='chrome',runtime_observation=dict(path=str(file),sha256=None),**{role:tool for role in ('python','node','browser')})
        with self.assertRaisesRegex(AssertionError,'bound actual runtime'):config.observed_runtime(copy.deepcopy(plan),{})
        pins={};selected=copy.deepcopy(plan)
        self.assertEqual(config.observed_runtime(selected,pins,digest),[str(self.root/'runtime-root')])
        self.assertEqual(pins[runtime['path']],runtime['sha256']);self.assertNotIn(cold['path'],pins)
        self.assertEqual(selected['runtime_observation']['sha256'],digest)
        with self.assertRaisesRegex(AssertionError,'conflicting observed'):config.observed_runtime(copy.deepcopy(plan),{runtime['path']:'d'*64},digest)
        changed=copy.deepcopy(plan);changed['node']=dict(tool,sha256='e'*64)
        with self.assertRaisesRegex(AssertionError,'tool drift'):config.observed_runtime(changed,{},digest)
        wrong=copy.deepcopy(plan);wrong['channel']='msedge'
        with self.assertRaises(AssertionError):config.observed_runtime(wrong,{},digest)
        pins={};self.assertEqual(config.observed_runtime({},pins),[]);self.assertEqual(pins,{})

    def test_new_namespace_requires_joined_prewrite_union_and_capacity_before_any_write(self):
        from types import SimpleNamespace
        from hosted_picker import control as namespace_control
        original=Path
        old=self.root/'hosted105-old';old.mkdir();(old/'payload').write_bytes(b'known')
        source=self.root/'source';source.mkdir();new=self.root/'hosted105-new'
        custody=source/'custody.json';custody.write_text(json.dumps(dict(sampledOwnedBytes=10)))
        plan=dict(root=str(new),controller_root=str(source),documents={'custody.json':str(custody)},inputs=[dict(path=str(old/'payload'))],owned_cap_bytes=32*1024**3,growth_bytes=4*1024**3)
        mapping=lambda value: self.root if str(value)=='C:/' else original(value)
        with patch.object(config,'Path',side_effect=mapping),patch.object(namespace_control,'Path',side_effect=mapping),patch.object(namespace_control,'native_volume',return_value={'filesystem':'NTFS'}),patch.object(config.shutil,'disk_usage',return_value=SimpleNamespace(free=200*1024**3)):
            with patch.object(namespace_control,'storage_size',side_effect=OSError('read denied')):
                with self.assertRaisesRegex(Exception,'read denied'):config.prepare_namespace(plan,[str(old)])
                self.assertFalse(new.exists(),'failed census creates no case directory or candidate')
            with patch.object(config.shutil,'disk_usage',return_value=SimpleNamespace(free=10)):
                with self.assertRaisesRegex(Exception,'headroom'):config.prepare_namespace(plan,[str(old)])
                self.assertFalse(new.exists())
            overlap=dict(plan,inputs=[dict(path=str(new/'input'))])
            with self.assertRaisesRegex(AssertionError,'input/output overlap'):config.prepare_namespace(overlap,[str(old)])
            self.assertFalse(new.exists())
            proof=config.prepare_namespace(plan,[str(old)])
            self.assertEqual(proof['value']['owned_bytes'],5);self.assertEqual(proof['value']['roots'],1)
            self.assertEqual(proof['value']['retained_floor_bytes'],10);self.assertEqual(proof['value']['admission_bytes'],10)
            self.assertTrue(new.is_dir());self.assertEqual(list(new.iterdir()),[])
            with self.assertRaisesRegex(AssertionError,'fresh case'):config.prepare_namespace(plan,[str(old)])

    def test_isolated_worker_proof_imports_selected_sibling_package_before_safe_denial(self):
        import subprocess,sys
        source=Path(control.__file__).resolve()
        missing=self.root/'missing-preflight.json'
        code="""import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('isolated_control',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
sys.path.insert(0,str(m.HERE))
m.PLAN={};m.CONFIG_PATH='unused';m.PREPARATION=dict(path=sys.argv[2],sha256='a'*64)
try:m.verify_sources()
except FileNotFoundError:pass
else:raise AssertionError('safe missing preflight must deny')
"""
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(source),str(missing)],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(list(self.root.iterdir()),[],'No owner/clock/attempt may be created')

    def test_worker_reuses_only_exact_preflight_then_refreshes_complete_metadata(self):
        from scale_acceptance import hosted_qualification
        binding=dict(path='native-pref',sha256='a'*64)
        with patch.multiple(control,PLAN={'synthetic':True},CONFIG_PATH='exact-plan',PREPARATION=binding), patch.object(hosted_qualification,'preflight',return_value={'status':'passed'}) as proof, patch.object(config,'check') as metadata, patch.object(config,'validate') as cold:
            self.assertEqual(control.verify_sources(),{'status':'passed'})
            proof.assert_called_once_with(binding,'exact-plan','actual-picker')
            metadata.assert_called_once_with(control.PLAN)
            cold.assert_not_called()
            proof.side_effect=ValueError('preflight mismatch')
            metadata.reset_mock()
            with self.assertRaisesRegex(ValueError,'preflight mismatch'):control.verify_sources()
            metadata.assert_not_called()
            cold.assert_not_called()
        with patch.multiple(control,PLAN={'synthetic':True},PREPARATION=None),patch.object(config,'validate',return_value='full') as cold:
            self.assertEqual(control.verify_sources(),'full')
            cold.assert_called_once_with(control.PLAN,fresh=False)

    def test_old_and_proposed_storage_budgets_remain_distinct(self):
        mib=1024**2
        self.assertEqual(config.storage_stop(dict(owned_cap_bytes=256*mib,growth_bytes=10*mib)),248*mib)
        self.assertEqual(config.storage_stop(dict(owned_cap_bytes=672*mib,growth_bytes=32*mib)),664*mib)
        self.assertEqual(config.storage_stop(dict(owned_cap_bytes=32*1024**3,growth_bytes=4*1024**3)),24*1024**3)
        self.assertEqual(config.storage_limits(dict(owned_cap_bytes=32*1024**3,growth_bytes=4*1024**3))['profile'],2*1024**3)
        for owned,growth in ((256,10*mib+1),(672,32*mib+1),(512,mib),(656,mib),(True,mib),(672,True)):
            cap=owned if type(owned) is bool else owned*mib
            with self.subTest(owned=owned,growth=growth),self.assertRaises(AssertionError):
                config.storage_stop(dict(owned_cap_bytes=cap,growth_bytes=growth))

    def test_controller_uses_one_bound_definition_for_both_guards(self):
        mib=1024**2
        source=Path(control.__file__).parent/'suite.py'
        plan=dict(schema='chopper-hosted-picker-qualification-v1',root=str(self.root/'case'),
            node=dict(path='synthetic-node'),profile=dict(path=str(self.root/'profile')),
            input=dict(path=str(self.root/'existing-input')),owned_cap_bytes=672*mib,growth_bytes=32*mib,
            inputs=[dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest())])
        selected=self.root/'config.json';selected.write_text(json.dumps(plan))
        fields=dict(ROOT=None,OUT=None,NODE=None,PLAN=None,CONFIG_PATH=None,CONFIG_SHA=None,PREPARATION=None,LIMIT=256*mib,MODULES={})
        from unittest.mock import patch
        with patch.multiple(control,**fields):
            control.bind(selected,hashlib.sha256(selected.read_bytes()).hexdigest())
            checked=control.load('suite')
            self.assertEqual(control.LIMIT,672*mib)
            self.assertEqual(checked.STOP_BYTES,664*mib)
            self.assertEqual(checked.FUTURE_BYTES,32*mib)
            checked.growth_gate(300*mib+32*mib-1,300*mib)
            with self.assertRaises(AssertionError):checked.growth_gate(300*mib+32*mib,300*mib)
            with patch.object(control,'document',return_value=dict(sampledOwnedBytes=633*mib)):
                control.guard_check(0,100,662*mib,False,dict(transient=0,profile=0,free=200*1024**3))
                with self.assertRaises(AssertionError):control.guard_check(0,100,664*mib,False,dict(transient=0,profile=0,free=200*1024**3))

    def test_owned_storage_census_denies_unreadable_subtree(self):
        retained = self.root/'retained'
        retained.mkdir()
        (retained/'payload').write_bytes(b'x'*64)
        self.assertEqual(control.storage_size(self.root), 64)
        scandir = os.scandir
        def denied(directory):
            if Path(directory) == retained:
                raise PermissionError('owned subtree unreadable')
            return scandir(directory)
        with patch.object(os, 'scandir', side_effect=denied):
            with self.assertRaisesRegex(PermissionError, 'owned subtree unreadable'):
                control.storage_size(self.root)

    def test_json_duplicate_nonfinite_and_alias_denials(self):
        p=self.root/'input.json'
        p.write_text('{}')
        self.assertEqual(config.read(p,expected_sha256=hashlib.sha256(p.read_bytes()).hexdigest()),{})
        p.write_text('malformed JSON')
        with self.assertRaisesRegex(AssertionError,'JSON expected hash drift'):
            config.read(p,expected_sha256='0'*64)
        for raw in ('{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}'):
            p.write_text(raw)
            with self.subTest(raw=raw),self.assertRaises((AssertionError,ValueError)):config.read(p)
        p.write_text('{}')
        alias=self.root/'alias.json'
        try:alias.symlink_to(p)
        except OSError:self.skipTest('symlink unavailable')
        with self.assertRaisesRegex(AssertionError,'alias'):config.read(alias)

    def test_path_rechecks_ancestor_reparse_and_allows_absent_destination(self):
        source = self.root/'source.json'
        source.write_text('{}')
        absent = self.root/'not-created/config.json'
        self.assertEqual(config.path(absent), absent)
        lstat = Path.lstat
        def reparse(p):
            info = lstat(p)
            if p == self.root:
                from types import SimpleNamespace
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info
        for target in (source, absent):
            with patch.object(Path, 'lstat', reparse):
                with self.subTest(target=target), self.assertRaisesRegex(AssertionError, 'reparse'):
                    config.path(target)
        self.assertEqual(config.path(source), source)

    def test_path_denies_dangling_alias_and_propagates_ancestor_errors(self):
        absent = self.root/'missing.json'
        alias = self.root/'dangling.json'
        try:
            alias.symlink_to(absent)
        except OSError:
            self.skipTest('symlink unavailable')
        with self.assertRaisesRegex(AssertionError, 'alias'):
            config.path(alias)
        lstat = Path.lstat
        def denied(p):
            if p == self.root:
                raise PermissionError('ancestor unreadable')
            return lstat(p)
        with patch.object(Path, 'lstat', denied):
            with self.assertRaisesRegex(PermissionError, 'ancestor unreadable'):
                config.path(absent)
        with self.assertRaisesRegex(AssertionError, 'regular'):
            config.stamp(self.root)

    def test_immutable_hardlink_aliases_but_no_metadata_or_namespace_drift(self):
        source=self.root/'source.py';source.write_text('# synthetic\n')
        alias=self.root/'readonly-alias.py';os.link(source,alias)
        self.assertEqual(config.stamp(source)[:3],config.stamp(alias)[:3])
        p=dict(inputs=[dict(path=str(source),stat=config.stamp(source))],
               input_directories={str(self.root):config.inventory(self.root)})
        config.check(p)
        added=self.root/'extra';added.write_bytes(b'')
        with self.assertRaisesRegex(AssertionError,'inventory'):config.check(p)
        added.unlink()
        source.write_text('# changed!!\n')
        with self.assertRaisesRegex(AssertionError,'metadata'):config.check(p)

    def test_parser_receives_only_pinned_utf8_source_without_executing_it(self):
        scripts = self.root/'scripts'
        helpers = scripts/'hosted_picker'
        helpers.mkdir(parents=True)
        parser = helpers/'parse-uia.ps1'
        parser.write_bytes((Path(config.__file__).parent/'parse-uia.ps1').read_bytes())
        uia = helpers/'uia.ps1'
        raw = "throw 'UIA_SIDE_EFFECT 漢字'\n".encode('utf-8')
        uia.write_bytes(raw)
        binding = self.root/'uia-binding.json'
        binding.write_text(json.dumps(dict(powershell=dict(path='powershell.exe'))))
        plan = dict(controller_root=str(self.root), documents={'uia-binding.json':str(binding)},
                    inputs=[dict(path=str(p), stat=config.stamp(p),
                                 sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in (parser,uia)])
        calls = []
        def probe(argv, budget, name, *, cwd):
            calls.append(argv)
            self.assertEqual(argv[1:5], ['-NoLogo','-NoProfile','-NonInteractive','-Command'])
            command = argv[5]
            self.assertIn('::ParseInput($text,', command)
            self.assertNotIn('UIA_SIDE_EFFECT', command)
            payload = command.split("-SourceBase64 '",1)[1][:-1]
            self.assertEqual(base64.b64decode(payload,validate=True), raw)
            self.assertNotIn('-ExecutionPolicy', argv)
            return 'parsed'
        self.assertEqual(config.parse_uia(plan, None, probe), 'parsed')
        for source in (uia,parser):
            previous = source.read_bytes()
            source.write_bytes(previous+b'\n')
            with self.subTest(source=source), self.assertRaisesRegex(AssertionError, 'PowerShell source'):
                config.parse_uia(plan, None, probe)
            source.write_bytes(previous)
            for row in plan['inputs']:
                if row['path']==str(source):row['stat']=config.stamp(source)
        plan['inputs'][-1]['sha256'] = '0'*64
        with self.assertRaisesRegex(AssertionError, 'PowerShell source hash drift'):
            config.parse_uia(plan, None, probe)
        self.assertEqual(len(calls),1)

    def test_generator_never_learns_hashes_or_creates_an_attempt(self):
        source_root=self.root/'selected';source_root.mkdir()
        source=source_root/'input.py';source.write_text('# synthetic selected source\n')
        scripts=self.root/'controller/scripts';helpers=scripts/'hosted_picker';helpers.mkdir(parents=True)
        helper=helpers/'helper.py';helper.write_text('# synthetic helper\n')
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        selected=self.root/'selected.json'
        selected.write_text(json.dumps(dict(inputs=[dict(path=str(source),sha256=sha(source))],input_directories=[str(source_root)])))
        receipts=[]
        for name in ('older-receipt.json','newer-failed-receipt.json'):
            receipt=self.root/name;receipt.write_text('{"retained":true}')
            receipts.append(dict(native_path=str(receipt),sha256=sha(receipt),elapsed=1))
        accounting=self.root/'accounting.json';accounting.write_text(json.dumps(dict(prior_attempts=receipts)))
        definition=self.root/'definition.json'
        definition.write_text(json.dumps(dict(documents={'accounting.json':str(accounting)},source_selection=dict(path=str(selected),sha256=sha(selected)),
            inputs=[dict(path=str(helper),sha256=sha(helper)),dict(path=str(selected),sha256=sha(selected)),dict(path=str(accounting),sha256=sha(accounting))],input_directories=[str(helpers)])))
        output=self.root/'config.json'
        with patch.object(config,'SCRIPTS',scripts),patch.object(config,'validate') as validate:
            result=config.prepare(definition,output)
            self.assertEqual(result['input_files'],7)
            generated={row['path']:row['sha256'] for row in validate.call_args.args[0]['inputs']}
            self.assertTrue(all(generated[row['native_path']]==row['sha256'] for row in receipts),'All ledger references derived, not one hand-picked missing row')
            self.assertFalse(result['workload_started']);self.assertFalse(result['scale_slot_consumed'])
            self.assertEqual(validate.call_args.args[0]['input_directories'][str(helpers)],[str(helper)])
            metadata=json.loads(definition.read_text())
            metadata.update(case='malformed-retry',malformed_input=dict(path=str(source),bytes=source.stat().st_size,sha256=sha(source),nativeStat=dict(dev=0,ino=0,bytes=0,mtime_ns=0)))
            metadata_definition=self.root/'metadata-definition.json';metadata_definition.write_text(json.dumps(metadata))
            config.prepare(metadata_definition,self.root/'metadata-config.json')
            actual=validate.call_args.args[0]['malformed_input']
            self.assertEqual(actual['sha256'],sha(source),'metadata fill never learns a new content hash')
            self.assertEqual(actual['nativeStat'],dict(zip(('dev','ino','bytes','mtime_ns'),config.stamp(source)[:4])))
            value=json.loads(definition.read_text())
            value['inputs'].append(dict(path=receipts[0]['native_path'],sha256='0'*64))
            conflict=self.root/'conflicting-definition.json';conflict.write_text(json.dumps(value))
            with self.assertRaisesRegex(AssertionError,'conflicting historical receipt'):
                config.prepare(conflict,self.root/'conflict-output.json')
            self.assertFalse((self.root/'conflict-output.json').exists())
            original_ledger=accounting.read_text()
            accounting.write_text(json.dumps(dict(prior_attempts=[])))
            with self.assertRaisesRegex(AssertionError,'JSON expected hash drift'):
                config.prepare(definition,self.root/'changed-ledger-output.json')
            self.assertFalse((self.root/'changed-ledger-output.json').exists())
            accounting.write_text(original_ledger)
            (helpers/'undeclared.py').write_text('# unexpected\n')
            denied=self.root/'denied.json'
            with self.assertRaisesRegex(AssertionError,'pin every actual input'):
                config.prepare(definition,denied)
            self.assertFalse(denied.exists())
        self.assertFalse(any(p.name=='attempt1' for p in self.root.rglob('*')))
