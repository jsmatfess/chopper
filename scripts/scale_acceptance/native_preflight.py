"""Read-only native preparation adapter; never a session or slot owner.

The acceptance entry point runs this inside its separately metered preparation
child. Identity's existing reads and Git commands remain subject to that budget.
"""
import importlib.util
from importlib.machinery import ModuleSpec
import json
import os
from pathlib import Path
import stat
import sys
import types
from .native_scale_control import validate_preparation
from .native_scale_identity import host, source_map
from .verify import read_json, require, sha256


WINDOWS_BLOCKED = ('Windows admission deferred: fresh OS-local proof and current '
                   'Linux seal/parity required')
RUNTIME_PENDING = [
    'Fresh capacity, original reservation ownership and live containment',
    'Complete tiny controller journey, independent verification and cleanup',
    'Matching generated frozen batch before release acceptance',
]


def observe_baseline(roots, budget):
    """Produce the existing nine-field Storage baseline, without an external helper."""
    from . import native_scale_identity as identity
    from .native_scale_monitor import Storage
    from ._native_file import _allocated_bytes
    roots = list(map(identity.path, roots))
    require(all(a != b and a not in b.parents and b not in a.parents
                for i, a in enumerate(roots) for b in roots[i+1:]), 'overlapping baseline roots')
    value = dict(roots=[], entries=[], sum_bytes=0)
    checked = []
    for root in roots:
        budget.check()
        before = root.lstat()
        require(stat.S_ISDIR(before.st_mode), 'retained baseline root must be directory')
        def walk_error(error):
            raise error
        for folder, directories, files in os.walk(root, onerror=walk_error):
            budget.check()
            for current in [Path(folder), *(Path(folder)/name for name in files)]:
                budget.check()
                current = identity.path(str(current))
                if os.name == 'nt':
                    for ancestor in (current, *current.parents):
                        require(not ancestor.lstat().st_file_attributes & 0x400, 'baseline reparse point')
                observed = current.lstat()
                require(observed.st_ino and (stat.S_ISREG(observed.st_mode) or stat.S_ISDIR(observed.st_mode)),
                        'baseline special/unknown file identity')
                amount = (_allocated_bytes(current, observed) if stat.S_ISREG(observed.st_mode)
                          else getattr(observed, 'st_blocks', 0)*512)
                item = dict(path=str(current), stat=identity.stat_fields(observed, amount, current))
                checked.append(item)
                if current == root:
                    value['roots'].append(item)
                if stat.S_ISREG(observed.st_mode):
                    item = dict(item, charge_bytes=max(observed.st_size, amount))
                    value['entries'].append(item)
                    value['sum_bytes'] += item['charge_bytes']
            # Walk does not follow directory symlinks; reject those omitted names too.
            for name in directories:
                child = identity.path(str(Path(folder)/name))
                require(not getattr(child.lstat(), 'st_file_attributes', 0)&0x400, 'baseline reparse point')
        require(os.path.samestat(before, root.stat()), 'baseline root identity drift')
    # Admission independently proves exact membership and fresh allocations.
    Storage(value, dict(sum_bytes=value['sum_bytes'], entry_count=len(value['entries']),
        carry_bytes=value['sum_bytes'], prior_sampled_aggregate_highwater_bytes=value['sum_bytes']))
    for item in checked:
        budget.check()
        identity.sealed_stat(item)
    return value


def observe_source(root, commit, budget):
    """Derive a complete Git/body map; no hand-maintained checker inventory."""
    from . import native_scale_identity as identity
    root = identity.path(str(root))
    budget.check()
    require(identity.git(root, 'rev-parse', 'HEAD') == commit, 'selected source commit drift')
    tree = identity.git(root, 'rev-parse', 'HEAD^{tree}')
    blobs, hashes = {}, {}
    for record in filter(None, identity.git(root, 'ls-tree', '-rz', '--full-tree', 'HEAD').split('\0')):
        budget.check()
        info, name = record.split('\t', 1)
        mode, kind, oid = info.split()
        require(mode in ('100644', '100755') and kind == 'blob', 'nonregular Git source')
        blobs[name] = oid
        hashes[name] = sha256(identity.path(str(root/name)))
    group = dict(root=str(root), commit=commit, tree=tree, inputs=sorted(blobs), git_blobs=blobs, sha256=hashes)
    identity.source_map(group)
    budget.check()
    return group


def stage_checkout(donor, destination, commit, budget, *, maximum_bytes):
    """Fresh local Git fetch/checkout; never resets or shares object storage."""
    import subprocess
    import time
    from .guard import load_runner
    require(os.name != 'nt', 'source staging uses the existing Linux/WSL checkout')
    require(not os.path.lexists(destination), 'fresh checkout destination required')
    environment = {key:value for key,value in os.environ.items() if not key.startswith('GIT_')}
    environment.update(GIT_OPTIONAL_LOCKS='0',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_TERMINAL_PROMPT='0')
    receipts = []
    destination.mkdir()
    def git(*args):
        budget.check()
        argv = ['git','-c','core.fsmonitor=false','-c','core.hooksPath='+os.devnull,
                '-C',str(destination),*args]
        process = subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                   env=environment,start_new_session=True)
        try:
            out,err = process.communicate(timeout=budget.remaining_seconds)
        except BaseException as error:
            try:
                load_runner().stop(process)  # Positively owned private process group only.
                process.communicate(timeout=5)
            except BaseException as cleanup_error:
                error.owned_subprocess_pending = True
                error.add_note('Git group='+str(process.pid)+' cleanup='+repr(cleanup_error))
            raise
        require(len(out)+len(err)<=1024**2, 'bounded fixed Git command capture')
        # Local fetch/checkout may spawn helpers; direct exit alone is not quiescence.
        until = min(time.monotonic()+5,time.monotonic()+budget.remaining_seconds)
        while True:
            try:os.killpg(process.pid,0)
            except ProcessLookupError:break
            if time.monotonic()>=until:
                error = OSError('Git helper process group not quiescent: '+str(process.pid))
                error.owned_subprocess_pending = True
                raise error
            time.sleep(.01)
        receipts.append(dict(argv=argv,code=process.returncode,stdout=out.decode(errors='replace'),
                             stderr=err.decode(errors='replace'),eof_reaped=True,process_group_absent=True))
        require(process.returncode == 0, 'source Git command failed: '+err.decode(errors='replace')[:4096])
        require(sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()) <= maximum_bytes,
                'fresh source checkout growth ceiling')
    git('init','--quiet')
    for key,value in (('core.autocrlf','false'),('core.filemode','false'),('core.fsmonitor','false'),('gc.auto','0')):
        git('config',key,value)
    git('fetch','--quiet','--no-tags','--depth=1',str(donor),commit)
    git('checkout','--quiet','--detach',commit)
    require(not (destination/'.git/objects/info/alternates').exists() and
            not list((destination/'.git/objects/pack').glob('*.promisor')), 'independent complete Git storage required')
    return receipts


def preparation_destination(directory, protected, *, staged_bootstrap=False):
    """Keep both preparation DATA roots outside every observed input pool."""
    bootstrap = directory.with_name(directory.name+'-inputs')
    require(not os.path.lexists(directory) and
            (bootstrap.is_dir() if staged_bootstrap else not os.path.lexists(bootstrap)) and
            bootstrap.parent.is_dir() and all(a != b and a not in b.parents and b not in a.parents
                for a in (directory, bootstrap) for b in protected),
            'fresh separate bootstrap DATA required')
    return bootstrap


def preparation_reservations(retained, current, observed_roots):
    """Merge historical maxima; active declarations cannot decrease a bound."""
    from pathlib import PureWindowsPath
    historical, active = {}, {}
    for rows, target in ((retained,historical),(current,active)):
        for row in rows:
            require(set(row) == {'root','reserved_bytes'} and type(row['reserved_bytes']) is int and
                    row['reserved_bytes'] > 0, 'finite preparation DATA reservation')
            root = PureWindowsPath(row['root'])
            require(root.is_absolute() and '..' not in root.parts, 'absolute preparation DATA reservation')
            if target is active:
                require(row['reserved_bytes'] >= historical.get(root,0), 'active preparation reservation decreased')
            target[root] = max(target.get(root,0),row['reserved_bytes'])
    merged = dict(historical)
    merged.update(active)
    roots = list(merged)
    require(all(root != other and not root.is_relative_to(other) and not other.is_relative_to(root)
        for i,root in enumerate(roots) for other in [*roots[i+1:],*map(PureWindowsPath,observed_roots)]),
        'disjoint preparation DATA reservation roots required')
    rows = [dict(root=str(root),reserved_bytes=amount)for root,amount in merged.items()]
    return rows, sum(merged.values()), sum(amount-historical.get(root,0)for root,amount in active.items())


def preparation_reservation_updates(definition, load, retained=None):
    """Read pinned refinements for an already declared DATA owner/root."""
    from pathlib import PureWindowsPath
    known = {PureWindowsPath(row['root']):row['reserved_bytes']for row in
             preparation_reservations(retained,[],[])[0]} if retained is not None else None
    rows = []
    for pin in definition.get('preparation_reservation_updates',[]):
        require(set(pin)=={'path','sha256'}, 'pinned preparation reservation refinement required')
        value = load(pin)
        require(set(value)=={'schema','root','previous_reserved_bytes','reserved_bytes','source_q_bytes'} and
            value['schema']=='native-preparation-reservation-refinement-v1' and
            value['source_q_bytes']==definition['source_q_bytes'] and
            type(value['previous_reserved_bytes'])is int and type(value['reserved_bytes'])is int and
            0<value['previous_reserved_bytes']<=value['reserved_bytes']<=definition['source_q_bytes'],
            'monotone same-owner preparation refinement required')
        root = PureWindowsPath(value['root'])
        if known is not None:
            require(root in known and value['previous_reserved_bytes']<=known[root]<=value['reserved_bytes'],
                    'active preparation refinement root/decrease')
        rows.append(dict(root=str(root),reserved_bytes=value['reserved_bytes']))
    return rows


def source_admission_bound(current, retained_floor, new_growth, reservations, new_reservations):
    return max(current+reservations, retained_floor+new_growth+new_reservations)


def selected_tools(previous, selected, pin):
    """Refresh exact bytes for the same explicit tool roles, before preparation."""
    require(isinstance(selected,list) and selected and all(
        set(item) == {'path','sha256'} and isinstance(item['path'],str) and
        isinstance(item['sha256'],str) and len(item['sha256']) == 64 and
        all(c in '0123456789abcdef' for c in item['sha256']) for item in selected),
        'explicit exact current tool pins required')
    require(len({item['path'] for item in selected}) == len(selected) and
            {item['path'] for item in selected} == {item['path'] for item in previous},
            'current tools must preserve exact role/path set')
    for item in selected:
        require(pin(item['path']) == item, 'selected current tool bytes changed: '+item['path'])
    return selected


def retained_preparation_reservations(records, load, source_q, *, local_refinement_pins=(), resolve_path=Path):
    """Retain admitted failed-preparation envelopes even without a final point."""
    from pathlib import PureWindowsPath
    require(all(set(item)=={'path','sha256'} for item in local_refinement_pins),
            'exact current refinement pins required')
    aliases={item['sha256']:item for item in local_refinement_pins}
    def refinement_load(item):
        selected=aliases.get(item['sha256'],item)
        try:
            return load(selected)
        except Exception as error:
            error.add_note('Retained refinement '+str(item)+'; selected local pin '+str(selected))
            raise
    rows = []
    staged_sources, refinements = {}, []
    for record in records:
        require({'manifest','stage','preparation'} <= set(record) <= {'manifest','stage','preparation','metadata_output'},
                'retained preparation provenance required')
        manifest, stage, preparation = (load(record[key]) for key in ('manifest','stage','preparation'))
        require(manifest['stage']['sha256'] == record['stage']['sha256'] and
                manifest['preparation']['sha256'] == record['preparation']['sha256'] and
                stage['preparation']['sha256'] == record['preparation']['sha256'] and
                preparation['source_q_bytes'] == source_q and
                stage['schema'] == 'native-tiny-stage-v1' and
                0 < stage['limits']['output_bytes'] <= 4*1024**2,
                'retained preparation manifest/declaration binding')
        require(type(preparation['preparation_limits']['storage_bytes']) is int and
                preparation['preparation_limits']['storage_bytes'] > 0, 'retained finite preparation storage')
        root = PureWindowsPath(stage['output'])
        require(type(stage['limits']['source_bytes']) is int and stage['limits']['source_bytes'] > 0,
                'retained finite staged-source bound')
        staged = PureWindowsPath(stage.get('destination',stage['output']))
        staged_sources[staged] = max(staged_sources.get(staged,0),stage['limits']['source_bytes'])
        refinements += preparation_reservation_updates(preparation,refinement_load)
        rows += [dict(root=str(root),reserved_bytes=preparation['preparation_limits']['storage_bytes']),
                 dict(root=str(root.with_name(root.name+'-inputs')),reserved_bytes=4*1024**2)]
        if 'metadata_output' in record:
            from .native_scale_identity import stamp
            extra=record['metadata_output']
            require(set(extra)=={'root','reserved_bytes','selection','peer_imports','observation','lifecycle','independent','terminal'},
                    'complete preparation metadata output custody required')
            namespace=PureWindowsPath(preparation['namespace'])
            require(PureWindowsPath(extra['root'])==namespace and type(extra['reserved_bytes'])is int and
                    0<extra['reserved_bytes']<=source_q,'exact preparation metadata owner/root/ceiling')
            require(set(extra['selection'])=={'path','sha256'} and
                extra['selection']['sha256']==preparation['namespace_disk_authority']['selection']['sha256'],
                'original metadata ceiling authority SHA required')
            selection=load(extra['selection'])
            require(extra['reserved_bytes']==selection['namespace_disk_bytes'],'original namespace UPPER required')
            imports,point,life,audit,terminal=(load(extra[k])for k in
                ('peer_imports','observation','lifecycle','independent','terminal'))
            emitted=load(point['plan']);scale=load(emitted['qualification']['scale_plan'])
            require(point['complete'] is True and point['qualification'] is False and
                point['product_runs']==point['scale_slots']==0 and point['previous_plan']==preparation['previous_plan'] and
                point['previous_preflight']==preparation['previous_preflight'] and
                emitted['actions_enabled'] is emitted['parent_scheduled'] is False and
                PureWindowsPath(emitted['qualification']['namespace'])==namespace,
                'closed pre-worker observation/metadata owner required')
            require(all(namespace!=PureWindowsPath(name) and not namespace.is_relative_to(PureWindowsPath(name)) and
                not PureWindowsPath(name).is_relative_to(namespace) for name in
                [*scale['owned_roots'],*emitted['source_reservation']['roots'],
                 *(row['root']for row in point['preparation_data_reservations'])]),
                'metadata namespace already counted in an observed pool/DATA row')
            require(life['passed'] is life['cleanup_passed'] is life['fixture_byte0_available_unlocked_closed'] is True and
                life['qualification'] is life['original_touched'] is False and life['product_runs']==0 and
                audit['cleanup_passed'] is audit['fixture_byte0_available_unlocked_closed'] is True and
                audit['qualification'] is audit['original_touched'] is False and audit['component_sha256']==extra['lifecycle']['sha256'] and
                len(audit['actor_and_keepers'])==3 and all(row['absent'] is True and row['error']==87 for row in audit['actor_and_keepers']) and
                type(terminal['code'])is int and terminal['code']!=0 and terminal['EOF'] is terminal['reaped'] is True,
                'positive terminal no-Tiny/Original/worker metadata custody required')
            require(imports['complete'] is imports['original_proof_bytes_preserved'] is True and
                imports['CSV_inputs_generated']==0 and imports['records'],'complete metadata-only import producer required')
            wanted={PureWindowsPath(pin['path']):pin['sha256'] for peer in emitted['qualification']['peers'].values() for pin in peer.values()}
            items=imports['records'];actual={PureWindowsPath(item['path']):item['sha256']for item in items}
            require(len(actual)==len(items) and actual==wanted and
                imports['copied_bytes']==sum(item['bytes']for item in items)<=extra['reserved_bytes'],
                'exact deduplicated metadata members/bytes required')
            root=resolve_path(str(namespace));directory=root/'imports'
            for member in (root,directory,*root.parents):
                fields=member.lstat()
                require(stat.S_ISDIR(fields.st_mode) and not stat.S_ISLNK(fields.st_mode) and
                    not getattr(fields,'st_file_attributes',0)&0x400,'metadata output directory alias/reparse')
            require({p.name for p in root.iterdir()}=={'imports'} and
                {p.name for p in directory.iterdir()}=={name.name for name in actual},'exact no-worker metadata namespace membership required')
            for item in items:
                name=PureWindowsPath(item['path']);file=resolve_path(str(name));before=stamp(file);fields=file.lstat()
                require(name.parent==namespace/'imports' and name.name==item['sha256']+'.json' and
                    stat.S_ISREG(fields.st_mode) and fields.st_nlink==1 and not getattr(fields,'st_file_attributes',0)&0x400 and
                    fields.st_size==item['bytes']<=8*1024**2 and sha256(file)==item['sha256'] and stamp(file)==before,
                    'metadata output member raw identity/alias drift')
            rows.append(dict(root=str(namespace),reserved_bytes=extra['reserved_bytes']))
    known = {PureWindowsPath(row['root'])for row in rows}
    require(all(PureWindowsPath(row['root'])in known for row in refinements),'historical preparation refinement root')
    rows,_,_ = preparation_reservations([*rows,*refinements],[],[])
    return rows, sum(staged_sources.values())


def preparation_components(definition, load, *, resolve_path=Path):
    """Inherit completed accounting closure, plus owned failed-preparation lifecycle output."""
    from pathlib import PureWindowsPath
    from .native_scale_identity import stamp
    point=load(definition['retained_source_point'])
    previous=load(definition['previous_plan']);observed=load(point['plan'])
    excluded={'actions_enabled','parent_scheduled','approved','enabled','environment_sha256'}
    def selected(value):
        return {k:v for k,v in dict(value,execution_kind=value.get('execution_kind','qualification')).items() if k not in excluded}
    require(point['complete'] is True and point['qualification'] is False and selected(observed)==selected(previous),
        'retained component point/previous plan linkage mismatch: '+str(definition['retained_source_point']))
    inherited=point['retained_component_points']
    components={}
    for item in [*inherited,*definition['retained_component_points']]:
        require(set(item)=={'path','sha256'},'exact retained component pin required')
        components[item['sha256']]=item
    for record in definition['retained_preparations']:
        stage=load(record['stage'])
        name=str(PureWindowsPath(stage['output'])/'lifecycle.json')
        file=resolve_path(name)
        if not os.path.lexists(file):
            continue  # Earlier setup denial can precede lifecycle; its whole DATA envelope remains retained.
        for member in (file, *file.parents):
            info=member.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,
                'owning lifecycle alias/reparse path: '+name)
        before=stamp(file)
        info=file.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=65536,
            'bounded regular single-link owning lifecycle output required: '+name)
        item=dict(path=name,sha256=sha256(file))
        require(stamp(file)==before,'owning lifecycle output changed: '+name)
        owner=load(record['preparation'])
        require(stage['preparation']['sha256']==record['preparation']['sha256'],'lifecycle owner preparation mismatch: '+name)
        fixture=PureWindowsPath(owner['harness']['root']).parent/('lifecycle-'+owner['attempt'])
        try:
            value=load(item)
            require(PureWindowsPath(value['normal_owner']['path'])==fixture/'fixture.lock' and
                all(PureWindowsPath(row['path']).is_relative_to(fixture) for row in value['current_fixture_inventory']),
                'lifecycle receipt wrong owner: '+name+'; expected fixture '+str(fixture))
            require(value['schema']=='native-lock-owner-lifecycle-v1' and value['passed'] is True and
                value['qualification'] is False and value['cleanup_passed'] is True and value['original_touched'] is False and
                value['product_runs']==0 and value['fixture_byte0_available_unlocked_closed'] is True,
                'closed owning lifecycle output required: '+name)
        except Exception as error:
            error.add_note('Owning lifecycle='+str(item)+'; preparation='+str(record['preparation']))
            raise
        components.setdefault(item['sha256'],item)
    for item in components.values():
        try:
            value=load(item)
            # Same existing observer family predicate; legacy API/publication proofs have no schema.
            require(value.get('passed',value.get('cleanup_passed')) is True and value['qualification'] is False,
                'retained component scope')
            require(isinstance(value['current_fixture_inventory'],list) and
                type(value['source_growth_envelope'])is int and value['source_growth_envelope']>=0 and
                type(value['parent_positive_logicalEOF_delta'])is int and value['parent_positive_logicalEOF_delta']>=0,
                'retained component accounting fields')
            require(all(isinstance(row['path'],str) and isinstance(row['stat'],dict) and
                type(row['stat']['mode'])is int for row in value['current_fixture_inventory']),
                'retained component inventory shape')
        except Exception as error:
            error.add_note('Component hash/path='+str(item)+'; owner point='+str(definition['retained_source_point']))
            raise
    return list(components.values())


def preflight_no_controller(failed, plan, failure, terminal):
    """Prove a rejected operator never crossed its qualify/Original boundary."""
    from . import native_tiny as tiny
    from .native_scale_identity import stamp
    require(failure['controller_pid'] is None and failure['qualification'] is False and
            isinstance(failure['error'],str) and failure['error'] and
            type(terminal['returncode']) is int and terminal['returncode'] != 0 and
            terminal['reaped'] is True and terminal['capture_files_closed'] is True,
            'failed preflight operator must be terminal without a controller')
    root = Path(failed['path'])
    require(Path(plan['owned_root']) == root/'data' and Path(plan['campaign']) == root/'campaign',
            'preflight rejection namespace owner mismatch')
    argv = terminal['argv']
    require(len(argv)>=6 and argv[-5]=='supervise' and argv[-3]=='--sha256' and argv[-1]=='--execute' and
            Path(argv[-6]) == Path(plan['harness']['root'])/'scripts/native-scale-runner.py',
            'terminal preflight operator command mismatch')
    operator_pin = dict(path=argv[-4],sha256=argv[-2])
    operator,_ = tiny.pinned_json(operator_pin,4*1024**2)
    require(Path(operator['namespace']) == root, 'terminal preflight operator namespace mismatch')
    evidence = Path(failed['preflight']['path']).parent
    files = [Path(failed['preflight']['path']),*(evidence/name for name in
             ('worker-result.json','runner/status.json','preparation-plan.json'))]
    before = {file:stamp(file) for file in files}
    pins = [dict(path=str(file),sha256=sha256(file)) for file in files]
    tiny.preflight(Path(failed['plan']['path']),plan,Path(failed['preflight']['path']),failed['preflight']['sha256'])
    require(all(stamp(file)==value for file,value in before.items()), 'retained preflight record changed')
    # These files precede every controller launch; data/campaign precede all workers.
    require(all(not os.path.lexists(root/name) for name in (
            'data','campaign','qualify-invocation.json','reservation.json','controller-pid.json','startup.json')) and
            not list(root.glob('controller-*.json')), 'preflight rejection crossed no-controller boundary')
    return [operator_pin,*pins]


def stage_current(definition, output, budget):
    """Bootstrap the maintained native preparer from the exact clean Linux source."""
    from pathlib import PureWindowsPath
    import shutil
    from .native_scale_control import create
    from .native_scale_identity import stamp
    require(os.name != 'nt' and set(definition) == {'schema','commit','destination','preparation','output','limits'} and
            definition['schema'] == 'native-tiny-stage-v1', 'Linux/WSL source stage definition required')
    require(set(definition['limits']) == {'seconds','read_bytes','visits','source_bytes','output_bytes'} and
            all(type(n) is int and n>0 for n in definition['limits'].values()), 'finite complete stage allowances')
    require(definition['limits']['output_bytes'] <= 4*1024**2, 'bootstrap DATA allowance exceeds recorded envelope')
    def mounted(value):
        current = PureWindowsPath(value)
        require(current.is_absolute() and current.drive.lower() == 'c:' and '..' not in current.parts,
                'reviewed absolute C: source destination required')
        return Path('/mnt/c',*current.parts[1:])
    def local_pin(item):
        name = item['path']
        current = mounted(name) if PureWindowsPath(name).drive else Path(name)
        require(current.is_absolute() and '..' not in current.parts and
                all(not q.is_symlink() for q in (current,*current.parents)), 'absolute nonsymlink stage input')
        before = stamp(current)
        require(current.stat().st_size <= 4*1024**2 and sha256(current) == item['sha256'], 'stage DATA pin drift')
        value = read_json(current,4*1024**2)
        require(stamp(current) == before, 'stage DATA producer drift')
        return value
    configuration = local_pin(definition['preparation'])
    validate_definition(configuration)
    cutoff, _ = authority_clocks(local_pin(configuration['continuation']))
    import time
    require(time.time() < cutoff, 'source stage launch cutoff expired')
    previous = local_pin(configuration['previous_plan'])
    retained=None
    if 'retained_windows_d' in configuration:
        from .native_scale_identity import retained_windows_d
        retained=retained_windows_d(previous,configuration['retained_windows_d'],resolve_path=mounted)
    def tool_pin(name):
        current = mounted(name)
        before = stamp(current)
        value = dict(path=name,sha256=sha256(current))
        require(stamp(current) == before, 'current tool producer drift')
        return value
    selected_tools(previous['tools'],configuration['tools'],tool_pin)
    failed_data, retained_stage_bound = retained_preparation_reservations(configuration['retained_preparations'],local_pin,
        configuration['source_q_bytes'],local_refinement_pins=configuration.get('preparation_reservation_updates',()),resolve_path=mounted)
    target = PureWindowsPath(definition['destination'])
    require(set(configuration['harness']) == {'root','commit'} and
            PureWindowsPath(configuration['harness']['root']) == target and
            configuration['harness']['commit'] == definition['commit'] and
            any(target.is_relative_to(PureWindowsPath(root)) for root in previous['source_reservation']['roots']),
            'same declared preparer/harness source reservation required')
    destination = mounted(str(target))
    require(destination.parent.is_dir() and not any(p.is_symlink() for p in destination.parents), 'stage parent/link')
    native_output = PureWindowsPath(definition['output'])
    prepared_output = mounted(str(native_output))
    bootstrap_root = prepared_output.with_name(prepared_output.name+'-inputs')
    native_bootstrap = native_output.with_name(native_output.name+'-inputs')/'definition.json'
    protected = [mounted(configuration['previous_plan']['path']),destination,
                 *(mounted(root) for root in previous['source_reservation']['roots']),
                 mounted(previous['qualification']['namespace'])]
    if retained:protected += [mounted(configuration['namespace']),*map(mounted,retained['plan']['owned_roots'])]
    preparation_destination(prepared_output, protected)
    output = Path(output).absolute()
    require(not output.exists() and not output.is_relative_to(destination), 'fresh separate stage receipt required')
    root = Path(__file__).resolve().parents[2]
    observe_source(root,definition['commit'],budget)
    local_point = local_pin(configuration['retained_source_point'])
    configuration=dict(configuration,retained_component_points=preparation_components(
        configuration,local_pin,resolve_path=mounted))
    foreign = local_pin(configuration['foreign_host_bound']) if configuration['foreign_host_bound'] else None
    foreign_upper = foreign['source_fit']['current']+foreign['source_fit']['remaining_write_reservation'] if foreign else 0
    old_data = local_point.get('preparation_data_reservations',[])
    historical,_,_ = preparation_reservations([*old_data,*failed_data],[],previous['source_reservation']['roots'])
    updates = preparation_reservation_updates(configuration,local_pin,historical)
    _,total,_ = preparation_reservations(historical,updates,previous['source_reservation']['roots'])
    _,old_total,_ = preparation_reservations(old_data,[],previous['source_reservation']['roots'])
    new_failed_data = total-old_total
    require(local_point['complete'] is True and
            local_point['source_conservative_with_fixture_directory_eof']+foreign_upper+new_failed_data+retained_stage_bound+
                definition['limits']['source_bytes']+definition['limits']['output_bytes']+
                configuration['preparation_limits']['storage_bytes'] <=
                configuration['source_q_bytes'], 'known local/foreign point plus bounded source stage must fit q')
    commands = stage_checkout(root,destination,definition['commit'],budget,maximum_bytes=definition['limits']['source_bytes'])
    group = observe_source(destination,definition['commit'],budget)
    group['root'] = str(target)
    bootstrap_root.mkdir()
    copied, copies = {}, []
    copied_bytes = 0
    def native_records(value):
        nonlocal copied_bytes
        if isinstance(value,dict):
            if {'path','sha256'} <= value.keys() and value['path'].startswith('/'):
                budget.check()
                source = Path(value['path'])
                require(source.is_absolute() and not source.is_symlink() and source.stat().st_size<=16*1024**2,
                        'bounded immutable Linux proof source required')
                before = stamp(source)
                raw = source.read_bytes()
                require(sha256(source)==value['sha256'] and stamp(source)==before,'operational proof source drift')
                name = value['sha256']+'.json'
                if name not in copied:
                    require(copied_bytes+len(raw)<=definition['limits']['output_bytes'],'bootstrap DATA ceiling')
                    with (bootstrap_root/name).open('xb') as stream:stream.write(raw)
                    require(sha256(bootstrap_root/name)==value['sha256'],'bootstrap proof destination drift')
                    copied[name] = True
                    copied_bytes += len(raw)
                copies.append(dict(source=value,source_stat=before,source_producer='Linux/WSL; not a Windows stat claim',
                    destination=str(native_bootstrap.parent/name),sha256=value['sha256']))
                return dict(value,path=str(native_bootstrap.parent/name))
            return {key:native_records(child) for key,child in value.items()}
        if isinstance(value,list):return [native_records(child) for child in value]
        return value
    native_definition = native_records(configuration)
    create(bootstrap_root/'definition.json',native_definition)
    native_sha = sha256(bootstrap_root/'definition.json')
    arguments = ['-B',str(target/'scripts/native-scale-runner.py'),'prepare',str(native_bootstrap),
                 str(native_output),'--sha256',native_sha]
    result = dict(schema='native-tiny-source-stage-v1',staged=True,admission=False,source=group,
        commands=commands,linux_stat_producer=True,native_metadata_reobservation_required=True,
        git_tool=dict(path=shutil.which('git'),sha256=sha256(shutil.which('git'))),
        bootstrap=dict(source=definition['preparation'],destination=str(native_bootstrap),
            relocated_proofs=copies,destination_body_sha256=native_sha),
        preparer_argv=[previous['python']['path'],*arguments],
        wsl_preparer_argv=['/usr/bin/env','CHOPPER_WINDOWS_PYTHON='+previous['python']['path'],
            sys.executable,'-B',str(root/'scripts/windows-native.py'),'--checkout',str(destination),
            '--expect-commit',definition['commit'],'python','--',*arguments])
    require(copied_bytes+(bootstrap_root/'definition.json').stat().st_size+
            len((json.dumps(result,sort_keys=True,indent=2)+'\n').encode())<=definition['limits']['output_bytes'],
            'complete bootstrap DATA/receipt allowance exceeded')
    create(output,result)
    return dict(receipt=str(output),sha256=sha256(output),staged=True,admission=False)


def authority_clocks(continuation):
    from datetime import datetime
    require(continuation['schema'] == 'chopper-unattended-continuation-v1' and
            continuation['non_time_allowances_renewed'] is False, 'owning continuation; no cap reset')
    cutoff = datetime.fromisoformat(continuation['launch_cutoff_utc'])
    stop = datetime.fromisoformat(continuation['deadline_utc'])
    require(cutoff.utcoffset() is not None and stop.utcoffset() is not None and cutoff < stop,
            'explicit ordered timezone-aware authority clocks')
    return cutoff.timestamp(),stop.timestamp()



def validate_definition(definition):
    """One preparation declaration contract, before stage or native observation."""
    if definition.get('schema') == 'native-windows-scale-preparation-v1':
        required = {'schema','previous_plan','previous_preflight','frozen_batch','namespace',
            'authorization','continuation','preparation_limits','preflight_limits','retained_source_point','linux','peers','claim_parent','input_root'}
        require(required <= set(definition) <= required|{'retained_windows_d'},
            'complete Windows scale preparation definition fields')
        limits=definition['preparation_limits']
        require(set(limits)=={'seconds','read_bytes','visits','storage_bytes'} and
            all(type(n) is int and n>0 for n in limits.values()),'finite scale preparation allowances')
        parent=definition['claim_parent']
        from pathlib import PurePosixPath
        require(set(parent)=={'python','python_sha256','runner'} and
            all(PurePosixPath(parent[k]).is_absolute() for k in ('python','runner')) and
            len(parent['python_sha256'])==64, 'explicit Linux parent claim roles required')
        return limits
    if definition.get('schema') == 'native-tiny-linux-preparation-v1':
        required = {'schema','previous_plan','harness','namespace','authorization','continuation',
                    'preparation_limits','preflight_limits'}
        require(required <= set(definition) <= required|{'execution_kind','frozen_batch','metadata_per_process'},
                'complete Linux preparation definition fields')
        require(set(definition['harness']) == {'root','commit'}, 'selected harness root/commit only')
        limits = definition['preparation_limits']
        require(set(limits) == {'seconds','read_bytes','visits','storage_bytes'} and
                all(type(n) is int and n > 0 for n in limits.values()), 'finite preparation allowances')
        if 'execution_kind' in definition or 'frozen_batch' in definition:
            from .hosted_qualification import execution_selection
            execution_selection(definition)
        return limits
    required = {'schema', 'previous_plan', 'previous_preflight', 'authorization', 'continuation', 'harness',
        'attempt', 'preparation_limits', 'preflight_limits',
        'latest_source_history', 'retained_source_point', 'retained_namespace_history',
        'namespace_point', 'retained_failed_namespaces', 'retained_source_fixture_growth',
        'retained_component_points', 'failed_component_interval',
        'additional_failed_component_intervals', 'source_q_bytes'}
    required.update(('foreign_host_bound','tools','retained_preparations'))
    require(required <= set(definition) <= required|{'preparation_reservation_updates','execution_kind','frozen_batch','retained_completed_namespaces','namespace_disk_authority','retained_windows_d','namespace'} and definition['schema'] == 'native-tiny-preparation-v1',
            'complete native preparation definition fields')
    require(('namespace' in definition) == ('retained_windows_d' in definition),
            'retained WindowsD requires a fresh separate Tiny namespace')
    require(set(definition['harness']) == {'root', 'commit'}, 'selected harness root/commit only')
    if 'execution_kind' in definition or 'frozen_batch' in definition:
        from .hosted_qualification import execution_selection
        execution_selection(definition)
    limits = definition['preparation_limits']
    require(set(limits) == {'seconds', 'read_bytes', 'visits', 'storage_bytes'} and
            all(type(n) is int and n > 0 for n in limits.values()), 'finite preparation allowances')
    return limits


def prepare_current(definition, directory, budget):
    """Observe, derive a disabled plan, then generate its complete parent protocol."""
    from .native_scale_identity import path
    limits = validate_definition(definition)
    if definition['schema'] == 'native-windows-scale-preparation-v1':
        return prepare_windows_scale(definition,directory,budget)
    if definition['schema'] == 'native-tiny-linux-preparation-v1':
        return prepare_linux(definition, directory, budget)
    directory = path(str(directory))
    from .native_tiny import pinned_json
    previous, _ = pinned_json(definition['previous_plan'], 4*1024**2)
    from .native_scale_identity import stamp
    def tool_pin(name):
        current = path(name)
        before = stamp(current)
        value = dict(path=str(current),sha256=sha256(current))
        require(stamp(current) == before, 'current tool producer drift')
        return value
    selected_tools(previous['tools'],definition['tools'],tool_pin)
    definition=dict(definition,retained_component_points=preparation_components(
        definition,lambda item:pinned_json(item,4*1024**2)[0],resolve_path=path))
    retained,_ = retained_preparation_reservations(definition['retained_preparations'],
        lambda item:pinned_json(item,4*1024**2)[0],definition['source_q_bytes'],
        local_refinement_pins=definition.get('preparation_reservation_updates',()),resolve_path=path)
    preparation_reservation_updates(definition,lambda item:pinned_json(item,4*1024**2)[0],retained)
    pinned_json(definition['authorization'], 4*1024**2)
    continuation, _ = pinned_json(definition['continuation'], 65536)
    cutoff,stop = authority_clocks(continuation)
    retained = None
    if 'retained_windows_d' in definition:
        from .native_scale_identity import retained_windows_d
        retained = retained_windows_d(previous,definition['retained_windows_d'])
    if retained:
        fresh_namespace=path(definition['namespace'])
        require(not os.path.lexists(fresh_namespace) and all(not fresh_namespace.is_relative_to(path(name)) and
            not path(name).is_relative_to(fresh_namespace) for name in
            [*retained['plan']['owned_roots'],*retained['plan']['source_reservation']['roots']]),
            'fresh Tiny namespace must be absent and disjoint from retained Windows roots')
    protected = [*(map(path,retained['plan']['owned_roots']) if retained else ()),
                 path(previous['qualification']['namespace']), *map(path, previous['owned_roots']),
                 *map(path, previous['source_reservation']['roots'])]
    if retained:protected.append(fresh_namespace)
    preparation_destination(directory, protected, staged_bootstrap=True)
    budget.check()
    require(Path(__file__).resolve().parent == path(definition['harness']['root'])/'scripts/scale_acceptance',
            'prepare must run from selected harness')
    observe_source(definition['harness']['root'], definition['harness']['commit'], budget)
    directory.mkdir(mode=0o700)
    # Exercise the actual checker parser, including its deterministic capture
    # storage constraints, before spending any native lifecycle/inventory work.
    from .native_scale_control import create
    from .native_scale_host import module
    request_shape = directory/'request-shape.json'
    create(request_shape, dict(schema='chopper-acceptance-preflight-v1', profile='native',
        host_os=previous['os'], plan=definition['previous_plan']['path'],
        plan_sha256=definition['previous_plan']['sha256'], limits=definition['preflight_limits']))
    module('acceptance-preflight').request(request_shape)
    from .native_scale_host import bounded
    lifecycle = bounded(lambda:lifecycle_check(definition,previous,directory,budget),
                        seconds=min(60,budget.remaining_seconds))
    d = dict(definition, launch_cutoff_unix=cutoff, stop_unix=stop,
        collector_limits=dict(seconds=limits['seconds'], output_bytes=limits['storage_bytes']))
    d['preparation_data_reservations'] = [dict(root=str(directory),reserved_bytes=limits['storage_bytes']),
        dict(root=str(directory.with_name(directory.name+'-inputs')),reserved_bytes=4*1024**2)]
    d['retained_component_points'] = [*definition['retained_component_points'], lifecycle]
    observed = observe_plan(d, directory/'observation', budget)
    execution = {}
    if 'execution_kind' in definition or 'frozen_batch' in definition:
        from .hosted_qualification import execution_selection
        execution = execution_selection(definition)
    if execution:
        value = read_json(observed['path'],4*1024**2)
        value.update(execution)
        selected = directory/'batch-plan.DISABLED.json'
        create(selected,value)
        observed = dict(path=str(selected),sha256=sha256(selected))
    result = prepare_packet(dict(schema=definition['schema'], plan=observed,
        authorization=definition['authorization'], preflight_limits=definition['preflight_limits']),
        directory/'prepared', budget)
    require(sum(p.stat().st_size for p in directory.rglob('*') if p.is_file()) <= limits['storage_bytes'],
            'complete preparation output allowance exceeded')
    return result


def prepare_linux(definition, directory, budget):
    """Derive a fresh Linux attempt from the retained complete inventory and debt."""
    import copy
    import time
    from . import native_tiny as tiny
    from .native_scale_control import create
    from .native_scale_identity import path, stamp
    require(sys.platform.startswith('linux'), 'actual Linux preparation required')
    previous, _ = tiny.pinned_json(definition['previous_plan'], 4*1024**2)
    require(previous['os'] == 'Linux' and tiny.enabled(previous), 'complete Linux Tiny template required')
    scale = copy.deepcopy(tiny.validate(previous))
    metadata = definition.get('metadata_per_process', previous['qualification']['metadata_per_process'])
    retained_metadata = previous['qualification']['metadata_per_process']
    require(set(metadata) == {'read_bytes','visits'} and
            all(type(metadata[key]) is int and 0 < metadata[key] <= retained_metadata[key]
                for key in retained_metadata), 'Linux metadata allowance must not increase retained per-process limits')
    tiny.pinned_json(definition['authorization'], 4*1024**2)
    continuation, _ = tiny.pinned_json(definition['continuation'], 65536)
    cutoff, stop = authority_clocks(continuation)
    require(time.time() < cutoff, 'Linux preparation launch cutoff expired')
    directory, namespace = path(str(directory)), path(definition['namespace'])
    protected = [path(previous['qualification']['namespace']), namespace, path(definition['harness']['root']),
                 *map(path,previous['owned_roots']), *map(path,previous['source_reservation']['roots'])]
    bootstrap = preparation_destination(directory, protected)
    require(not os.path.lexists(namespace), 'fresh Linux namespace required')
    harness = observe_source(definition['harness']['root'], definition['harness']['commit'], budget)
    require(Path(__file__).resolve().parent == path(harness['root'])/'scripts/scale_acceptance',
            'prepare must run from selected harness')
    scale['harness'] = harness
    scale['source_reservation'] = copy.deepcopy(previous['source_reservation'])
    for root in (harness['root'], str(bootstrap), str(directory)):
        if root not in scale['source_reservation']['roots']:
            scale['source_reservation']['roots'].append(root)
    # Static preparation data and all retained attempts remain charged; the
    # original source ceiling and scale lineage are unchanged.
    bootstrap.mkdir(mode=0o700)
    written = 0
    def write(name, value):
        nonlocal written
        raw = (json.dumps(value,sort_keys=True,indent=2)+'\n').encode('utf-8')
        require(len(raw) <= 4*1024**2 and written+len(raw) <= definition['preparation_limits']['storage_bytes'],
                'Linux preparation output ceiling before write')
        create(bootstrap/name,value)
        written += len(raw)
        return bootstrap/name
    scale_file = bootstrap/'scale-reference.DISABLED.json'
    write(scale_file.name, scale)
    plan = copy.deepcopy(previous)
    plan.update(harness=harness, source_reservation=scale['source_reservation'],
                owned_root=str(namespace/'data'), campaign=str(namespace/'campaign'),
                actions_enabled=False, parent_scheduled=False, enabled=False, approved=False)
    plan['owned_roots'] = [*previous['owned_roots'], plan['owned_root'], plan['campaign']]
    plan['qualification'].update(metadata_per_process=dict(metadata),
        namespace=str(namespace), launch_cutoff_unix=cutoff, stop_unix=stop,
        original_lock_stat=stamp(path(plan['reservation']['lock_path'])),
        scale_plan=dict(path=str(scale_file),sha256=sha256(scale_file)))
    plan.pop('execution_kind',None);plan.pop('frozen_batch',None)
    if 'execution_kind' in definition or 'frozen_batch' in definition:
        from .hosted_qualification import execution_selection
        plan.update(execution_selection(definition))
    plan_file = bootstrap/'tiny-plan.DISABLED.json'
    write(plan_file.name, plan)
    result = prepare_packet(dict(schema='native-tiny-preparation-v1',
        plan=dict(path=str(plan_file),sha256=sha256(plan_file)),
        authorization=definition['authorization'], preflight_limits=definition['preflight_limits']), directory, budget,
        output_limit=definition['preparation_limits']['storage_bytes']-written)
    require(sum(p.stat().st_size for root in (bootstrap,directory) for p in root.rglob('*') if p.is_file()) <=
            definition['preparation_limits']['storage_bytes'], 'complete Linux preparation output allowance exceeded')
    return result


def lifecycle_check(definition, previous, directory, budget):
    """Run the maintained temporary-lock component before sealing source history."""
    import time
    import secrets
    from .native_scale_control import create
    from . import native_scale_host as host, native_scale_identity as identity
    scripts = identity.path(definition['harness']['root'])/'scripts'
    fixture = scripts.parent.parent/('lifecycle-'+definition['attempt'])
    require(any(fixture.is_relative_to(identity.path(root)) for root in previous['source_reservation']['roots']),
            'temporary fixture source reservation missing')
    output = directory/'lifecycle.json'
    argv = [sys.executable, '-B', str(scripts/'native-scale-runner.py'),
            '_lifecycle', str(fixture), str(output)]
    budget.check()
    create(directory/'lifecycle-invocation.json', dict(argv=argv, original_touched=False, product_runs=0,
        fixture_growth_bytes=65536, read_bytes=128*1024**2, visits=2_000_000, seconds=60))
    process = None
    created = None
    keeper_scope_closed = True  # No actor exists until construction/start is attempted.
    windows = host.module('browser-small-windows')
    started = time.monotonic()
    try:
        with (directory/'lifecycle-stdout.log').open('xb') as out, (directory/'lifecycle-stderr.log').open('xb') as err:
            process = host.windows_bootstrap.SuspendedWorker()
            keeper_scope_closed = False
            def record(event,value):
                nonlocal created
                if event == 'created':created = value['identity']
                create(directory/('lifecycle-controller-'+event+'.json'),value)
            process.start_controller(argv,out,err,dict(os.environ),directory/'lifecycle-stderr.log',
                                     windows,secrets.token_hex(32),record)
            owned_context = windows.query_job(process.controller_job)
            require(owned_context['flags'] == 0x800 and process.controller_ack_attempted,
                    'actual selected post-ACK context required')
            create(directory/'lifecycle-context.json',dict(owned_job=owned_context,
                inherited_ancestor_jobs='UNKNOWN',launcher='SuspendedWorker.start_controller'))
            code = process.wait(timeout=max(0,min(60-(time.monotonic()-started),budget.remaining_seconds)))
        closed_job = process.finish_controller(windows)
        process = None
        create(directory/'lifecycle-controller-closed.json',closed_job)
        require(all((directory/name).stat().st_size <= 65536 for name in
                    ('lifecycle-stdout.log','lifecycle-stderr.log','lifecycle.json')),
                'bounded component captures/evidence')
        value = read_json(output,65536)
        require(value['actor'] == created,
                'exact lifecycle actor birth')
        keeper_scope_closed = value['measurement_complete'] is True and value['cleanup_passed'] is True
        require(code == 0 and value['measurement_complete'] is True and value['cleanup_passed'] is True,
                'lifecycle measurement cleanup incomplete')
        controls = host.module('test-native-file-allocation')
        births = [value['actor']]
        if value['candidate_supported'] is True:
            births += [value['normal_owner']['owner_identity'], value['constructor_rejection']['closed']]
        else:
            births += [value['closed']]
        proof = controls.exited_births(tuple(births))
        # This is an independent noncreating fixture probe, never the acceptance lock.
        lock = fixture/'fixture.lock'
        before = identity.stamp(lock)
        import msvcrt
        fd = os.open(lock,os.O_RDWR|os.O_BINARY)
        acquired = False
        try:
            observed = os.fstat(fd)
            original_fd = [observed.st_dev,observed.st_ino,observed.st_size,observed.st_mtime_ns,
                           observed.st_ctime_ns,observed.st_mode]
            require(original_fd[:4] == before[:4], 'fixture descriptor/path identity mismatch')
            msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            acquired = True
            require(identity.stamp(lock) == before, 'fixture drift under independent probe')
            msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
            acquired = False
            observed = os.fstat(fd)
            require([observed.st_dev,observed.st_ino,observed.st_size,observed.st_mtime_ns,
                     observed.st_ctime_ns,observed.st_mode] == original_fd, 'fixture descriptor drift')
        finally:
            if acquired:msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
            os.close(fd)
        require(identity.stamp(lock) == before, 'fixture stat drift after independent close')
        create(directory/'lifecycle-after-exit.json', dict(cleanup_passed=True,qualification=False,
            original_touched=False,actor_and_keepers=proof,fixture_byte0_available_unlocked_closed=True,
            component_sha256=sha256(output)))
        require(time.monotonic()-started<60,'complete lifecycle component exceeded sixty seconds')
        require(value['candidate_supported'] is True and value['passed'] is True,
                'temporary keeper lifecycle unsupported; stop before preparation/Tiny')
        return dict(path=str(output),sha256=sha256(output))
    except BaseException as error:
        if process is not None:
            try:
                closed = process.controller_no_start_closed
                if closed is not None and closed.get('no_ack') is True:
                    keeper_scope_closed = True  # The source barrier never admitted fixture/keeper creation.
                if closed is None and process.poll() is not None:
                    closed = process.finish_controller(windows)
                if closed is not None:
                    require(closed['handles_closed'] is True and closed['job']['pids'] == [],
                            'positive lifecycle actor closure required')
                    process = None
                    create(directory/'lifecycle-controller-failed-closed.json',closed)
            except BaseException as cleanup_error:
                try:error.add_note('lifecycle actor closure unknown: '+repr(cleanup_error))
                except BaseException:pass
        try:
            create(directory/'lifecycle-failed.json', dict(error=repr(error),qualification=False,
                pid=process.pid if process is not None else None,
                actor_closed=process is None, keeper_scope_closed=keeper_scope_closed,
                ownership_uncertain=process is not None or not keeper_scope_closed))
        except BaseException:
            pass
        if not keeper_scope_closed and created is not None:
            try:
                partial = read_json(output,65536)
                keeper_scope_closed = (partial['actor'] == created and
                    partial.get('measurement_complete') is True and partial.get('cleanup_passed') is True)
            except BaseException:
                pass
        if process is not None or not keeper_scope_closed:
            # No automatic kill of a query/fixture keeper with unknown closure.
            while True:time.sleep(1)
        raise


def prepare_windows_scale(d, directory, budget):
    """Derive the selected Large plan from its fresh complete Tiny and current NTFS."""
    import copy
    import time
    from . import native_scale_identity as identity, native_tiny as tiny
    from .native_scale_control import create, native_recipe
    require(os.name == 'nt', 'prepare Windows scale on the actual native host')
    previous, _ = tiny.pinned_json(d['previous_plan'],4*1024**2)
    require(tiny.enabled(previous) and previous['os'] == 'Windows' and previous['host'] == host(),
            'matching current Windows Tiny required')
    require(Path(sys.executable).resolve()==Path(previous['python']['path']) and sys.version==previous['python']['version'],
            'actual selected preparation Python required')
    tiny.preflight(identity.path(d['previous_plan']['path']),previous,
        identity.path(d['previous_preflight']['path']),d['previous_preflight']['sha256'])
    from .hosted_qualification import qualified_batch, batch_admission
    require(qualified_batch(d['frozen_batch'],previous,'native') is not None,
            'complete matching Tiny/frozen definition required')
    continuation, _ = tiny.pinned_json(d['continuation'],65536)
    cutoff, stop = authority_clocks(continuation)
    require(time.time() < cutoff < stop, 'fresh scale authority clocks required')
    directory, namespace = identity.path(str(directory)),identity.path(d['namespace'])
    require(not directory.exists() and not namespace.exists(), 'fresh scale preparation/attempt required')
    roots = set(tiny.retained_roots(previous,tiny.reference(previous)))|{previous['qualification']['namespace']}
    retained = identity.retained_windows_d(previous,d['retained_windows_d']) if 'retained_windows_d' in d else None
    if retained:
        require(set(retained['plan']['source_reservation']['roots']) <= set(previous['source_reservation']['roots']),
                'retained D source roots must survive fresh qualification')
        roots.update(retained['plan']['owned_roots'])
    roots = {name for name in roots if not any(identity.path(name) != identity.path(other) and
        identity.path(name).is_relative_to(identity.path(other)) for other in roots)}
    input_root=identity.path(d['input_root'])
    require(input_root.is_dir() and all(item.is_file() and not item.is_symlink() for item in input_root.iterdir()),
        'flat immutable scale bootstrap inputs required')
    require(all(not input_root.is_relative_to(identity.path(name)) and not identity.path(name).is_relative_to(input_root)
        for name in [*roots,*previous['source_reservation']['roots']]),'fresh disjoint bootstrap input owner required')
    source_roots = [*previous['source_reservation']['roots'],str(input_root)]
    require(all(not a.is_relative_to(b) and not b.is_relative_to(a) for a in (directory,namespace)
        for b in map(identity.path,[*roots,*source_roots])) and
        not directory.is_relative_to(namespace) and not namespace.is_relative_to(directory),
        'new scale output/data must be disjoint from retained inputs')
    written=0
    def emit(name,value):
        nonlocal written
        budget.check()
        raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
        require(written+len(raw)<=d['preparation_limits']['storage_bytes'],'scale preparation output ceiling')
        create(directory/name,value);written+=len(raw)
        return dict(path=str(directory/name),sha256=sha256(directory/name))
    # All irreversible admission and budget checks precede any output directory.
    point,_=tiny.pinned_json(d['retained_source_point'],4*1024**2)
    observed,_=tiny.pinned_json(point['plan'],4*1024**2)
    freeze_fields={'actions_enabled','parent_scheduled','approved','enabled','environment_sha256'}
    observed=dict(observed,execution_kind=observed.get('execution_kind','qualification'))
    qualified=dict(previous,execution_kind=previous.get('execution_kind','qualification'))
    require(point['complete'] is True and point['qualification'] is False and
        {k:v for k,v in observed.items() if k not in freeze_fields} ==
        {k:v for k,v in qualified.items() if k not in freeze_fields},
        'exact previous disabled observation/frozen configuration required')
    old,_=tiny.pinned_json(previous['qualification']['windows_history'],64*1024**2)
    baselines={pool:observe_baseline([identity.path(r) for r in names],budget) for pool,names in
        (('native',sorted(roots)),('source',source_roots))}
    prior={}
    for pool,baseline in baselines.items():
        old_charges=tiny.History._baseline_charges(old['baselines'][pool])
        current=tiny.History._baseline_charges(baseline)
        growth=sum(max(0,amount-old_charges.get(key,0)) for key,amount in current.items())
        carry=old['prior_storage'][pool]['carry_bytes']+growth
        if pool=='native':
            carry+=tiny.namespace_retirement_debt(previous,baseline)
        if pool=='source':
            input_baseline=next(item for item in baseline['roots'] if item['path']==str(input_root))
            input_charge=sum(item['charge_bytes'] for item in baseline['entries'] if Path(item['path']).is_relative_to(input_root))
            require(input_charge+input_baseline['stat']['size']<=4*1024**2,'scale bootstrap DATA envelope4MiB')
            carry=(max(old['prior_storage'][pool]['carry_bytes'],point['combined_source_admission_bound'])+growth+
                input_baseline['stat']['size']+d['preparation_limits']['storage_bytes'])
        prior[pool]=dict(sum_bytes=baseline['sum_bytes'],entry_count=len(current),carry_bytes=carry,
            prior_sampled_aggregate_highwater_bytes=carry)
    require(prior['source']['carry_bytes']<=previous['source_reservation']['bytes'], 'unchanged source ceiling')
    require(prior['native']['carry_bytes']<previous['limits']['owned_bytes'],'native retained capacity')
    require(set(d['linux'])=={'plan','completion','claims','records','consumed','canonical_slot_ledger'},
        'complete exact Linux predecessor proof fields')
    plan=copy.deepcopy(previous)
    for name in ('qualification','frozen_batch'):
        plan.pop(name,None)
    plan.update(actions_enabled=False,parent_scheduled=False,approved=False,enabled=False,
        execution_kind='batch',frozen_batch=d['frozen_batch'],owned_root=str(namespace/'data'),
        campaign=str(namespace/'campaign'),owned_roots=[*sorted(roots),str(namespace/'data'),str(namespace/'campaign')],
        fixtures={shape:native_recipe(shape) for shape in ('D','G')},peers=d['peers'],
        source_reservation=dict(previous['source_reservation'],roots=source_roots),
        windows_execution=dict(namespace=str(namespace),original_lock_stat=identity.stamp(identity.path(plan['reservation']['lock_path'])),
            launch_cutoff_unix=cutoff,stop_unix=stop))
    # Elapsed time includes the complete current Tiny; no generation/time refund.
    started=read_json(identity.path(previous['campaign'])/'Windows-started.json')
    debit=max(old['prior_generation_ms'],int((time.time()-started['started'])*1000)+started['prior_generation_ms'])
    if retained:
        debit=max(debit,int((time.time()-retained['started']['started'])*1000)+retained['started']['prior_generation_ms'])
        require(all(prior[pool]['carry_bytes'] >= amount for pool,amount in retained['floors'].items()),
                'fresh Tiny must retain prior Windows highwaters')
    history=dict(baselines=baselines,prior_storage=prior,prior_generation_ms=debit,
        fresh_roots=[plan['owned_root'],plan['campaign']],allocation_origin=dict(old['allocation_origin'],
            carry_metric='sampled allocation plus retained opaque/envelope upper bounds; not physical peak'),
        retained_transition=dict(previous_plan=d['previous_plan'],previous_preflight=d['previous_preflight']))
    # Pinned Linux records are individual immutable custody receipts, never a copied family directory.
    for section in ('claims','records','consumed'):
        require(set(d['linux'][section])=={'D','G'},'complete Linux predecessor shapes required')
    for item in [d['linux']['plan'],d['linux']['completion'],*d['linux']['claims'].values(),
        *d['linux']['records'].values(),*d['linux']['consumed'].values(),*d['peers'].values()]:
        tiny.pinned_json(item,16*1024**2);budget.check()
    identity.dependency_metadata(previous['dependencies'],identity.runtime_requirements())
    directory.mkdir(mode=0o700)
    descriptor=dict(schema='selected639-windows-lineage-v1',host=plan['host'],selected_product=identity.PRODUCT,
        provenance=[d['authorization'],d['continuation'],d['retained_source_point']],linux=d['linux'],storage=history,
        claim_parent=d['claim_parent'])
    if retained:descriptor['retained_windows_d']=d['retained_windows_d']
    plan['windows_lineage']=emit('windows-lineage.json',descriptor)
    identity.Lineage(plan)
    batch_admission(plan,'native')
    disabled=emit('disabled-scale-plan.json',plan)
    result=prepare_packet(dict(schema='native-tiny-preparation-v1',plan=disabled,
        authorization=d['authorization'],preflight_limits=d['preflight_limits']),directory/'packet',budget,
        output_limit=d['preparation_limits']['storage_bytes']-written)
    emit('scale-observation.json',dict(complete=True,qualification=False,scale_slots=0,plan=disabled,
        source_carry=prior['source']['carry_bytes'],source_q_bytes=plan['source_reservation']['bytes'],
        preparation_envelope=d['preparation_limits']['storage_bytes'],retained_source_point=d['retained_source_point']))
    return result


def attempt_root(plan, parse):
    """The retained namespace can contain several fresh, separate attempts."""
    data, campaign = parse(plan['owned_root']), parse(plan['campaign'])
    root = data.parent
    require(campaign.parent == root and data != campaign and
            root.is_relative_to(parse((plan['qualification'] if 'qualification' in plan else plan['windows_execution'])['namespace'])),
            'fresh data/campaign must share an attempt under the retained namespace')
    return root


def prepare_packet(definition, directory, budget, *, output_limit=None):
    """Generate one disabled Tiny packet from owning contracts, never launch it.

    The definition names immutable inputs and preparation allowances. Paths,
    commands and the hashing closure come from the selected plan, rather than
    copied command templates. Actual-host preflight and explicit approvals remain
    separate execution gates.
    """
    from .native_scale_control import create
    from .native_scale_identity import path, stamp
    from . import native_tiny as tiny
    budget.check()
    require(set(definition) == {'schema', 'plan', 'authorization', 'preflight_limits'} and
            definition['schema'] == 'native-tiny-preparation-v1', 'native preparation definition fields')
    pins = {}
    for name in ('plan', 'authorization'):
        item = definition[name]
        require(set(item) == {'path', 'sha256'}, 'exact preparation input pin required')
        before = stamp(path(item['path']))
        require(sha256(item['path']) == item['sha256'], name+' pin drift')
        require(stamp(path(item['path'])) == before, name+' stat drift')
        pins[name] = dict(item, stat=before)
    plan = read_json(definition['plan']['path'], 4*1024**2)
    large = plan['os'] == 'Windows' and not tiny.enabled(plan) and 'windows_lineage' in plan
    require(plan['actions_enabled'] is False and plan['parent_scheduled'] is False and (tiny.enabled(plan) or large),
            'disabled complete Tiny plan required')
    validate_preparation(plan)
    if plan.get('execution_kind') == 'batch':
        from .hosted_qualification import batch_admission
        batch_admission(plan,'native')
    require(plan['os'] == ('Windows' if os.name == 'nt' else 'Linux'), 'prepare on selected native OS')
    limits = definition['preflight_limits']
    require(set(limits) == {'seconds', 'read_bytes', 'visits', 'storage_bytes', 'capture_bytes'} and
            all(type(value) is int and value > 0 for value in limits.values()),
            'explicit positive preparation allowances required')
    directory = path(str(directory))
    namespace = attempt_root(plan, path)
    protected = [path((plan['windows_execution'] if large else plan['qualification'])['namespace']), *map(path, plan['owned_roots']),
                 *map(path, plan['source_reservation']['roots'])]
    # Linux's generated packet is itself an explicitly reserved fresh source
    # root. No input may overlap it (checked below); it is populated only here.
    protected = [root for root in protected if not (plan['os'] == 'Linux' and root == directory)]
    require(all(directory != root and directory not in root.parents and root not in directory.parents
                for root in protected), 'preparation output overlaps observed namespace/source')
    require(not os.path.lexists(directory) and not os.path.lexists(namespace),
            'fresh preparation output and Tiny namespace required')
    # Resolve the complete owning input closure before creating any output.
    closure = preparation_inputs(plan)
    require(all(not path(name).is_relative_to(directory) for name in closure),
            'preparation output/input collision')
    for group in (plan['product'], plan['harness'], *plan['dependencies']):
        budget.check()
        if 'git_blobs' in group:
            source_map(group)
        else:
            for name, expected in group['sha256'].items():
                budget.check()
                require(sha256(path(group['root'])/name) == expected, 'dependency byte drift: '+name)
    file_pins = {}
    for name in closure:
        budget.check()
        current = path(name)
        before = stamp(current)
        file_pins[name] = dict(sha256=sha256(current), stat=before)
        require(stamp(current) == before, 'preparation input changed: '+name)
    scripts = path(plan['harness']['root'])/'scripts'
    python = plan['python']['path']
    plan_file = namespace/('scale-plan.json' if large else 'tiny-plan.json')
    request_file = namespace/'request.json'
    preflight_file = namespace/'preflight/result.json'
    commands = dict(supervise=[python, '-B', str(scripts/'native-scale-runner.py'),
        'supervise', str(directory/'operator.json'), '--sha256'],
        after_exit=[python, '-E', '-s', '-B', str(scripts/'native-scale-runner.py'),
        'after-exit', str(directory/'operator.json'), '--sha256'])
    from .native_scale_identity import execution_shapes
    shapes=execution_shapes(plan)
    packet = dict(schema='native-scale-prepared-v1' if large else 'native-tiny-prepared-v1', inputs=pins, namespace=str(namespace),
        source_roles={key: plan[key] for key in ('product', 'harness', 'dependencies')},
        preparation_inputs=file_pins, preflight_limits=limits, commands=commands,
        paths=dict(plan=str(plan_file),request=str(request_file),preflight=str(preflight_file)),
        phases=['actual-host-preflight', 'cold-admission', 'initial-full-live-guard',
                *(shape+'-'+stage for shape in shapes for stage in ('generation','Run')),
                *([] if large else ['failure']),'owned-cleanup', 'independent-after-exit'],
        actions_enabled=False, parent_scheduled=False)
    # The owning checker validates this generated request when it is frozen;
    # no handwritten command/namespace substitutions are accepted by supervise.
    # Recheck pinned inputs after deriving the closure; a failed check writes nothing.
    for name, item in pins.items():
        require(stamp(path(item['path'])) == item['stat'] and
                sha256(item['path']) == item['sha256'], name+' changed during preparation')
    budget.check()
    written = 0
    def emit(file, value):
        nonlocal written
        text = json.dumps(value,sort_keys=True,indent=2)+'\n'
        size = len(text.encode('utf-8'))+(text.count('\n') if os.name == 'nt' else 0)
        require(output_limit is None or written+size <= output_limit, 'preparation output ceiling before write')
        create(file,value)
        written += size
    directory.mkdir(mode=0o700)
    maps_file = directory/'source-maps.json'
    emit(maps_file, packet['source_roles'])
    metadata = {k:limits[k] for k in ('read_bytes','visits')} if large else plan['qualification']['metadata_per_process']
    operator = dict(schema='native-scale-operator-v1' if large else 'native-tiny-operator-v1', disabled_plan=definition['plan'],
        authorization=definition['authorization'], namespace=str(namespace),
        source_maps=dict(path=str(maps_file), sha256=sha256(maps_file)), preflight_limits=limits,
        metadata_grant=(dict(scope='operator metadata only; Large input scans separately forecast',**metadata) if large else
            dict(max_metered_processes=25, **metadata,total_read_bytes=25*metadata['read_bytes'],total_visits=25*metadata['visits'])))
    emit(directory/'operator.json', operator)
    packet['commands']['supervise'].append(sha256(directory/'operator.json'))
    packet['commands']['supervise'].append('--execute')
    packet['commands']['after_exit'].append(sha256(directory/'operator.json'))
    if large:
        from pathlib import PureWindowsPath, PurePosixPath
        descriptor=read_json(plan['windows_lineage']['path'],64*1024**2)
        parent=descriptor['claim_parent']
        require(set(parent)=={'python','python_sha256','runner'} and
            all(PurePosixPath(parent[k]).is_absolute() for k in ('python','runner')),
            'exact pinned Linux parent claim roles required')
        def mounted(value):
            native=PureWindowsPath(value)
            require(native.drive.upper()=='C:' and '..' not in native.parts,'local C transport required')
            return str(PurePosixPath('/mnt/c',*native.parts[1:]))
        packet['commands']['canonical_claims']={shape:[parent['python'],'-B',parent['runner'],'claim-run',
            mounted(plan_file),'--sha256','ACTUAL_FROZEN_PLAN_SHA256',mounted(Path(plan['owned_root'])/(shape+'-Run-proposal.json')),
            '--windows'] for shape in shapes}

    emit(directory/'packet.json', packet)
    return dict(packet=str(directory/'packet.json'), sha256=sha256(directory/'packet.json'),
                actions_enabled=False, parent_scheduled=False)


def preparation_inputs(plan):
    """Full selected byte maps and named small proof closure, never old payloads.

    The common entry point uses these for its metered hashing lower bound.
    Actual Identity/Storage admission still validates every referenced record.
    """
    paths = [str(os.path.join(group['root'], name)) for group in
             [plan['product'], plan['harness'], *plan['dependencies']] for name in group['sha256']]
    paths += [plan[key]['path'] for key in ('python', 'package', 'executable', 'package_receipt', 'build_proof')]
    paths += [item['path'] for item in [*plan['tools'], *plan['peers'].values()]]
    if plan.get('execution_kind') == 'batch':
        from .hosted_qualification import batch_inputs
        paths += [item['path'] for item in batch_inputs(plan['frozen_batch'])]
    proof = read_json(plan['build_proof']['path'], 64*1024**2)
    paths += [item['path'] for item in [proof['source_reconciliation'], *proof['runner_receipts']]]
    def records(value):
        if isinstance(value, dict):
            if {'path', 'sha256'} <= value.keys():
                paths.append(value['path'])
            # expected_sha256 is a stat-only old payload, never a hash input.
            for child in value.values():
                records(child)
        elif isinstance(value, list):
            for child in value:
                records(child)
    if plan['os'] == 'Windows' and 'windows_lineage' in plan:
        item = plan['windows_lineage']
        paths.append(item['path'])
        records(read_json(item['path'],64*1024**2))
    if plan['os'] == 'Linux':
        item = plan['selected639_lineage']
        paths.append(item['path'])
        records(read_json(item['path'], 8*1024**2))
    if 'qualification' in plan:
        q = plan['qualification']
        paths.append(q['scale_plan']['path'])
        for peer in q.get('peers', {}).values():
            paths += [item['path'] for item in peer.values()]
        if 'windows_history' in q:
            item = q['windows_history']
            paths.append(item['path'])
            body=read_json(item['path'],64*1024**2)
            records(body)
        if 'namespace_disk_authority' in q:
            paths += [item['path'] for item in q['namespace_disk_authority'].values()]
        if 'namespace_history' in q:
            item = q['namespace_history']
            paths.append(item['path'])
            records(read_json(item['path'], 4*1024**2))
    return sorted(set(paths))


def selected_identity(plan):
    """Audit the selected harness, then use its definition-only identity module.

    The checker has its own identity; relocating its Identity implementation
    would incorrectly attribute that implementation to the selected producer.
    """
    root, _ = source_map(plan['harness'])
    directory = root / 'scripts/scale_acceptance'
    name = '_acceptance_preflight_' + os.urandom(16).hex()
    package = types.ModuleType(name)
    package.__path__ = [str(directory)]
    package.__package__ = name
    package.__spec__ = ModuleSpec(name, loader=None, is_package=True)
    package.__spec__.submodule_search_locations = package.__path__
    sys.modules[name] = package
    module_name = name + '.native_scale_identity'
    spec = importlib.util.spec_from_file_location(module_name, directory / 'native_scale_identity.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    # Retain the namespace for lazy relative imports until this one-shot child exits.
    spec.loader.exec_module(module)
    return module.Identity


def inspect(plan, budget, *, probe=None):
    """Validate a disabled or scheduled plan without changing either authority."""
    budget.check()
    require(plan['host'] == host(), 'actual native OS/host mismatch')
    validate_preparation(plan)
    if plan['os'] == 'Windows' and 'qualification' not in plan and 'windows_lineage' not in plan:
        return dict(status='blocked', diagnostics=[WINDOWS_BLOCKED],
                    runtime_pending=list(RUNTIME_PENDING), bindings=dict(host=plan['host']))
    if plan['os'] == 'Windows' and 'qualification' in plan and 'windows_history' not in plan['qualification']:
        return dict(status='blocked', diagnostics=['tiny Windows blocked: OS-local retained allocation/carry descriptor missing'],
                    runtime_pending=list(RUNTIME_PENDING), bindings=dict(host=plan['host']))
    if plan['os'] == 'Windows' and 'qualification' in plan and set(plan['qualification'].get('peers', {})) != {'D', 'G'}:
        return dict(status='blocked', diagnostics=['tiny Windows blocked: clean same-size Linux tiny peers required'],
                    runtime_pending=list(RUNTIME_PENDING), bindings=dict(host=plan['host']))
    if plan['os'] == 'Windows' and 'qualification' not in plan:
        require(all(not os.path.lexists(plan[key]) for key in ('owned_root','campaign')), 'fresh Windows scale roots required')
    selected = selected_identity(plan)
    try:
        identity = selected(plan)
    except ValueError as error:
        if str(error) == 'actual Python runtime/dependency coverage missing':
            module = sys.modules[selected.__module__]
            roots, files = module.runtime_requirements()
            required = set(files)
            for root in roots:
                required.update(root / name for name in module.frozen_metadata(root, ['**/*']) if (root / name).is_file())
            covered = {module.path(group['root']) / name for group in plan['dependencies'] for name in group['sha256']}
            missing = sorted(map(str, required - covered))
            raise ValueError(str(error) + '; missing paths (' + str(len(missing)) + '): ' + json.dumps(missing[:20])) from error
        raise
    if probe is not None:
        probe()
    identity.check()
    preparation_storage = None
    if plan['os'] == 'Windows':
        from importlib import import_module
        selected_package = selected.__module__.rsplit('.', 1)[0]
        storage = import_module(selected_package + '.native_scale_monitor').Storage
        tiny = import_module(selected_package + '.native_tiny')
        preparation_storage = {}
        history = identity.lineage
        for pool in ('native', 'source'):
            previous = history.value['prior_storage']['Windows'][pool]
            admitted = storage(history.baselines[pool], previous)
            preparation_storage[pool] = dict(current_origin_bytes=sum(admitted.baseline.values()),
                sampled_highwater_carry_bytes=admitted.carry,
                historical_allocation_bound=None)
        if 'qualification' in plan:
            for shape in ('D', 'G'):tiny.peer_report(plan, shape)
    budget.check()
    return dict(status='passed', diagnostics=[], runtime_pending=list(RUNTIME_PENDING),
                preparation_storage=preparation_storage,
                bindings=dict(host=plan['host'], product=plan['product']['commit'],
                    product_tree=plan['product']['tree'], harness=plan['harness']['commit'],
                    harness_tree=plan['harness']['tree'], python=plan['python'],
                    package=plan['package'], executable=plan['executable'],
                    package_receipt=plan['package_receipt'], build_proof=plan['build_proof'],
                    selected639_lineage=plan['selected639_lineage']))


def import_tiny_peers(previous, plan, budget, *, pins=None):
    """Preserve qualified peer bytes inside a newly reserved Tiny namespace."""
    import hashlib
    from . import native_tiny as tiny, native_scale_identity as identity
    namespace=identity.path(plan['qualification']['namespace'])
    require(plan['os']=='Windows' and previous['os']=='Windows' and
            namespace!=identity.path(previous['qualification']['namespace']) and not os.path.lexists(namespace),
            'fresh Windows peer-import namespace required')
    proof_plan=dict(plan,qualification=dict(plan['qualification'],peers=previous['qualification']['peers']))
    for shape in ('D','G'):
        budget.check();tiny.peer_report(proof_plan,shape)
    pending={};original={}
    for item in tiny.peer_pins(proof_plan):
        budget.check()
        source=identity.path(item['path']);_,before=tiny.pinned_json(item,8*1024**2)
        observed=source.stat()
        require(stat.S_ISREG(observed.st_mode) and observed.st_nlink==1 and
                all(not q.is_symlink() and not getattr(q.lstat(),'st_file_attributes',0)&0x400
                    for q in (source,*source.parents)),
                'peer import alias/reparse denied')
        with source.open('rb') as stream:
            held=os.fstat(stream.fileno())
            require((held.st_dev,held.st_ino,held.st_size,held.st_mtime_ns)==
                    (observed.st_dev,observed.st_ino,observed.st_size,observed.st_mtime_ns) and
                    stat.S_ISREG(held.st_mode) and held.st_mode==observed.st_mode and
                    held.st_nlink==1 and not getattr(held,'st_file_attributes',0)&0x400,
                    'peer import held identity drift')
            raw=stream.read(8*1024**2+1)
        require(len(raw)==observed.st_size<=8*1024**2 and hashlib.sha256(raw).hexdigest()==item['sha256'] and
                identity.stamp(source)==before,'peer import source changed')
        original[source]=before;pending[item['sha256']]=raw
    require(sum(map(len,pending.values()))<=plan['qualification']['new_bytes'], 'peer imports exceed namespace ceiling')
    def imported(peer):
        return {key:dict(item,path=str(namespace/'imports'/(item['sha256']+'.json')))for key,item in peer.items()}
    plan['qualification']['peers']={shape:imported(peer)for shape,peer in previous['qualification']['peers'].items()}
    # The retained namespace subsumes its old phase roots without dropping their charges.
    plan['owned_roots']=identity.windows_root_union([],plan['owned_roots'])
    # Validate both the outer plan and History before creating metadata-only output.
    validate_preparation(plan)
    tiny.History(plan)
    budget.check();namespace.mkdir(mode=0o700);directory=namespace/'imports';directory.mkdir(mode=0o700)
    records=[]
    for digest,raw in pending.items():
        budget.check();target=directory/(digest+'.json')
        with target.open('xb')as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        require(sha256(target)==digest and target.stat().st_nlink==1 and not target.is_symlink(),
                'peer import destination changed')
        records.append(dict(path=str(target),sha256=digest,bytes=len(raw)))
    require(all(identity.stamp(source)==before for source,before in original.items()), 'peer import producer drift')
    if pins is not None:pins.update(original)
    for shape in ('D','G'):tiny.peer_report(plan,shape)
    budget.check()
    return dict(complete=True,copied_bytes=sum(map(len,pending.values())),records=records,
                original_proof_bytes_preserved=True,CSV_inputs_generated=0)


def observe_plan(d, directory, budget):
    """Refresh the existing Windows lineage using current full native observations.

    Retained proof descriptors are data, not executable collectors. This follows
    the already qualified Storage/History transition; no Run or Original lock
    ownership is acquired here.
    """
    import copy
    import hashlib
    import shutil
    import time
    from . import native_scale_identity as identity, native_scale_host, native_tiny as tiny
    from .native_scale_monitor import Storage
    from .native_scale_control import LIMITS
    from ._native_file import _windows_api
    from .guard import load_runner
    need = require
    need(os.name == 'nt', 'current Windows preparation requires native Windows')
    BASE = identity.path(str(directory))
    START = time.monotonic()
    need(not os.path.lexists(BASE), 'fresh observation directory required')
    # The selected controller imports this same closure before runtime freeze.
    native_scale_host.module('native-scale-runner')
    native_scale_host.module('local-ci')
    load_runner()
    _windows_api()
    limits = d['collector_limits']
    source_checks = {}
    output_bytes = 0
    def check():
        budget.check()
        need(time.monotonic()-START < limits['seconds'] and time.time() < d['launch_cutoff_unix'],
             'shared native preparation deadline')
    def write(name, value):
        nonlocal output_bytes
        check()
        raw = (json.dumps(value, indent=2, sort_keys=True)+'\n').encode()
        need(output_bytes+len(raw) <= limits['output_bytes'], 'observation output ceiling')
        with (BASE/name).open('xb') as stream:
            stream.write(raw)
        output_bytes += len(raw)
        return dict(path=str(BASE/name), sha256=hashlib.sha256(raw).hexdigest())
    def pinned(item, maximum=64*1024**2):
        check()
        return tiny.pinned_json(item, maximum)
    def pin(name):
        check()
        current = identity.path(str(name))
        before = identity.stamp(current)
        value = dict(path=str(current), sha256=sha256(current))
        need(identity.stamp(current) == before, 'pinned input drift: '+str(current))
        return value
    previous_plan, _ = pinned(d['previous_plan'], 4*1024**2)
    retained = identity.retained_windows_d(previous_plan,d['retained_windows_d'],source_checks) if 'retained_windows_d' in d else None
    namespace = identity.path(previous_plan['qualification']['namespace'])
    need(d['attempt'] and Path(d['attempt']).name == d['attempt'] and d['attempt'] not in ('.', '..'),
         'one fresh attempt name required')
    fresh_namespace=identity.path(d['namespace']) if retained else namespace
    need(not retained or not os.path.lexists(fresh_namespace), 'retained-D fresh Tiny namespace already exists')
    d = dict(d, diagnostic_directory=str(fresh_namespace/d['attempt']))
    protected = [*(map(identity.path,retained['plan']['owned_roots']) if retained else ()),
                 namespace, *map(identity.path, previous_plan['owned_roots']),
                 *map(identity.path, previous_plan['source_reservation']['roots'])]
    if retained:protected.append(fresh_namespace)
    need(all(BASE != root and BASE not in root.parents and root not in BASE.parents for root in protected),
         'observation output overlaps measured pool')
    d=dict(d,retained_component_points=preparation_components(
        d,lambda item:pinned(item,4*1024**2)[0],resolve_path=identity.path))
    BASE.mkdir(mode=0o700)
    write('observation-started.json', dict(qualification=False, product_runs=0, scale_slots=0,
        previous_plan=d['previous_plan']))
    try:
        previous_plan, source_checks[Path(d['previous_plan']['path'])] = pinned(d['previous_plan'], 4*1024**2)
        maps = dict(product=previous_plan['product'],
            harness=observe_source(d['harness']['root'], d['harness']['commit'], budget))
        previous_reference = previous_plan['qualification']['scale_plan']
        scale, source_checks[Path(previous_reference['path'])] = pinned(previous_reference, 4*1024**2)
        history_pin = previous_plan['qualification']['windows_history']
        previous, source_checks[Path(history_pin['path'])] = pinned(history_pin)
        need(identity.host() == previous_plan['host'] == previous['host'], 'actual host changed')
        need(Path(sys.executable).resolve() == Path(previous_plan['python']['path']) and
             sys.version == previous_plan['python']['version'], 'selected Python changed')
        for role in ('product', 'harness'):
            check()
            identity.source_map(maps[role])
        need(maps['product'] == previous_plan['product'], 'selected product map changed')
        lock = Path(previous_plan['reservation']['lock_path'])
        lock_stamp = identity.stamp(lock)
        need(lock_stamp[:2] == previous_plan['qualification']['original_lock_stat'][:2], 'original host lock replaced')
        free_before = shutil.disk_usage('C:/').free
        need(free_before >= previous_plan['limits']['start_free_bytes'], 'start free floor')
        requirements = identity.runtime_requirements()
        required = set(requirements[1])
        runtime_freezes = {}
        for root in requirements[0]:
            frozen = identity.frozen_metadata(root, ['**/*'])
            runtime_freezes[root] = frozen
            required.update(root/name for name in frozen if (root/name).is_file())
        groups = {}
        images = []
        for path in sorted(required):
            value = pin(path)
            groups.setdefault(path.parent, {})[path.name] = value['sha256']
            if path in requirements[1]:
                images.append(dict(value, stat=identity.stamp(path)))
        dependencies = [dict(root=str(root), inputs=sorted(values), sha256=values) for root, values in groups.items()]
        identity.dependency_metadata(dependencies, requirements)
        for key in ('python', 'executable', 'package', 'package_receipt', 'build_proof'):
            need(pin(previous_plan[key]['path']) == {k: previous_plan[key][k] for k in ('path', 'sha256')},
                 'selected artifact changed '+key)
        tools = selected_tools(previous_plan['tools'],d['tools'],pin)
        def expected(item):
            need(pin(item['path'])['sha256'] == item['sha256'], 'expected external bytes drift')
        identity.build_binding(previous_plan, tiny.read_json(previous_plan['build_proof']['path']), expected)
        latest, source_checks[Path(d['latest_source_history']['path'])] = pinned(d['latest_source_history'],32*1024**2)
        need(latest['schema']=='native-tiny-windows-history-v1' and latest['host']==previous_plan['host'],
             'latest source history host/schema mismatch')
        baselines, prior, retired = {}, {}, {}
        for pool in ('native', 'source'):
            phase_start = time.monotonic()
            old = previous['baselines'][pool]
            names = {item['path'] for item in old['roots']}
            if retained:
                names=set(identity.windows_root_union(names,retained['plan']['owned_roots'] if pool=='native' else
                             retained['plan']['source_reservation']['roots']))
            rows = [dict(path=name,allow_absent=False) for name in sorted(names)]
            need(not any(BASE.is_relative_to(Path(row['path'])) for row in rows), 'collector cannot inventory its own output')
            value = observe_baseline([row['path'] for row in rows], budget)
            baselines[pool] = value
            old_charges = tiny.History._baseline_charges(old)
            current = tiny.History._baseline_charges(value)
            growth = sum(max(0, amount-old_charges.get(key, 0)) for key, amount in current.items())
            carry=tiny.History.transition_carry(previous['prior_storage'][pool],old,value,
                retained=retained,pool=pool,previous_plan=previous_plan,
                latest_source=latest if pool=='source' else None)
            prior[pool] = dict(sum_bytes=value['sum_bytes'], entry_count=len(current),
                              carry_bytes=carry, prior_sampled_aggregate_highwater_bytes=carry)
            retired[pool] = [dict(path=key[0], device=key[1], file_id=key[2], charge_bytes=amount)
                             for key, amount in old_charges.items() if key not in current]
            baseline_seconds = time.monotonic()-phase_start
            write(pool+'-checkpoint.json', dict(complete=True, roots=len(value['roots']), entries=len(value['entries']),
                baseline_seconds=baseline_seconds, storage_admitted_during_baseline=True,
                total_pool_seconds=time.monotonic()-phase_start, carry_bytes=carry,
                retired_identity_count=len(retired[pool]), baseline_frozen=False, qualification=False))
        retained_point, source_checks[Path(d['retained_source_point']['path'])] = pinned(d['retained_source_point'],4*1024**2)
        need(retained_point['complete'] is True and retained_point['full_source_roots'] == len(previous_plan['source_reservation']['roots']),
             'retained complete source floor binding')
        retained_floor = retained_point['source_current_sampled']
        conservative_floor = retained_point['source_conservative_with_fixture_directory_eof']
        old_data = retained_point.get('preparation_data_reservations', [])
        def retained_preparation_pin(item):
            value, source_checks[Path(item['path'])] = pinned(item,4*1024**2)
            return value
        failed_data, _ = retained_preparation_reservations(d['retained_preparations'],retained_preparation_pin,d['source_q_bytes'],
            local_refinement_pins=d.get('preparation_reservation_updates',()),resolve_path=Path)
        historical,_,_ = preparation_reservations([*old_data,*failed_data],[],previous_plan['source_reservation']['roots'])
        updates = preparation_reservation_updates(d,retained_preparation_pin,historical)
        data_reservations, data_reserve, _ = preparation_reservations(
            historical,[*updates,*d['preparation_data_reservations']],previous_plan['source_reservation']['roots'])
        _,old_reserve,_ = preparation_reservations(old_data,[],previous_plan['source_reservation']['roots'])
        new_data_reserve = data_reserve-old_reserve
        old_components = {item['sha256'] for item in retained_point['retained_component_points']}
        need(old_components <= {item['sha256'] for item in d['retained_component_points']},
             'previous component charge provenance missing')
        d['new_component_points'] = [item for item in d['retained_component_points'] if item['sha256'] not in old_components]
        latest_charges = tiny.History._baseline_charges(latest['baselines']['source'])
        actual_charges = tiny.History._baseline_charges(baselines['source'])
        latest_growth = sum(max(0, amount-latest_charges.get(key,0)) for key,amount in actual_charges.items())
        retained_latest_floor = latest['prior_storage']['source']['carry_bytes']+latest_growth
        write('retained-source-carry-comparison.json',dict(latest_history=d['latest_source_history'],
            latest_carry=latest['prior_storage']['source']['carry_bytes'], latest_to_current_growth=latest_growth,
            retained_latest_floor=retained_latest_floor, actual_transition_carry=prior['source']['carry_bytes'],
            full49_point_floor=retained_floor, physical_peak=None))
        need(prior['source']['carry_bytes'] >= retained_latest_floor,'latest retained source carry would be refunded')
        census_pin = write('baselines.json', dict(baselines=baselines, prior_storage=prior,
            retired_identities=retired, previous_history=history_pin, historical_allocation_bound=None))
        binding_pin = write('bindings.json', dict(host=identity.host(), python=previous_plan['python'],
            product=maps['product'], harness=maps['harness'], tools=tools, dependencies=dependencies, mapped_images=images,
            original_lock_stat=lock_stamp, environment_sha256=identity.environment_digest(),
            retained_source_roots=len(baselines['source']['roots']), qualified_harness=maps['harness']['commit'],
            qualification=False, preparation_data_reservations=data_reservations,
            preparation_data_metric='unobserved DATA write envelopes; physical peak UNKNOWN',
            actual_tool_versions=dict(python=sys.version,git=identity.git(Path(d['harness']['root']),'--version'))))
        namespace = Path(previous_plan['qualification']['namespace'])
        need(not Path(d['diagnostic_directory']).exists(), 'fresh full tiny leaf required')
        retained_namespace, source_checks[Path(d['retained_namespace_history']['path'])] = pinned(d['retained_namespace_history'],4*1024**2)
        need(retained_namespace['namespace'] == str(namespace),'retained namespace owner mismatch')
        children = sorted(Path(row['path']) for row in retained_namespace['baseline']['roots'])
        current_children = sorted(namespace.iterdir())
        failed_plans, failed_paths, unstarted = [], [], set()
        unstarted_provenance = []
        for failed in d['retained_failed_namespaces']:
            failed_audit, source_checks[Path(failed['admin_audit']['path'])] = pinned(failed['admin_audit'],1024**2)
            if failed.get('cleanup_kind') not in ('no-start-admin','preflight-no-controller'):
                failed_result, source_checks[Path(failed['session_result']['path'])] = pinned(failed['session_result'],1024**2)
            failed_plan, source_checks[Path(failed['plan']['path'])] = pinned(failed['plan'],4*1024**2)
            need(Path(failed_plan['qualification']['namespace']) == namespace and
                 Path(failed_plan['owned_root']) == Path(failed['path'])/'data' and
                 Path(failed_plan['campaign']) == Path(failed['path'])/'campaign','retained failed plan scope')
            if failed.get('cleanup_kind') == 'preflight-no-controller':
                operator_failure, source_checks[Path(failed['operator_failure']['path'])] = pinned(failed['operator_failure'],1024**2)
                closure = preflight_no_controller(failed,failed_plan,operator_failure,failed_audit)
                for item in closure:
                    _, source_checks[Path(item['path'])] = pinned(item,16*1024**2)
                unstarted_provenance += closure
                for key in ('owned_root','campaign'):
                    unstarted.add(str(Path(failed_plan[key])))
            elif failed.get('cleanup_kind') == 'no-start-admin':
                probe = failed_audit['original_inode_noncreating_byte0_probe']
                need(failed_audit['complete'] is True and failed_audit['ADMINRECOVERY'] is True and
                     failed_audit['qualification'] is False and failed_audit['errors'] == [] and
                     all(probe[key] is True for key in ('available','unlocked','observer_descriptor_closed')) and
                     probe['stat'] == failed_plan['qualification']['original_lock_stat'],
                     'failed no-start independent retirement proof required')
                for key in ('owned_root','campaign'):
                    name = Path(failed_plan[key])
                    need(not os.path.lexists(name), 'retired unstarted root appeared')
                    unstarted.add(str(name))
            elif failed.get('cleanup_kind') == 'normal-full-tiny-after-exit':
                qpin=failed['qualification_result']
                failed_qualification, source_checks[Path(qpin['path'])] = pinned(qpin,1024**2)
                need(failed_audit['schema'] == 'native178-full-tiny-after-exit-v1' and
                     failed_audit['qualification_passed'] is False and failed_audit['administrative_recovery'] is False and
                     failed_audit['independent_probe_released'] is True and failed_audit['original_byte_zero_available'] is True and
                     failed_audit['qualification_sha256'] == qpin['sha256'] and failed_qualification['passed'] is False and
                     failed_result['passed'] is False, 'failed sibling normal cleanup proof required')
            else:
                need(failed_audit['complete'] is True and failed_audit['ADMINRECOVERY'] is True and
                     failed_audit['qualification'] is False and failed_result['passed'] is False,
                     'failed sibling terminal recovery proof required')
            failed_plans.append(failed_plan)
            failed_paths.append(Path(failed['path']))
        completed=d.get('retained_completed_namespaces',[])
        completed_paths=[Path(item['path']) for item in completed]
        need(set(current_children) == {*children,*failed_paths,*completed_paths} and
             all(p.is_dir() and not p.is_symlink() for p in current_children),
             'only exact retained baseline plus failed siblings permitted')
        namespace_baseline = observe_baseline([*children,*completed_paths], budget)
        point, source_checks[Path(d['namespace_point']['path'])] = pinned(d['namespace_point'],4*1024**2)
        if completed:
            point=tiny.namespace_advancement(namespace,namespace_baseline,d['namespace_point'],
                d['retained_namespace_history'],completed,lock_stamp,expected_host=previous_plan['host'],pins=source_checks)
            point_pin=write('completed-namespace-point.json',point)
        else:point_pin=d['namespace_point']
        summary = point['unchanged_current_identities']['tiny']
        fields = {item['path']:item['stat'] for item in namespace_baseline['entries']}
        expected_summary = dict(files=len(fields),successful_charge_sum=namespace_baseline['sum_bytes'],
            digest=hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest())
        origin = point['tiny_origin_carry']
        write('namespace-point-comparison.json', dict(expected=expected_summary, actual=summary,
            origin_carry_bytes=origin, expected_sampled_bytes=origin+namespace_baseline['sum_bytes'],
            baseline=namespace_baseline, validation='owning History below; no workload admission yet'))
        namespace_pin = write('namespace-history.json',dict(schema='native-tiny-namespace-history-v1',
            namespace=str(namespace),observation=point_pin,origin_carry_bytes=origin,
            **(dict(completed_namespaces=completed,previous_observation=d['namespace_point'],
                previous_history=d['retained_namespace_history']) if completed else {}),
            baseline=namespace_baseline,prior_storage=dict(sum_bytes=namespace_baseline['sum_bytes'],
                entry_count=len(fields),carry_bytes=origin+namespace_baseline['sum_bytes'],
                prior_sampled_aggregate_highwater_bytes=origin+namespace_baseline['sum_bytes'])))
        current_scale = copy.deepcopy(scale)
        current_scale['limits'] = LIMITS
        current_scale['dependencies'] = dependencies
        current_scale['tools'] = tools
        current_scale['environment_sha256'] = identity.environment_digest()
        if retained:
            current_scale['owned_roots']=identity.windows_root_union(current_scale['owned_roots'],retained['plan']['owned_roots'])
            current_scale['source_reservation']=dict(current_scale['source_reservation'],roots=
                identity.windows_root_union(current_scale['source_reservation']['roots'],retained['plan']['source_reservation']['roots']))
        scale_pin = write('scale-reference.DISABLED.json', current_scale)
        history = copy.deepcopy(previous)
        history.update(scale_plan=scale_pin, baselines=baselines, prior_storage=prior,
            provenance=[*history['provenance'], census_pin, binding_pin],
            latest_source_history=d['latest_source_history'],
            retained_transition=dict(schema='native-tiny-retained-transition-v1',
                previous_plan=d['previous_plan'], previous_preflight=d['previous_preflight']))
        if retained:
            history['retained_windows_d']=d['retained_windows_d']
            history['provenance'] += [item for key,item in d['retained_windows_d'].items() if key!='capacity_log']
            history['prior_generation_ms']=max(history['prior_generation_ms'],
                int((time.time()-retained['started']['started'])*1000)+retained['started']['prior_generation_ms'])
        history['provenance'] += [pin for record in d['retained_preparations'] for key,pin in record.items() if key!='metadata_output']
        history['provenance'] += [value for record in d['retained_preparations']
            for key,value in record.get('metadata_output',{}).items() if key not in ('root','reserved_bytes')]
        history['provenance'] += d.get('preparation_reservation_updates',[])
        history['provenance'] += unstarted_provenance
        history['provenance'] += [failed[key] for failed in d['retained_failed_namespaces']
            if failed.get('cleanup_kind') == 'preflight-no-controller'
            for key in ('plan','admin_audit','operator_failure','preflight')]
        history['provenance'] += [item for item in d['retained_component_points'] if item not in history['provenance']]
        if retained:history['provenance'].append(namespace_pin)
        history['provenance'] += [d['latest_source_history'], d['retained_source_point'], d['authorization'],d['continuation']]
        foreign_bound = None
        if d['foreign_host_bound'] is not None:
            foreign, source_checks[Path(d['foreign_host_bound']['path'])] = pinned(d['foreign_host_bound'],1024**2)
            fit = foreign['source_fit']
            need(fit['q'] == d['source_q_bytes'] and
                 all(type(fit[key]) is int and fit[key] >= 0 for key in ('current','remaining_write_reservation')),
                 'opaque foreign-host source point/envelope required')
            foreign_bound = dict(record=d['foreign_host_bound'], measured_source_point_bytes=fit['current'],
                retained_write_envelope_bytes=fit['remaining_write_reservation'],
                metric='opaque other-host source point plus unspent/unknown write envelope; no physical high water',
                physical_peak=None)
            history['provenance'].append(d['foreign_host_bound'])
        history_pin = write('windows-history.CANDIDATE.json', history)
        plan = copy.deepcopy(previous_plan)
        plan.update(actions_enabled=False, parent_scheduled=False, dependencies=dependencies, limits=LIMITS,
                    harness=maps['harness'], tools=tools, environment_sha256=identity.environment_digest())
        plan['owned_root'] = str(Path(d['diagnostic_directory'])/'data')
        plan['campaign'] = str(Path(d['diagnostic_directory'])/'campaign')
        candidates = list(dict.fromkeys([*plan['owned_roots'],
            *(root for prior_plan in failed_plans for root in prior_plan['owned_roots'])]))
        need(all(os.path.lexists(root) or root in unstarted for root in candidates),
             'retained owned root disappeared without positive no-start retirement')
        if retained:candidates=list(dict.fromkeys([*candidates,*retained['plan']['owned_roots']]))
        plan['owned_roots'] = [root for root in candidates if root not in unstarted]+[plan['owned_root'],plan['campaign']]
        plan['source_reservation']=dict(current_scale['source_reservation'])
        plan['qualification'].update(scale_plan=scale_pin, windows_history=history_pin, namespace_history=namespace_pin,
            original_lock_stat=lock_stamp, launch_cutoff_unix=d['launch_cutoff_unix'], stop_unix=d['stop_unix'])
        if retained:
            plan['qualification']['namespace']=str(fresh_namespace)
            plan['qualification'].pop('namespace_history',None)
        if 'namespace_disk_authority' in d:
            authority=d['namespace_disk_authority']
            selection,_=pinned(authority['selection'],65536)
            plan['qualification'].update(new_bytes=selection['namespace_disk_bytes'],namespace_disk_authority=authority)
        if retained:
            write('peer-imports.json',import_tiny_peers(previous_plan,plan,budget,pins=source_checks))
        else:
            tiny.History(plan)
        for shape in ('D', 'G'):
            tiny.peer_report(plan, shape)
        plan_pin = write('tiny-plan.DISABLED.json', plan)
        need(identity.runtime_requirements() == requirements and
             all(identity.stamp(Path(item['path'])) == item['stat'] for item in images), 'runtime mapped image drift')
        need(all(identity.frozen_metadata(root, ['**/*']) == value for root, value in runtime_freezes.items()), 'runtime namespace drift')
        need(all(identity.stamp(path) == value for path, value in source_checks.items()), 'original proof/source drift')
        need(identity.stamp(lock) == lock_stamp, 'original lock drift')
        free_after = shutil.disk_usage('C:/').free
        need(free_after >= previous_plan['limits']['stop_free_bytes'], 'stop free floor')
        check()
        source_storage = Storage(baselines['source'], prior['source'])
        source_current = source_storage.sample([Path(p) for p in plan['source_reservation']['roots']])
        source_admission_floor = max(source_current,retained_floor)
        fixture_pin = d['retained_source_fixture_growth']['point']
        fixture, source_checks[Path(fixture_pin['path'])] = pinned(fixture_pin,4*1024**2)
        missing_fixture_highwater = sum(max(0,item['charge']-source_storage.high.get(
            (str(Path(item['path'])),item['dev'],item['ino']),0))
            for item in fixture['retired_and_current_file_highwaters'])
        component_directory_extra = 0
        new_component_growth = 0
        new_component_count = 0
        for component_pin in d['retained_component_points']:
            component, source_checks[Path(component_pin['path'])] = pinned(component_pin,65536)
            need(component.get('passed',component.get('cleanup_passed')) is True and component['qualification'] is False, 'retained component scope')
            for item in component['current_fixture_inventory']:
                identity.sealed_stat(item)
                if 'sha256' in item:
                    need(identity.sha256(Path(item['path'])) == item['sha256'], 'retained component body drift')
            component_directory_extra += sum(item['stat']['size'] for item in component['current_fixture_inventory']
                if __import__('stat').S_ISDIR(item['stat']['mode'])) + component['parent_positive_logicalEOF_delta']
            if component_pin in d['new_component_points']:
                new_component_growth += component['source_growth_envelope']
                new_component_count += 1
        need(new_component_count == len(d['new_component_points']) and
             retained_point['source_conservative_with_fixture_directory_eof'] == conservative_floor,
             'previous conservative point/new component binding')
        failed_interval = d['failed_component_interval']
        failed_audit, source_checks[Path(failed_interval['audit']['path'])] = pinned(failed_interval['audit'],65536)
        need(failed_audit['complete'] is True and failed_audit['ADMINRECOVERY'] is True and
             failed_audit['qualification'] is False, 'failed component recovery required')
        failed_root=Path(failed_interval['root'])
        failed_current_regular=sum(amount for key,amount in source_storage.high.items()
            if Path(key[0]).is_relative_to(failed_root))
        # The retained interval reservation includes current files; never add them twice.
        failed_interval_extra=max(0,failed_interval['conservative_reservation_bytes']-failed_current_regular)
        additional_failed_extra = 0
        additional_failed_reservation = 0
        old_intervals = {str(Path(item['root'])):item['conservative_reservation_bytes']
            for item in retained_point['additional_failed_component_intervals']}
        current_intervals = {str(Path(item['root'])):item['conservative_reservation_bytes']
            for item in d['additional_failed_component_intervals']}
        need(old_intervals.keys() <= current_intervals.keys() and
             all(current_intervals[root]>=amount for root,amount in old_intervals.items()),
             'retained failed interval reservation cannot be dropped/refunded')
        for interval in d['additional_failed_component_intervals']:
            proof, source_checks[Path(interval['audit']['path'])] = pinned(interval['audit'],65536)
            need(proof['complete'] is True and proof['ADMINRECOVERY'] is True and
                 proof['qualification'] is False, 'additional failed component recovery required')
            current = sum(amount for key,amount in source_storage.high.items()
                if Path(key[0]).is_relative_to(Path(interval['root'])))
            additional_failed_extra += max(0,interval['conservative_reservation_bytes']-current)
            additional_failed_reservation += max(0,interval['conservative_reservation_bytes']-
                old_intervals.get(str(Path(interval['root'])),0))
        source_conservative = source_admission_bound(source_current + missing_fixture_highwater + fixture['fixture_directory_logical_eof'] + fixture['directory_parent']['positive_logical_eof_delta'] + component_directory_extra + failed_interval_extra + additional_failed_extra, conservative_floor, new_component_growth + additional_failed_reservation, data_reserve, new_data_reserve)
        foreign_upper = (foreign_bound['measured_source_point_bytes']+foreign_bound['retained_write_envelope_bytes']
                         if foreign_bound is not None else 0)
        need(source_conservative + foreign_upper <= d['source_q_bytes'],
             'whole source family/headroom; foreign point counted once without old local host')
        check()
        write('observation-result.json', dict(complete=True, qualification=False, product_runs=0, scale_slots=0,
            seconds=time.monotonic()-START, read_bytes=budget.read_bytes, visits=budget.visits,
            output_bytes_before_result=output_bytes, plan=plan_pin, baselines=census_pin, bindings=binding_pin,
            capacity=dict(volume='C:',free_before_bytes=free_before,free_after_bytes=free_after,
                start_floor_bytes=previous_plan['limits']['start_free_bytes'],
                stop_floor_bytes=previous_plan['limits']['stop_free_bytes'],physical_peak=None),
            previous_plan=d['previous_plan'], previous_preflight=d['previous_preflight'], source_reservation_unchanged=True,
            constructor_qualified=False, baseline_roots_unchanged=True, retired_identities=retired,
            namespace_history=namespace_pin, retained_failed_namespaces=d['retained_failed_namespaces'],
            retained_source_fixture_growth=d['retained_source_fixture_growth'],
            full_source_roots=len(plan['source_reservation']['roots']),source_current_sampled=source_current,
            source_admission_floor=source_admission_floor, retained_full49_point_floor=retained_floor,
            source_conservative_with_fixture_directory_eof=source_conservative,
            preparation_data_reservations=data_reservations,
            preparation_data_metric='unobserved DATA write envelopes; physical peak UNKNOWN',
            foreign_host_bound=foreign_bound, combined_source_admission_bound=source_conservative+foreign_upper,
            missing_retained_fixture_file_highwater=missing_fixture_highwater,
            retained_component_points=d['retained_component_points'], component_directory_extra=component_directory_extra,
            new_component_current_growth_envelope=new_component_growth,
            failed_component_interval=failed_interval, failed_component_current_regular=failed_current_regular,
            failed_component_interval_extra=failed_interval_extra,
            additional_failed_component_intervals=d['additional_failed_component_intervals'],
            additional_failed_component_interval_extra=additional_failed_extra,
            historical_allocation_bound=None))
        return plan_pin
    except BaseException as error:
        try:
            # A spent read/deadline allowance must not erase the primary failure.
            raw = (json.dumps(dict(complete=False, qualification=False, error=repr(error),
                seconds=time.monotonic()-START, read_bytes=budget.read_bytes, visits=budget.visits))+'\n').encode()
            if output_bytes+len(raw) <= limits['output_bytes']:
                with (BASE/'observation-failed.json').open('xb') as stream:
                    stream.write(raw)
        except BaseException:
            pass
        raise
