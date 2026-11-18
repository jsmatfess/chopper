#!/usr/bin/env python3
"""Explicitly approved, native Windows SMALL supervisor. Never a CI entry point."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit

sys.dont_write_bytecode = True  # do not mutate the frozen scripts inventory

HERE = Path(__file__).resolve().parent
PRODUCT = '639d1fe97d985b1544df0932321c6a93cca2567b'
PRODUCT_TREE = 'b3bde79d552ee29760cb283d07938f9248cee0bb'
HARNESS = 'b68c2cfba4bd9c49c94e007080f80522b5f9f293'
PACKAGE_RECEIPT_SHA256 = '1720f28a01cbbd7a30cbb8c8614b9efc2da01e57c765c625f51e8a5e3455c30d'
GIB = 1024**3
LIMITS = dict(batch_seconds=7200, owned_bytes=64*GIB, stop_owned_bytes=56*GIB, start_free_bytes=192*GIB,
              stop_free_bytes=128*GIB, start_quota_bytes=4*GIB, stop_quota_bytes=2*GIB,
              sample_ms=1000, stale_ms=5000, disk_stale_ms=90000)
VARIANTS = {'test-browser.mjs': [[], ['--resource-contracts'], ['--resource-contracts', '--shuffle-partition']],
            'test-browser-graph.mjs': [[]], 'test-browser-graph-lifecycle.mjs': [[], ['--composed']],
            'test-browser-graph-inspection.mjs': [[]], 'test-browser-graph-bounds.mjs': [[]],
            'test-browser-bridge.mjs': [[]], 'test-browser-cleanup.mjs': [[]],
            'test-browser-termination.mjs': [[], ['--persistent'], ['--persistent', '--process-kill'],
                ['--persistent', '--process-kill', '--direct'], ['--persistent', '--process-kill', '--composed']]}


ORIGIN_PORTS = {'test-browser.mjs': 8422, 'test-browser-graph.mjs': 8423,
    'test-browser-graph-lifecycle.mjs': 8425, 'test-browser-graph-inspection.mjs': 8427,
    'test-browser-graph-bounds.mjs': 8431, 'test-browser-cleanup.mjs': 8423,
    'test-browser-termination.mjs': 8424}

def command_specs(*, first_only=False):
    commands=[dict(script=name,flags=list(flags),timeout_seconds=450,
                   origin='http://127.0.0.1:'+str(ORIGIN_PORTS.get(name,18100+index)))
              for index,(name,flags) in enumerate((n,f) for n,variants in VARIANTS.items() for f in variants)]
    return commands[:1] if first_only else commands


OPERATIONS = []


def operation(action):
    # A timed-out sampler still owns its input thread until both actually exit.
    OPERATIONS[:] = [thread for thread in OPERATIONS if thread.is_alive()]
    thread = threading.Thread(target=action, daemon=True)
    OPERATIONS.append(thread)
    thread.start()
    return thread


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), HERE / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runner = module('validation-runner')
windows = module('browser-small-windows')


def need(condition, message):
    if not condition:
        raise OSError(message)


def now_ms():
    return int(time.time()*1000)


def canonical(path):
    value = Path(path)
    need(value.is_absolute() and value.resolve() == value, 'Canonical absolute path required: ' + str(path))
    for part in [value, *value.parents]:
        need(not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(), 'Symlink/junction rejected: ' + str(part))
    return value


def stamp_lock(path):
    stat = Path(path).stat()
    return [stat.st_dev, stat.st_ino]


def stamp(path):
    stat = canonical(path).stat()
    need(Path(path).is_file(), 'Regular file required')
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def freeze(path):
    before = stamp(path)
    digest = runner.digest(Path(path))
    need(stamp(path) == before, 'Input changed while hashing')
    return dict(path=str(path), sha256=digest, stat=before)


def no_nulls(value):
    need(value is not None, 'Null configuration denied')
    if isinstance(value, dict):
        for child in value.values():
            no_nulls(child)
    if isinstance(value, list):
        for child in value:
            no_nulls(child)


def inventory(directory):
    root = canonical(directory)
    need(root.is_dir(), 'Inventory root missing')
    paths = []
    for folder, dirs, files in os.walk(root, onerror=lambda error: (_ for _ in ()).throw(error)):
        for name in dirs + files:
            canonical(Path(folder) / name)
        paths.extend(str(Path(folder) / name) for name in files)
    return sorted(paths)


def retained_origin(config, *, with_priming=False):
    """An explicit additional original-metric debit, plus a new sampled origin."""
    path = config['retained_origin_manifest']
    need(type(path) is str, 'Retained origin manifest path type')
    path = canonical(path)
    declared = [e for e in config['inputs'] if e['path'] == str(path)]
    need(len(declared) == 1, 'Undeclared retained origin manifest')
    before = InputMetadata().file(path)
    need(before[2] < 1024**2, 'Retained origin manifest oversized')
    with path.open('rb') as stream:
        raw = stream.read(1024**2)
    need(len(raw) < 1024**2, 'Retained origin manifest oversized')
    need(InputMetadata().file(path) == before, 'Retained origin manifest changed while reading')
    need(hashlib.sha256(raw).hexdigest() == declared[0]['sha256'], 'Retained origin manifest hash mismatch')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'Retained origin duplicate key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError(value)
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, UnicodeError) as error:
        raise OSError('Retained origin malformed JSON') from error
    required = {'schema', 'additional_retained_bytes', 'adopted_roots'}
    need(type(value) is dict and required <= set(value) <= required | {'metadata'}, 'Retained origin schema')
    need(value['schema'] == 'chopper-small-retained-origin-v1', 'Retained origin schema')
    debit, roots = value['additional_retained_bytes'], value['adopted_roots']
    need(type(debit) is int and 0 <= debit <= 2**64-1, 'Retained origin debit must be uint64')
    need(type(roots) is list and all(type(root) is str for root in roots), 'Retained origin root types')
    need('metadata' not in value or type(value['metadata']) is dict, 'Retained origin metadata type')
    paths = []
    others = [canonical(root) for root in [config['owned_root'], *config['history_roots']]]
    for root in roots:
        path = canonical(root)
        need(str(path) == root and stat.S_ISDIR(InputMetadata().read(path).st_mode), 'Retained origin root missing/noncanonical')
        need(str(path.anchor) in config['volumes'], 'Uninventoried retained origin volume')
        need(all(not path.is_relative_to(other) and not other.is_relative_to(path)
                 for other in others + paths), 'Overlapping retained origin roots')
        paths.append(path)
    priming = value.get('metadata', {}).get('storage_priming')
    if priming is not None:
        need(type(priming) is dict and set(priming) == {'covered_roots', 'fresh_roots', 'ledger'}, 'Storage priming schema')
        need(debit == 0 and config['history_roots'] == [], 'Primed aggregate cannot stack other debits/ledgers')
        covered, fresh = priming['covered_roots'], priming['fresh_roots']
        need(all(type(group) is list and group and all(type(p) is str for p in group)
                 for group in (covered, fresh)), 'Storage priming root types')
        declared_roots = {str(p) for p in [*paths, canonical(config['owned_root'])]}
        need(len(set(covered + fresh)) == len(covered + fresh)
             and set(covered + fresh) == declared_roots, 'Storage priming must partition complete declared roots')
        need(config['owned_root'] in fresh and all(any(canonical(p).is_relative_to(canonical(r)) for r in fresh)
             for p in (config['root'], config['retained_origin_manifest'])), 'Fresh source/metadata/runtime roots required')
        ledger = priming['ledger']
        need(type(ledger) is dict and set(ledger) == {'path', 'sha256', 'cumulative_owned_bytes'}
             and type(ledger['cumulative_owned_bytes']) is int and ledger['cumulative_owned_bytes'] >= 0,
             'Storage priming ledger binding')
        need(any(canonical(ledger['path']).is_relative_to(canonical(r)) for r in covered)
             and [e for e in config['inputs'] if e['path'] == ledger['path']]
                 == [dict(path=ledger['path'], sha256=ledger['sha256'])], 'Covered aggregate ledger must be declared/pinned')
        before = InputMetadata().file(ledger['path'])
        need(before[2] <= 1024**2, 'Storage priming ledger oversized')
        with Path(ledger['path']).open('rb') as stream:
            raw = stream.read(1024**2 + 1)
        need(len(raw) == before[2] and InputMetadata().file(ledger['path']) == before
             and hashlib.sha256(raw).hexdigest() == ledger['sha256'], 'Storage priming ledger drift')
        prior = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
        need(type(prior['cumulative_owned_bytes']) is int
             and prior['cumulative_owned_bytes'] == ledger['cumulative_owned_bytes'],
             'Storage priming aggregate mismatch')
        history = value.get('metadata', {}).get('history')
        if history is not None:
            from scale_acceptance.hosted_qualification import retained_storage_ledger
            need(history['ledger']['path'] == ledger['path'] and history['ledger']['sha256'] == ledger['sha256'],
                 'Storage priming history binding mismatch')
            inherited, inherited_roots = retained_storage_ledger(history, declared=config['inputs'])
            need(inherited == prior and inherited_roots == covered, 'Storage priming history aggregate/root mismatch')
        else:
            need(prior.get('method') == 'sum of per-file identity high-water bytes; deleted identities retained; unknown deletion races deny',
                 'Storage priming aggregate/method mismatch')
    return (debit, paths, priming) if with_priming else (debit, paths)


def preparation_state(config):
    """Cold-only tool body/membership proof; never add it to a live hot census."""
    selected=config.get('preparation')
    if selected is None:return dict(git='git',frozen=[],inventories={})
    declared={row['path']:row['sha256'] for row in selected['inputs']}
    need(len(declared)==len(selected['inputs']) and declared,'Unique preparation input pins required')
    need(isinstance(selected['input_directories'],dict),'Exact preparation membership maps required')
    inventories={name:inventory(canonical(name)) for name in selected['input_directories']}
    need(inventories==selected['input_directories'],'Preparation directory membership drift')
    need(all(name in declared for members in inventories.values() for name in members),
         'Preparation tool inventory not fully declared')
    for role,tool in selected['tools'].items():
        need(declared.get(str(canonical(tool['path'])))==tool['sha256'],'Preparation tool binding mismatch: '+role)
    git=str(canonical(selected['tools']['git']['path']))
    frozen=[freeze(canonical(name)) for name in declared]
    need(all(row['sha256']==declared[row['path']] for row in frozen),'Preparation tool body drift')
    return dict(git=git,frozen=frozen,inventories=inventories)


def validate_config(config, *, producer_root=None):
    """Read-only preparation checks, without starting the acceptance clock."""
    no_nulls(config)
    need(config['schema'] == 'chopper-small-runner-config-v1', 'Config schema')
    root, owned = canonical(config['root']), canonical(config['owned_root'])
    need(root == (canonical(producer_root) if producer_root is not None else HERE.parent),
         'Run producer from the selected test checkout')
    need(not owned.exists(), 'Fresh owned root required; no resume')
    need(root.anchor == owned.anchor, 'Runner batch/packet storage must share the test checkout drive')
    need(not root.is_relative_to(owned) and not owned.is_relative_to(root / 'ui'), 'Owned/source overlap')
    need(config['channel'] in ('chrome', 'msedge'), 'Installed channel required')
    need(config['limits'] == LIMITS, 'Exact SMALL limits required')
    if 'overall_deadline_ms' in config:
        need(type(config['overall_deadline_ms']) is int and 0 < config['overall_deadline_ms'] < 2**53
             and now_ms() < config['overall_deadline_ms']-120000, 'Overall execution/cleanup deadline expired or invalid')
    need(config['source_commit'] == PRODUCT, 'Frozen product source reference required')
    harness = config['harness_commit']
    need(isinstance(harness, str) and len(harness) == 40 and all(c in '0123456789abcdef' for c in harness),
         'Exact selected harness commit required')
    cold=preparation_state(config)
    # Labels alone never establish source: compare each declared source file to
    # the actual Git blob at the separate product/harness revision.
    for group, commit in [('product_source', PRODUCT), ('harness_source', harness)]:
        need(config[group], 'Source mapping required')
        for entry in config[group]:
            path = canonical(entry['path'])
            content = subprocess.check_output([cold['git'], '-c', 'core.fsmonitor=false', '-C', str(root), 'show', commit + ':' + entry['git_path']], timeout=4)
            need(hashlib.sha256(content).hexdigest() == runner.digest(path), 'Source blob mismatch: ' + str(path))
    source_paths = subprocess.check_output([cold['git'], '-c', 'core.fsmonitor=false', '-C', str(root), 'ls-tree', '-r', '--name-only', PRODUCT, '--',
        'crates', 'vendor', '.cargo', 'Cargo.toml', 'Cargo.lock', 'ui/src', 'ui/public', 'ui/index.html',
        'ui/style.css', 'ui/package.json', 'ui/package-lock.json', 'scripts/build-browser.mjs'], text=True, timeout=4).splitlines()
    need(source_paths and set(source_paths) <= {entry['git_path'] for entry in config['product_source']},
         'Incomplete actual frozen product source manifest')
    need(len(config['product_assets']) == 7 and len(config['package_zips']) == 3, 'Seven frozen assets and three ZIPs required')
    receipt_path = canonical(config['package_receipt'])
    need(runner.digest(receipt_path) == PACKAGE_RECEIPT_SHA256, 'Frozen package receipt mismatch')
    receipt = json.loads(receipt_path.read_text())
    need(config['source_tree'] == PRODUCT_TREE == receipt['release_source_tree'], 'Product tree mismatch')
    for paths, expected in [(config['product_assets'], receipt['hosted']), (config['package_zips'], receipt['packages'])]:
        need({Path(p).name for p in paths} == set(expected), 'Frozen inventory mismatch')
        for path in paths:
            need(runner.digest(canonical(path)) == expected[Path(path).name]['sha256'], 'Frozen artifact drift: ' + path)
    for path in config['product_assets']:
        served = root / 'ui/dist' / Path(path).name
        need(runner.digest(served) == receipt['hosted'][Path(path).name]['sha256'], 'Served product differs from frozen package')
    # Every input is a concrete file/hash, never a supplied commit-label proof.
    entries = config['inputs']
    need(entries and len({e['path'] for e in entries}) == len(entries), 'Unique explicit input manifest required')
    declared = {e['path']: e['sha256'] for e in entries}
    graph_selected = any(command['script'] == 'test-browser-graph.mjs' for command in config['commands'])
    if graph_selected:
        need(bool(config.get('zstd_dll')), 'Explicit Graph zstd_dll required')
    required = config['product_assets'] + config['package_zips'] + [config['node'], config['python'], config['browser'], config['package_receipt']]
    required += [str(root / name) for name in ('ui/package.json', 'ui/package-lock.json')]
    required += [e['path'] for key in ('product_source', 'harness_source') for e in config[key]]
    required += [str(root / 'scripts' / name) for name in ('browser-small-runner.py', 'browser-small-windows.py', 'browser-small-bootstrap.mjs',
                 'browser-small-contract.mjs', 'browser-small-observer.mjs', 'browser-launch.mjs', 'browser-artifacts.mjs',
                 'browser-acceptance.mjs', 'serve-hosted.mjs', 'validation-runner.py', 'local-ci.py')]
    if 'retained_origin_manifest' in config:
        retained_origin(config)
        required.append(config['retained_origin_manifest'])
    if graph_selected:
        required.append(config['zstd_dll'])
    directories = config['input_directories']
    need(all(str(root / name) in directories for name in ('ui/dist', 'ui/src', 'ui/node_modules', 'scripts')), 'Complete served/source/scripts/dependency inventory required')
    inventories = {directory: inventory(directory) for directory in directories}
    required += [p for paths in inventories.values() for p in paths]
    # The live UI builds/serves PRODUCT, even when HARNESS has newer UI files.
    product_map = {(e['path'], e['git_path']) for e in config['product_source']}
    product_ui = {name for name in source_paths if name.startswith('ui/src/')}
    need(set(inventory(root / 'ui/src')) == {str(root / name) for name in product_ui}
         and all((str(root / name), name) in product_map for name in product_ui),
         'Missing actual frozen product UI source proof')
    harness_map = {(e['path'], e['git_path']) for e in config['harness_source']}
    need(not any(e['git_path'].startswith('ui/src/') for e in config['harness_source']),
         'Production UI belongs to PRODUCT, not HARNESS')
    required_harness = ['scripts/' + name for name in (
        'browser-small-contract.mjs', 'browser-small-observer.mjs', 'browser-launch.mjs',
        'browser-acceptance.mjs', 'browser-artifacts.mjs', 'browser-graph-codec.mjs', 'serve-hosted.mjs')]
    required_harness += ['scripts/' + command['script'] for command in config['commands']]
    if graph_selected:
        required_harness.append('scripts/graph-codec-fixtures.py')
    if any('--resource-contracts' in command['flags'] for command in config['commands']):
        required_harness += ['scripts/build-browser-tests.mjs',
                             'ui/tests/resource-contract-tests.ts', 'ui/tests/resource-contract-worker.ts']
    need(all((str(root / name), name) in harness_map for name in required_harness),
         'Missing actual selected harness source proof')
    required += [str(canonical(path) / 'storage-ledger.json') for path in config['history_roots']]
    for path in required:
        need(path in declared, 'Undeclared required input: ' + path)
    frozen = [freeze(canonical(e['path'])) for e in entries]
    need(all(e['sha256'] == declared[e['path']] for e in frozen), 'Input hash mismatch')
    volumes = config['volumes']
    need(volumes and len(set(volumes)) == len(volumes), 'Explicit unique physical volume inventory')
    for volume in volumes:
        need(str(canonical(volume).anchor) == str(canonical(volume)), 'Volume root required')
    for path in [root, owned, *config['history_roots'], *declared]:
        need(str(canonical(path).anchor) in volumes, 'Uninventoried volume: ' + str(path))
    history = [str(canonical(path)) for path in config['history_roots']]
    need(len(set(history)) == len(history), 'Duplicate history root')
    for a in [owned, *map(Path, history)]:
        for b in [owned, *map(Path, history)]:
            need(a == b or not a.is_relative_to(b), 'Overlapping owned roots')
        need(not root.is_relative_to(a), 'Source under owned history')
    need(0 < len(config['commands']) <= 16, 'Explicit bounded selection required')
    selected = set()
    for command in config['commands']:
        name, flags = command['script'], command['flags']
        need(flags in VARIANTS.get(name, []), 'Unsupported harness/variant')
        need((name, tuple(flags)) not in selected, 'No repeats/retries')
        selected.add((name, tuple(flags)))
        need(0 < command['timeout_seconds'] <= 900, 'Command deadline exceeds fifteen minutes')
        origin = urlsplit(command['origin'])
        ports = ORIGIN_PORTS
        need(origin.scheme == 'http' and origin.hostname == '127.0.0.1' and origin.port
             and not origin.path and not origin.query and not origin.fragment and not origin.username
             and command['origin'] == 'http://127.0.0.1:' + str(origin.port), 'Exact loopback origin required')
        need(name not in ports or origin.port == ports[name], 'Owning harness origin mismatch')
        harness = str(root / 'scripts' / name)
        need(harness in declared, 'Owning harness not declared')
    check_inputs(cold)
    return dict(frozen=frozen, inventories=inventories)


def execution_deadline_ms(plan):
    """The fixed batch cap and pinned overall stop, with cleanup time reserved."""
    end = plan['batch_started_ms'] + LIMITS['batch_seconds']*1000
    overall = plan['config'].get('overall_deadline_ms')
    return min(end, overall-120000) if overall is not None else end


def check_execution_deadline(plan):
    need(plan['batch_started_ms'] <= now_ms() < execution_deadline_ms(plan), 'Fixed overall/channel deadline')


def prepare(config):
    validated = validate_config(config)
    frozen, inventories = validated['frozen'], validated['inventories']
    root, owned = canonical(config['root']), canonical(config['owned_root'])
    declared = {e['path']: e['sha256'] for e in config['inputs']}
    volumes = config['volumes']
    started, reservation = now_ms(), 'small-' + uuid.uuid4().hex
    packets, steps = [], []
    for index, command in enumerate(config['commands']):
        name, flags = command['script'], command['flags']
        harness = str(root / 'scripts' / name)
        base = owned / f'command-{index+1}'
        packet = dict(schema='chopper-small-contract-observation-v1', approved=True,
            channel=config['channel'], argv=[harness, *flags], features='default-product; separately declared test reactor',
            source_commit=PRODUCT, source_tree=config['source_tree'], package_receipt_sha256=declared[config['package_receipt']],
            executable=config['browser'], executable_sha256=declared[config['browser']], browser_version=config['browser_version'],
            origin=command['origin'], guard=str(owned / 'guard.json'), runner_lock=str(owned / 'batch/runner.lock'),
            receipt=str(base.with_suffix('.jsonl')), reservation=reservation, batch_started_ms=started,
            volumes=volumes, limits=LIMITS, inputs=[dict(path=e['path'], sha256=e['sha256']) for e in frozen])
        if name == 'test-browser-graph.mjs':
            packet.update(python=config['python'], zstd_dll=config['zstd_dll'])
        packets.append(dict(path=str(base.with_suffix('.packet.json')), value=packet))
        steps.append(dict(id=f'contract-{index+1}', argv=[config['node'], str(HERE / 'browser-small-bootstrap.mjs'), packets[-1]['path']],
            timeout_seconds=command['timeout_seconds'], inputs=[os.path.relpath(e['path'], root) for e in frozen if Path(e['path']).anchor == root.anchor] +
            [os.path.relpath(owned / 'source-manifest.json', root)] +
            [os.path.relpath(p['path'], root) for p in packets], artifacts=[os.path.relpath(packet['receipt'], root)],
            depends=[f'contract-{index}'] if index else []))
    plan = dict(root=str(root), batch_timeout_seconds=7200, estimated_seconds=sum(s['timeout_seconds'] for s in steps),
                estimated_disk_bytes=64*GIB, toolchains={k: declared[config[k]] for k in ('node', 'python', 'browser')},
                features=['default-product; separately declared test reactor'], fixtures=['selected unchanged SMALL contracts'], steps=steps,
                external_input_manifest=frozen, small_observation_owner=reservation)
    if 'overall_deadline_ms' in config:
        plan['overall_deadline_ms'] = config['overall_deadline_ms']
    return dict(schema='chopper-small-runner-plan-v1', config=config, frozen=frozen, inventories=inventories,
                packets=packets, runner_plan=plan, batch_started_ms=started, reservation=reservation,
                storage_method='sum of per-file identity high-water bytes; deleted identities retained; unknown deletion races deny')


class Storage:
    """Monotonic sampled allocation envelope: no credit for deletion/shrinkage.

    Every observed identity retains its high-water. Explicit current mutable
    namespaces may reconcile a vanished unsealed name with a bounded fresh walk;
    unseen transient allocations remain unknown, not physical peak or I/O traffic.
    """
    def __init__(self, roots):
        self.roots = [canonical(root) for root in roots]
        # A previous attempt's retired bytes cannot be rediscovered from its
        # latest directory size. Require its retained ledger, add its entire
        # historical charge, and conservatively charge its visible files again.
        self.high = {}
        self.known_paths = set()
        self.total = 0
        self.known_dirs = set()
        self.path_parents = {}

    def sample(self, *, mutable_roots=(), immutable_paths=(), deadline=None):
        mutable = {str(Path(p)) for p in mutable_roots}
        sealed = {str(Path(p)) for p in immutable_paths}
        need(mutable <= {str(p) for p in self.roots}, 'Mutable storage root outside declared ownership')
        need(not mutable or deadline is not None, 'Mutable storage census requires original deadline')
        self.rescans = []
        def immutable_name(path):
            return any(Path(value).is_relative_to(path) for value in sealed)
        for root in self.roots:
            before = InputMetadata(self.path_parents).read(root)
            need(stat.S_ISDIR(before.st_mode), 'Owned storage root lost')
            def root_check():
                current = InputMetadata(self.path_parents).read(root)
                need(stat.S_ISDIR(current.st_mode) and os.path.samestat(before, current), 'Owned storage root identity drift')
            def mutable_change(error):
                name = getattr(error, 'filename', None)
                return (isinstance(error, FileNotFoundError) and name is not None and str(root) in mutable
                        and not immutable_name(Path(name)) and Path(name) != root and Path(name).is_relative_to(root))
            def onerror(error):
                if mutable_change(error) or (error.filename and immutable_name(Path(error.filename))):raise error
                need(isinstance(error, FileNotFoundError) and str(error.filename) in self.known_dirs,
                     'Unbounded owned directory census failure: ' + str(error))
            try:
                for retry in range(8):
                    try:
                        for folder, dirs, files in os.walk(root, onerror=onerror):
                            if mutable:need(time.monotonic() < deadline, 'Mutable storage census deadline')
                            folder_path = Path(folder)
                            metadata = InputMetadata(self.path_parents)
                            try:
                                need(stat.S_ISDIR(metadata.read(folder_path).st_mode), 'Owned directory changed type')
                            except FileNotFoundError as error:
                                if mutable_change(error) or immutable_name(folder_path):raise
                                need(str(folder) in self.known_dirs, 'Unbounded unseen storage deletion race')
                                continue
                            for name in dirs + files:
                                path = folder_path / name
                                try:
                                    info = metadata.read(path)
                                except FileNotFoundError as error:
                                    if mutable_change(error) or immutable_name(path):raise
                                    need(str(path) in self.known_paths, 'Unbounded unseen storage deletion race')
                                    continue
                                is_directory = name not in files
                                if is_directory:
                                    need(stat.S_ISDIR(info.st_mode), 'Owned directory changed type')
                                    self.known_dirs.add(str(path))
                                else:
                                    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Owned regular single-link files required')
                                key = (str(root), info.st_dev, info.st_ino, getattr(info, 'st_birthtime_ns', info.st_ctime_ns if os.name == 'nt' else 0))
                                size = 4096 if is_directory else ((info.st_size + 4095)//4096 + 1)*4096
                                previous = self.high.get(key, 0)
                                self.total += max(0, size-previous)
                                self.high[key] = max(previous, size)
                                self.known_paths.add(str(path))
                                need(len(self.high) <= 200000, 'Bounded storage identity table exceeded')
                            try:
                                need(stat.S_ISDIR(InputMetadata(self.path_parents).read(folder_path).st_mode), 'Owned directory changed type')
                            except FileNotFoundError as error:
                                if mutable_change(error) or immutable_name(folder_path):raise
                                need(str(folder) in self.known_dirs, 'Unbounded storage directory deletion race')
                    except FileNotFoundError as error:
                        if not mutable_change(error):raise
                        self.rescans.append(dict(root=str(root), path=str(error.filename)[:4096],
                            attempt=retry+1, unobserved_allocation='UNKNOWN'))
                        root_check()
                        need(retry < 7 and time.monotonic() < deadline, 'Mutable storage rescan exhausted/deadline')
                        continue
                    root_check()
                    if mutable:need(time.monotonic() < deadline, 'Mutable storage census deadline')
                    break
            except BaseException as error:
                error.storage_observation = dict(partial_total=self.total, complete=False, root=str(root),
                    rescans=list(self.rescans), unobserved_transient_allocation='UNKNOWN')
                raise
        need(self.total < LIMITS['stop_owned_bytes'], 'Cumulative owned storage ceiling')
        return self.total


def primed_storage(priming, fresh_roots=None):
    """Populate covered highs, preserve the accepted floor, then add only fresh roots."""
    storage=Storage(priming['covered_roots'])
    storage.sample()
    storage.total=max(storage.total,priming['ledger']['cumulative_owned_bytes'])
    storage.roots += [canonical(p) for p in (priming['fresh_roots'] if fresh_roots is None else fresh_roots)]
    return storage


class InputMetadata:
    """One fresh census: check each path and shared ancestor at most once."""
    def __init__(self, path_parents=None):
        self.seen = {}
        # Exact spellings retain the right ancestors even in case-sensitive Windows directories.
        # Only immutable lexical facts may cross fresh metadata censuses.
        self.path_parents = {} if path_parents is None else path_parents

    def read(self, value):
        path = value if isinstance(value, Path) else Path(value)
        spelling = str(path)
        if spelling not in self.seen:
            parent = self.path_parents.get(spelling)
            if parent is None:
                need(path.is_absolute() and '..' not in path.parts, 'Absolute canonical input required')
                parent = path.parent
                if len(self.path_parents) < 200000:
                    self.path_parents[spelling] = parent
            if parent != path:
                need(stat.S_ISDIR(self.read(parent).st_mode), 'Input ancestor is not a directory')
            info = path.lstat()
            need(not stat.S_ISLNK(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400),
                 'Symlink/reparse input rejected: ' + str(path))
            self.seen[spelling] = info
        return self.seen[spelling]

    def file(self, path):
        info = self.read(path)
        need(stat.S_ISREG(info.st_mode), 'Regular file required')
        # Frozen inputs bind identity; Storage separately enforces single-link ownership.
        return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]

    def inventory(self, directory):
        root = Path(directory)
        need(stat.S_ISDIR(self.read(root).st_mode), 'Inventory root missing')
        paths = []
        def walk(folder):
            with os.scandir(folder) as entries:
                for entry in entries:
                    path = folder / entry.name
                    info = self.read(path)
                    if stat.S_ISDIR(info.st_mode):
                        walk(path)
                    else:
                        need(stat.S_ISREG(info.st_mode), 'Regular input file required')
                        paths.append(str(path))
        walk(root)
        return sorted(paths)


def check_inputs(plan, path_parents=None):
    metadata = InputMetadata(path_parents)
    for entry in plan['frozen']:
        need(metadata.file(entry['path']) == entry['stat'], 'Source/tool/binary drift: ' + entry['path'])
    for directory, paths in plan['inventories'].items():
        need(metadata.inventory(directory) == paths, 'Source inventory drift: ' + directory)


class InputObservation:
    """One complete immutable-input census at a time, independently of hot guards."""
    def __init__(self, plan, *, clock=time.monotonic, wall=now_ms):
        self.plan, self.clock, self.wall = plan, clock, wall
        self.changed = threading.Condition()
        self.done = threading.Event()
        self.thread = None
        self.started = self.completed = self.error = None
        self.path_parents = {}  # Lexical paths only; each check_inputs has fresh seen/stat facts.

    def start(self):
        need(self.thread is None, 'Input census already started')
        self.thread = operation(self.run)

    def run(self):
        while not self.done.is_set():
            started, wall = self.clock(), self.wall()
            with self.changed:
                self.started = started
            try:
                check_inputs(self.plan, self.path_parents)
                need(0 <= self.clock()-started <= 2, 'Input census late/blocked')
                with self.changed:
                    self.completed = (started, wall)
                    self.changed.notify_all()
            except BaseException as error:
                with self.changed:
                    self.error = error
                    self.changed.notify_all()
                return
            self.done.wait(max(0, .5-(self.clock()-started)))

    def read(self):
        with self.changed:
            if self.error is not None:
                raise self.error
            need(self.started is not None, 'Input census not started')
            pending = self.completed is None or self.completed[0] < self.started
            need(not pending or 0 <= self.clock()-self.started <= 2, 'Input census late/blocked')
            need(self.completed is not None, 'No completed input census')
            need(0 <= self.clock()-self.completed[0] <= 5, 'Input census stale from oldest start')
            need(0 <= self.wall()-self.completed[1] <= 5000, 'Input census wall timestamp stale/future')
            return self.completed[1]

    def initial(self):
        deadline = self.clock()+2
        self.start()
        with self.changed:
            while self.completed is None and self.error is None:
                need(0 <= deadline-self.clock() <= 2, 'Initial input census late/blocked')
                self.changed.wait(.025)
        return self.read()

    def stop(self):
        self.done.set()
        if self.thread is not None:
            self.thread.join(2)
            need(not self.thread.is_alive(), 'Input census still owns a pending call')
        if self.error is not None:
            raise self.error


def census_child(census, identities, runner_pid, node, previous=None, *, runner_birth):
    def require(value, message, process=None):
        if value:
            return
        error = OSError(message)
        error.pid = process['pid'] if process else runner_pid
        error.census_child_observation = dict(runner_pid=runner_pid, runner_birth=runner_birth,
            pids=list(census['pids'][:windows.MAX_PIDS]),
            identity_pids=[p['pid'] for p in identities[:windows.MAX_PIDS]],
            chain=[process['pid'], process['parent']] if process else [],
            process={k: str(process.get(k))[:4096] if k == 'image' else process.get(k)
                     for k in ('pid', 'parent', 'created', 'image')} if process else None)
        raise error
    require(census['kill_on_close'], 'Job kill-on-close/breakaway flags denied')
    by_pid = {p['pid']: p for p in identities}
    require(len(by_pid) == len(identities) == len(census['pids'])
            and set(by_pid) == set(census['pids']), 'Job identity census mismatch')
    require(runner_pid in by_pid, 'Runner absent from actual Job')
    root = by_pid[runner_pid]
    require(type(runner_birth) is int and runner_birth > 0 and root['created'] == runner_birth,
            'Held runner birth mismatch', root)
    # The initially owner-only, non-breakaway Job proves transitive ownership;
    # an intentionally exited ancestor need not remain in its current census.
    direct = [p for p in identities if p['parent'] == runner_pid]
    unexpected = next((p for p in direct if os.path.normcase(p['image']) != os.path.normcase(node)), None)
    require(unexpected is None, 'Unexpected direct runner child', unexpected)
    require(len(direct) <= 1, 'Multiple direct runner children', direct[-1] if direct else None)
    child = direct[0] if direct else None
    if child and previous and child['pid'] == previous['pid']:
        require(child == previous, 'Child PID identity reused', child)
    return child


class Receipts:
    MAX_BYTES = 32*1024*1024

    def __init__(self):
        self.offset = 0
        self.active = False
        self.quota_at = None
        self.quota_started = self.quota_pending = None
        self.pid = None
        self.armed = False
        self.observed = False
        self.pending_exit = None
        self.cleaned = False
        self.exists = False
        self.sampled = False
        self.last_stamp = -1

    def read(self, path, packet, now, owned, guards, *, census_started_ms=None):
        if not Path(path).exists():
            need(not self.exists, 'Quota receipt lost')
            return
        self.exists = True
        data = Path(path).read_bytes()
        # An append may finish during the read; assess this snapshot at completion.
        now = now_ms() if now is None else now
        need(len(data) <= self.MAX_BYTES and len(data) >= self.offset, 'Receipt oversized/truncated')
        end = data.rfind(b'\n')+1
        for line in data[self.offset:end].splitlines(keepends=True):
            event = json.loads(line)
            timestamp = event['sampled_ms']
            need(self.last_stamp <= timestamp <= now+1000 and now-timestamp <= 5000, 'Stale/regressing receipt')
            self.last_stamp = timestamp
            kind = event['type']
            need(kind not in ('input-error', 'preflight-error', 'monitor-error', 'initialization-error'), 'Observer failure: ' + str(event))
            if kind == 'binding':
                need(not self.active and not self.armed, 'Unfinished browser lifecycle')
                actual = event['actual']
                need(actual['parentPid'] == packet['child_pid'], 'Browser outside owned direct Node child')
                self.pid, self.active, self.quota_at, self.cleaned = actual['pid'], True, timestamp, False
                self.sampled = self.observed = False
                self.pending_exit = None
                self.quota_started, self.quota_pending = timestamp, None
            elif kind == 'quota-start':
                started = event['observation_started_ms']
                need(self.active and self.quota_pending is None and 0 <= now-started <= 30000, 'Quota pending start invalid')
                need(0 <= started-self.quota_started <= 45000, 'Quota start cadence exceeded')
                self.quota_started = self.quota_pending = started
            elif kind == 'sample':
                need(self.active, 'Quota outside live observer lifecycle')
                need(-1000 <= now-event['capacity']['sampled_ms'] <= 5000, 'Stale historical Job census')
                historical = guards.get(event['capacity']['sampled_ms'])
                need(event['capacity'] in (historical if isinstance(historical, list) else [historical]),
                     'Receipt does not match real historical Job census')
                need(self.pid in event['capacity']['owned_pids'], 'Browser absent from historical Job census')
                need(event['capacity']['child_pid'] == packet['child_pid'] and event['capacity']['runner_pid'] == packet['runner_pid'], 'Receipt process binding mismatch')
                quota = event['quota']
                need(self.quota_pending is not None and 0 <= now-self.quota_pending <= 30000
                     and quota['sampled_ms'] >= self.quota_pending, 'Quota pending completion invalid')
                self.quota_pending = None
                floor = 4*GIB if not self.sampled else 2*GIB
                need(not quota.get('error') and quota['origin'] == packet['origin'] and quota['secure'] is True and quota['isolated'] is True, 'Quota origin/monitor failure')
                age = now-quota['sampled_ms']
                usable = int((quota['quota']-quota['usage'])*.8)
                if not (0 <= age <= LIMITS['disk_stale_ms'] and quota['usage'] >= 0 and usable >= floor):
                    error = OSError('Quota capacity/staleness failure')
                    error.api, error.pid, error.path = 'Receipts.read/quota', self.pid, str(path)
                    error.receipt_observation = dict(phase='quota-sample',path=str(path),pid=self.pid,
                        now_ms=now,event_ms=timestamp,quota_sampled_ms=quota['sampled_ms'],age_ms=age,
                        maximum_age_ms=LIMITS['disk_stale_ms'],usage=quota['usage'],quota=quota['quota'],
                        usable_bytes=usable,required_usable_bytes=floor,
                        quota_started_ms=self.quota_started,census_started_ms=census_started_ms)
                    raise error
                need(quota['persistence_permission'] in ('granted', 'denied', 'prompt') and type(quota['persisted']) is bool, 'Quota permission missing')
                self.quota_at = quota['sampled_ms']
                self.sampled = True
            elif kind == 'deliberate-process-kill-armed':
                need(self.sampled and self.quota_pending is None and '--process-kill' in packet['argv'] and self.active and event['pid'] == self.pid and now-self.quota_at <= LIMITS['disk_stale_ms'], 'Unapproved deliberate kill')
                self.active, self.armed = False, True
            elif kind == 'deliberate-process-kill-observed':
                need(self.armed and event['pid'] == self.pid, 'Unapproved kill observation')
                need(type(census_started_ms) is int and 0 <= now-census_started_ms <= 1000,
                     'Kill exit requires bounded actual census start')
                if census_started_ms <= timestamp:
                    # Do not consume cleanup/later lifecycles against a census
                    # begun before (or in the same millisecond as) this event.
                    self.pending_exit = timestamp
                    return
                if self.pid in owned:
                    error = OSError('Deliberate kill not actually exited')
                    error.receipt_observation = dict(pid=self.pid, event_ms=timestamp,
                        census_started_ms=census_started_ms, pids=list(owned[:windows.MAX_PIDS]))
                    raise error
                self.observed = True
                self.pending_exit = None
            elif kind == 'monitor-cleanup':
                need(self.sampled and self.quota_pending is None and not event['errors'] and (not self.armed or self.observed), 'Observer cleanup failure/missing kill observation')
                self.active, self.armed, self.cleaned = False, False, True
            self.offset += len(line)
        if self.active:
            need(self.pid in owned, 'Unexpected browser absence')
            need(now-self.quota_at <= LIMITS['disk_stale_ms'], 'Live origin quota receipt stale/missing')
            need(0 <= now-self.quota_started <= 45000, 'Quota start cadence exceeded')
            need(self.quota_pending is None or now-self.quota_pending <= 30000, 'Quota observation pending/blocked')


def validate_worker_plan(plan, owned):
    """Internal mode is still limited to same-Node SMALL bootstrap commands."""
    need(Path(plan['root']) == HERE.parent and plan['batch_timeout_seconds'] == 7200, 'Worker plan root/deadline')
    need(0 < len(plan['steps']) <= 16, 'Worker bounded selection')
    for index, step in enumerate(plan['steps']):
        argv = step['argv']
        need(len(argv) == 3 and argv[1] == str(HERE / 'browser-small-bootstrap.mjs')
             and argv[2] == str(owned / f'command-{index+1}.packet.json'), 'Worker only accepts maintained bootstrap')
        need(0 < step['timeout_seconds'] <= 900 and 'stdin_file' not in step, 'Worker command boundary')
        need(runner.digest(canonical(argv[0])) == plan['toolchains']['node'], 'Worker Node identity drift')
        packet = json.loads(Path(argv[2]).read_text())
        owning = packet['argv']
        name = Path(owning[0]).name
        need(owning[0] == str(HERE / name) and owning[1:] in VARIANTS.get(name, []), 'Worker owning harness/variant')
        need(packet['limits'] == LIMITS and packet['approved'] is True
             and packet['runner_lock'] == str(owned / 'batch/runner.lock')
             and packet['guard'] == str(owned / 'guard.json')
             and packet['receipt'] == str(owned / f'command-{index+1}.jsonl'), 'Worker packet boundary')


# Only this adapter has a fixed selection/no-resume contract. The ordinary
# runner's immutable callback has no transport, size limit or recovery policy.
OBSERVATION_BYTES = 8192
OBSERVATION_STEPS = 16  # existing approved selection ceiling
ATTEMPT_STATES = {'running', 'passed', 'failed', 'timeout', 'interrupted', 'invalidated'}


def write_control_json(path, value):
    runner.write_json(path, value, replace=windows.replace_control_snapshot)


def error_causes(error, reservation):
    causes, cause = [], error
    for _ in range(4):
        if cause is None:
            break
        uncertain = bool(getattr(cause, 'process_handle_close_uncertain', False))
        if uncertain:
            reservation['process_handle_close_uncertain'] = True
        row = dict(kind=type(cause).__name__, api=getattr(cause, 'api', 'UNKNOWN'),
                   pid=getattr(cause, 'pid', None), winerror=getattr(cause, 'winerror', None),
                   process_handle_close_uncertain=uncertain)
        for key in ('path', 'handle', 'filename', 'filename2'):
            value = getattr(cause, key, None)
            if value is not None:
                row[key] = value[:4096] if isinstance(value, str) else value
        held = getattr(cause, 'held_observation', None)
        if held is not None:
            row['held_observation'] = {key: held.get(key) for key in
                ('pid', 'birth', 'member', 'previous_birth', 'wait_state', 'image_error')}
        fresh = getattr(cause, 'fresh_census', None)
        if fresh is not None:
            row['fresh_census'] = dict(flags=fresh.get('flags'), kill_on_close=fresh.get('kill_on_close'),
                                     pids=list(fresh['pids'][:windows.MAX_PIDS]))
        post = getattr(cause, 'post_census_held_observation', None)
        if post is not None:
            row['post_census_held_observation'] = {key: post.get(key) for key in
                ('pid', 'birth', 'wait_state', 'exit_api', 'exit_error', 'exit_code')}
        storage = getattr(cause, 'storage_observation', None)
        if storage is not None:
            row['storage_observation'] = storage
        receipt = getattr(cause, 'receipt_observation', None)
        if receipt is not None:
            row['receipt_observation'] = receipt
        ancestry = getattr(cause, 'census_child_observation', None)
        if ancestry is not None:
            row['census_child_observation'] = ancestry
        row['notes'] = [note[:4096] for note in getattr(cause, '__notes__', ())[:2]]
        causes.append(row)
        cause = cause.__cause__ or cause.__context__
    return causes


class StatusReader:
    """Bound owner/plan identity and validate an ordered, non-retrying prefix.

    Repeated identical checkpoints are reads, never progress. Intermediate
    checkpoints may be coalesced by atomic replacement. Only the final runner
    recheck may invalidate an earlier pass; success requires terminal coverage.
    """
    def __init__(self, pid, plan_sha256, owner, steps):
        self.binding = dict(schema='chopper-small-runner-status-v1', runner_pid=pid,
                            runner_plan_sha256=plan_sha256, owner=owner)
        self.steps = tuple(step['id'] for step in steps)
        need(0 < len(self.steps) <= OBSERVATION_STEPS and len(set(self.steps)) == len(self.steps), 'Observation step selection')
        self.previous = None

    def read(self, path):
        raw = windows.read_control_snapshot(path, OBSERVATION_BYTES)
        need(len(raw) <= OBSERVATION_BYTES, 'Observation oversized')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                need(key not in result, 'Observation duplicate key')
                result[key] = value
            return result
        try:
            value = json.loads(raw, object_pairs_hook=unique)
        except (ValueError, UnicodeError) as error:
            raise OSError('Observation malformed JSON') from error
        return self.accept(value)

    def accept(self, value):
        need(type(value) is dict and set(value) == {*self.binding, 'sequence', 'terminal', 'attempts'}, 'Observation schema')
        need(all(type(value[k]) is type(v) and value[k] == v for k, v in self.binding.items()), 'Observation owner/PID/plan mismatch')
        sequence, terminal, attempts = value['sequence'], value['terminal'], value['attempts']
        need(type(sequence) is int and type(terminal) is bool and type(attempts) is list
             and len(attempts) <= len(self.steps), 'Observation field types/size')
        for index, entry in enumerate(attempts):
            need(type(entry) is dict and set(entry) == {'id', 'attempt', 'status'}, 'Observation attempt schema')
            need(type(entry['id']) is str and entry['id'] == self.steps[index]
                 and type(entry['attempt']) is int and entry['attempt'] == index+1
                 and type(entry['status']) is str and entry['status'] in ATTEMPT_STATES, 'Observation step/attempt/status')
            need(entry['status'] != 'running' or (index == len(attempts)-1 and not terminal), 'Observation running prefix')
            need(index == len(attempts)-1 or entry['status'] == 'passed'
                 or (terminal and entry['status'] == 'invalidated'), 'Observation failed prefix')
        # Exactly initial, two checkpoints per actual attempt, then terminal.
        expected = 1+2*len(attempts) - bool(attempts and attempts[-1]['status'] == 'running') + terminal
        need(sequence == expected, 'Observation transition sequence')
        if terminal:
            need(not attempts or len(attempts) == len(self.steps) or attempts[-1]['status'] != 'passed', 'Observation terminal coverage')
        old = self.previous
        if old is not None:
            need(sequence >= old['sequence'], 'Observation replay/regression')
            if sequence == old['sequence']:
                need(value == old, 'Observation checkpoint substitution')
            else:
                need(not old['terminal'] and len(attempts) >= len(old['attempts']), 'Observation terminal/prefix regression')
                for before, after in zip(old['attempts'], attempts):
                    need(before['status'] == 'running' or before == after
                         or (terminal and before['status'] == 'passed' and after['status'] == 'invalidated'), 'Observation state regression')
        # Keep a private detached bounded copy, including against in-process tests.
        self.previous = json.loads(json.dumps(value))
        return self.previous


class StatusWriter:
    """Trusted immutable runner snapshots -> bounded atomic owner-bound file."""
    def __init__(self, path, pid, plan_sha256, owner, steps):
        self.path = path
        self.reader = StatusReader(pid, plan_sha256, owner, steps)
        self.sequence = 0
        self.current = None

    def __call__(self, snapshot):
        self.sequence += 1
        value = dict(self.reader.binding, sequence=self.sequence, terminal=snapshot.terminal,
                     attempts=[dict(id=a.id, attempt=a.attempt, status=a.status) for a in snapshot.attempts])
        self.reader.accept(value)
        raw = (json.dumps(value, separators=(',', ':'))+'\n').encode('utf-8')
        need(len(raw) <= OBSERVATION_BYTES, 'Observation oversized')
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        windows.replace_control_snapshot(temporary, self.path)
        self.current = snapshot



def command_ready_path(owned, attempt):
    need(type(attempt) is int and 1 <= attempt <= 15, 'Command handshake attempt outside fixed selection')
    return owned / f'command-ready-{attempt}.json'


def publish_command_ready(owned, attempt, published):
    path = command_ready_path(owned, attempt)
    if attempt not in published:
        # The completed current full guard authorizes this one immutable handoff.
        runner.write_json(path, dict(attempt=attempt))
        published.add(attempt)  # A failed publication never becomes acknowledged.


def worker(plan_path, owned):
    # Internal mode cannot execute a supplied command. It waits for the external
    # lock-owning supervisor to duplicate and verify this specific session Job.
    execution_sha = runner.digest(plan_path)
    need(os.environ.pop('CHOPPER_SMALL_WORKER_PLAN_SHA256', None) == execution_sha, 'Internal worker requires supervisor-bound plan')
    execution = json.loads(plan_path.read_text())
    validate_worker_plan(execution, owned)
    overall = execution.get('overall_deadline_ms')
    if overall is not None:
        need(type(overall) is int and 0 < overall < 2**53, 'Worker overall deadline type')
    stop = time.monotonic()+min(7200, max(0, (overall-120000-now_ms())/1000)) if overall is not None else None
    def check_overall():
        need(stop is None or time.monotonic() < stop, 'Worker overall deadline')
    check_overall()
    runner.contain_session()
    session = runner.owned_windows_job()
    writer = StatusWriter(owned / 'runner-observation.json', os.getpid(), execution_sha,
                          execution['small_observation_owner'], execution['steps'])
    def observe(snapshot):
        writer(snapshot)
        if writer.sequence == 1:
            # Publish initial runner state before the parent can begin reading it.
            runner.write_json(owned / 'job.json', dict(pid=os.getpid(), **session))
            deadline = time.monotonic()+5
            ack = owned / 'job-owned.json'
            while not ack.exists():
                need(stop is None or time.monotonic() < stop, 'Worker overall deadline')
                need(time.monotonic() < deadline, 'Supervisor ownership acknowledgement timed out')
                time.sleep(.025)
            proof = json.loads(ack.read_text())
            need(proof == dict(runner_pid=os.getpid(), supervisor_pid=os.getppid(),
                               handle=session['handle'], execution_sha256=execution_sha),
                 'Supervisor ownership acknowledgement mismatch')
            # Close our last handle promptly: supervisor loss now kills this
            # Job while product admission waits for the separate disk census.
            windows.close(session['handle'])
            deadline = time.monotonic()+35
            while not (owned / 'ready.json').exists():
                need(stop is None or time.monotonic() < stop, 'Worker overall deadline')
                need(time.monotonic() < deadline, 'Supervisor disk/readiness admission timed out')
                time.sleep(.025)
    last_attempt = 0
    def guard():
        nonlocal last_attempt
        check_overall()
        need(writer.current is not None, 'Missing runner observation')
        attempt = len(writer.current.attempts)
        if attempt != last_attempt:
            deadline = time.monotonic()+5
            while True:
                ack = command_ready_path(owned, attempt)
                if ack.exists() and json.loads(ack.read_text()).get('attempt') == attempt:
                    break
                check_overall()
                need(time.monotonic() < deadline, 'Pre-spawn supervisor handshake timed out')
                time.sleep(.025)
            last_attempt = attempt
        value = json.loads(windows.read_control_snapshot(owned / 'guard.json', 65536))
        need(value['allowed'] and not value.get('error') and -1000 <= now_ms()-value['sampled_ms'] <= 5000, 'Supervisor denied/stale')
        need(value['runner_pid'] == os.getpid(), 'Runner identity mismatch')
    code = runner.run(plan_path, owned / 'batch', guard=guard, observe=observe)
    runner.write_json(owned / 'worker-result.json', dict(code=code))
    # Keep the runner process alive while the supervisor retains its Job handle and reaps all
    # descendants and read the final receipts. Never detach children at exit.
    while True:
        check_overall()
        value = json.loads(windows.read_control_snapshot(owned / 'guard.json', 65536))
        need(value['allowed'] and now_ms()-value['sampled_ms'] <= 5000, 'Supervisor lost during cleanup')
        time.sleep(.1)


class Watchdog:
    """Independent of runner and supervisor filesystem operations."""
    def __init__(self, job, process, timeout=1, terminate=None, deadline=None, inputs=None):
        self.job, self.process, self.timeout = job, process, timeout
        self.deadline, self.inputs = deadline, inputs
        self.terminate = terminate or windows.terminate
        self.beat = time.monotonic()
        self.error = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.watch, daemon=True)

    def watch(self):
        while not self.done.wait(.05):
            expired = self.deadline is not None and time.monotonic() >= self.deadline
            input_error = None
            if self.inputs is not None:
                try:
                    self.inputs.read()
                except BaseException as error:
                    input_error = 'Independent watchdog: '+str(error)
            if expired or input_error or time.monotonic()-self.beat > self.timeout:
                self.error = input_error or ('Independent watchdog: overall execution deadline' if expired else 'Independent watchdog: atomic heartbeat late/blocked')
                try:
                    self.terminate(self.job)
                    self.process.wait(timeout=10)
                except BaseException as error:
                    self.error += '; stop/reap: ' + str(error)
                # Worker streams and any partial runner attempt remain untouched.
                os.write(2, (self.error+'\n').encode())
                return

    def pulse(self):
        need(self.error is None, self.error or 'Watchdog failed')
        self.beat = time.monotonic()


def write_capacity(config):
    need(any(str(canonical(volume)) == str(Path('C:/')) for volume in config['volumes']),
         'Explicit shared C: write volume required')
    need(shutil.disk_usage('C:/').free-LIMITS['owned_bytes'] >= 128*GIB,
         'Physical C: headroom after declared future growth')


def supervise(plan_path, approval):
    need(os.name == 'nt', 'Execution requires native Windows; no fallback')
    approval_identity = freeze(plan_path)
    need(approval_identity['sha256'] == approval, 'Exact plan approval SHA256 required')
    plan = json.loads(plan_path.read_text())
    no_nulls(plan)
    need(plan['schema'] == 'chopper-small-runner-plan-v1', 'Plan schema')
    config, owned = plan['config'], canonical(plan['config']['owned_root'])
    need(not owned.exists(), 'No resume/retries; fresh owned root required')
    need(config['python'] == str(Path(sys.executable).resolve()), 'Use approved native Python executable')
    stop = time.monotonic()+max(0, (execution_deadline_ms(plan)-now_ms())/1000)
    # Reconcile config-derived executable plan; only volatile prepare IDs differ.
    rebuilt = prepare(config)
    rebuilt['runner_plan']['small_observation_owner'] = plan['reservation']
    need(plan['runner_plan']['small_observation_owner'] == plan['reservation'], 'Observation owner/plan mismatch')
    for key in ('frozen', 'inventories', 'runner_plan', 'storage_method'):
        need(rebuilt[key] == plan[key], 'Plan/config mismatch: ' + key)
    for candidate, approved in zip(rebuilt['packets'], plan['packets'], strict=True):
        candidate['value'].update(batch_started_ms=plan['batch_started_ms'], reservation=plan['reservation'])
        need(candidate == approved, 'Packet/config mismatch')
    check_execution_deadline(plan)
    need(time.monotonic() < stop, 'Fixed overall execution deadline')
    write_capacity(config)
    local = module('local-ci')
    with local.host_lock():
        owned.mkdir()
        temp = owned / 'temp'
        temp.mkdir()
        lock_identity = stamp_lock(local.host_lock_path())
        reservation = dict(lock_identity=lock_identity, id=plan['reservation'], supervisor_pid=os.getpid(), held=True,
                           lock=str(local.host_lock_path()), acquired_ms=now_ms())
        runner.write_json(owned / 'reservation.json', reservation)
        for packet in plan['packets']:
            runner.write_json(Path(packet['path']), packet['value'])
        runner.write_json(owned / 'source-manifest.json', plan['frozen'])
        execution = owned / 'runner-plan.json'
        runner.write_json(execution, plan['runner_plan'])
        environment = dict(os.environ, TEMP=str(temp), TMP=str(temp), CHOPPER_SMALL_WORKER_PLAN_SHA256=runner.digest(execution))
        for key in ('NODE_OPTIONS', 'NODE_PATH', 'CHOPPER_SMALL_CONTRACT_PACKET', 'CHOPPER_SMALL_CONTRACT_REQUIRED'):
            environment.pop(key, None)
        job, process, watchdog, resources = None, None, None, None
        failure = None
        try:
            with (owned / 'worker-stdout.log').open('wb') as out, (owned / 'worker-stderr.log').open('wb') as err:
                reservation['worker_launch_attempted'] = True
                process = subprocess.Popen([config['python'], str(HERE / 'browser-small-runner.py'), '_worker', str(execution), str(owned)],
                    env=environment, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
                deadline = time.monotonic()+5
                while not ((owned / 'job.json').exists() and (owned / 'runner-observation.json').exists()):
                    need(process.poll() is None and time.monotonic() < deadline, 'Owned Job startup failed/timed out')
                    time.sleep(.025)
                startup = json.loads((owned / 'job.json').read_text())
                need(startup['pid'] == process.pid, 'Job owner PID mismatch')
                job = windows.duplicate_job(process.pid, startup['handle'])
                proof = windows.query_job(job)
                need(proof['kill_on_close'] and proof['pids'] == [process.pid], 'Owned Job acknowledgement census mismatch')
                reservation['worker_birth'] = windows._held_birth(windows.kernel(), process._handle, process.pid)
                runner.write_json(owned/'job-owned.json', dict(runner_pid=process.pid, supervisor_pid=os.getpid(),
                    handle=startup['handle'], execution_sha256=runner.digest(execution)))
                # This constructor only inventories/hashes immutable files. Share
                # the disk setup bound; live process/status guards stay at .8s/1s.
                setup_deadline = time.monotonic()+30
                resources = bounded_cleanup(lambda: resource_state(plan, owned, approval_identity), timeout=30)
                if resources.get('disk'):
                    disk_start = time.monotonic()
                    resources['disk'].start()
                    remaining = setup_deadline-time.monotonic()
                    need(remaining > 0, 'Initial filesystem setup timed out')
                    resources['disk'].after(disk_start, timeout=remaining)
                # No Node admission until a full, bounded immutable census completes.
                resources['inputs'].initial()
                watchdog = Watchdog(job, process, deadline=stop, inputs=resources['inputs'])
                watchdog.thread.start()
                run_supervision(plan, owned, process, job, reservation, watchdog, approval_identity, resources)
        except BaseException as error:
            reservation['failure_causes'] = error_causes(error, reservation)
            failure = str(error)
            try:
                bounded_cleanup(lambda: write_control_json(owned / 'guard.json', dict(schema='chopper-small-contract-guard-v1', allowed=False,
                                  sampled_ms=now_ms(), error=failure)))
                bounded_cleanup(lambda: runner.write_json(owned / 'control-failure.json', dict(error=failure, sampled_ms=now_ms(), causes=reservation['failure_causes'], sample_trace=list(resources.get('sample_trace', [])) if resources else [])))
            except BaseException as retention_error:
                reservation['retention_failure_causes'] = error_causes(retention_error, reservation)
                failure += '; failure retention: ' + str(retention_error)
        finally:
            cleanup = finish_supervision(plan, owned, process, job, reservation, watchdog, resources, failure)
        if not reservation.get('release_safe'):
            try:
                runner.write_json(owned / 'owner-retained.json', dict(reservation=plan['reservation'],
                    pid=os.getpid(), release=False, reason='Owned cleanup/thread/Job quiescence not established'))
            except BaseException:
                pass  # Receipt failure cannot release the original descriptor.
            # Process exit would release the original descriptor. Root must
            # reconcile this owner just as for the actual-picker controller.
            while True:
                try:
                    time.sleep(1)
                except BaseException:
                    pass
        code = 1 if failure is not None or cleanup else 0
    # The host_lock context has closed its original descriptor at this point.
    runner.write_json(owned / 'reservation-released.json', dict(
        reservation=plan['reservation'], original_lock_identity=lock_identity,
        released_after_supervision=True, passed=code == 0))
    return code


def qualify(plan_path, approval, config_path, preparation, *, first_command_control=False):
    from scale_acceptance.hosted_qualification import preflight, receipt
    # Admission precedes host-lock acquisition, worker creation and the channel
    # clock. Supervise still reconstructs and checks the complete selected plan.
    preflight(preparation, config_path, 'small')
    from scale_acceptance.hosted_qualification import batch_admission
    selected_config=json.loads(config_path.read_text())
    plan = json.loads(plan_path.read_text())
    need(selected_config == plan['config'], 'Preflight config/plan mismatch')
    admission=batch_admission(selected_config, 'small', selected_config['channel'])
    selected=plan['config']['commands']
    if first_command_control:
        need(selected==command_specs(first_only=True),'Exact first-command control required')
    else:
        need([(c['script'],c['flags']) for c in selected]==[(c['script'],c['flags']) for c in command_specs()],
             'Full fifteen-command qualification required')
    code = supervise(plan_path, approval)
    owned = Path(plan['config']['owned_root'])
    result = json.loads((owned / 'result.json').read_text())
    released = json.loads((owned / 'reservation-released.json').read_text())
    passed = code == 0 and result['passed'] is True and released['passed'] is True
    if first_command_control:
        runner.write_json(owned/'component-result.json',dict(schema='chopper-small-first-command-control-v1',
            qualification=False,passed=passed,preflight=preparation,plan_sha256=approval,
            selected_commands=selected,controller_result=result,reservation_release=released))
        return 0 if passed else 1
    runner.write_json(owned / 'tiny-qualification.json', receipt('small', plan['config']['channel'],
        preparation, passed=passed, details=dict(plan_sha256=approval,batch_admission=admission,
            selected_commands=plan['config']['commands'], input_files=len(plan['frozen']),
            complete_inventory_sha256=hashlib.sha256(json.dumps(plan['inventories'], sort_keys=True).encode()).hexdigest(),
            full_cold_guard_required=True, controller_result=result, reservation_release=released,
            coverage='selected unchanged SMALL contracts; injected handles; no actual-picker or scale claim')))
    return 0 if passed else 1


def bounded_cleanup(action, timeout=.8):
    """Native and filesystem cleanup cannot block the supervising thread."""
    result, errors = [], []
    def call():
        try:
            result.append(action())
        except BaseException as error:
            errors.append(error)
    thread = operation(call)
    thread.join(timeout)
    need(not thread.is_alive(), 'Cleanup operation late/blocked')
    if errors:
        raise errors[0]
    return result[0]


def finish_supervision(plan, owned, process, job, reservation, watchdog, resources, failure):
    errors = []
    if reservation.get('process_handle_close_uncertain'):
        errors.append('Parent handle close unproven')
    if reservation.get('worker_launch_attempted') and process is None:
        errors.append('Worker launch ownership uncertain: no returned process handle')
    job_empty = job is None
    job_closed = job is None
    def attempt(action, timeout=.8):
        try:
            return bounded_cleanup(action) if timeout == .8 else bounded_cleanup(action, timeout)
        except BaseException as error:
            error_causes(error, reservation)
            errors.append(str(error))
            return None
    def sample():
        nonlocal job_empty
        need(0 <= now_ms()-plan['batch_started_ms'] < 7200000, 'Cleanup channel deadline')
        need(0 <= now_ms()-resources['last_progress_ms'] < 600000, 'Cleanup contract progress deadline')
        value = sample_resources(plan, resources['pinned'], reservation, job, resources['storage'], False,
                                 processes=False, disk=resources.get('disk'), inputs=resources.get('inputs'))
        job_empty = not value[0]['pids']
        if watchdog and not watchdog.done.is_set():
            watchdog.pulse()
        return value
    try:
        # Keep the independent watchdog and real resource census active until
        # membership is empty, the worker is reaped, and final writes are checked.
        if resources is not None:
            attempt(sample)
        if job is not None:
            attempt(lambda: windows.terminate(job))
            deadline = time.monotonic()+10
            while True:
                value = attempt(sample) if resources is not None else attempt(lambda: windows.query_job(job))
                if value is None:
                    # Resource/deadline denial still leaves the independent
                    # bounded Job census available for stop/reap proof.
                    census = attempt(lambda: windows.query_job(job))
                    if census is None:
                        break
                else:
                    census = value[0] if resources is not None else value
                job_empty = not census['pids']
                if not census['pids']:
                    break
                if time.monotonic() >= deadline:
                    errors.append('Owned Job did not reap')
                    break
                time.sleep(.025)
        if process is not None:
            if job is None and process.poll() is None:
                attempt(process.kill)  # no Node can start before ready.json
            deadline = time.monotonic()+10
            while process.poll() is None and time.monotonic() < deadline:
                if resources is not None:
                    attempt(sample)
                time.sleep(.025)
            attempt(lambda: process.wait(timeout=.1))
        if resources is not None:
            attempt(sample)
        # No product process remains. The hot watchdog has no live process to
        # protect while final disk observations finish; pending I/O stays owned.
        if watchdog and resources is not None and resources.get('disk') and job_empty and (process is None or process.returncode is not None):
            watchdog.done.set()
            watchdog.thread.join(timeout=11)
        if watchdog and watchdog.error:
            errors.append(watchdog.error)
        cleanup = dict(errors=errors, worker_returncode=process.returncode if process else None, sampled_ms=now_ms())
        result = dict(passed=failure is None and not errors, error=failure, cleanup_errors=errors)
        if reservation.get('failure_causes'):
            result['error_causes'] = reservation['failure_causes']
        if reservation.get('retention_failure_causes'):
            result['retention_error_causes'] = reservation['retention_failure_causes']
        if resources is not None:
            # Charge a bounded allowance before these atomic files are written.
            # The post-write census must fit it; the ledger retains this charge.
            disk = resources.get('disk')
            completed = attempt(lambda: disk.after(time.monotonic()), 30) if disk else None
            need(disk is None or completed is not None, 'Final disk observation incomplete')
            observed_total = completed['value']['total'] if completed else resources['storage'].total
            reserved = observed_total + 1024**2
            need(reserved < LIMITS['stop_owned_bytes'], 'Final metadata storage ceiling')
            need(sum(len(json.dumps(v).encode()) for v in (cleanup, result)) < 512*1024, 'Final metadata bound')
            attempt(lambda: runner.write_json(owned / 'storage-ledger.json', dict(method=plan['storage_method'], cumulative_owned_bytes=reserved, sampled_ms=now_ms(), final_metadata_allowance=1024**2)))
        attempt(lambda: runner.write_json(owned / 'cleanup.json', cleanup))
        result.update(passed=failure is None and not errors, cleanup_errors=list(errors))
        attempt(lambda: runner.write_json(owned / 'result.json', result))
        if resources is not None:
            if resources.get('disk'):
                need(attempt(lambda: resources['disk'].after(time.monotonic()), 30) is not None,
                     'Post-write disk observation incomplete')
            value = attempt(sample)
            if value is not None and value[3] > reserved:
                errors.append('Final metadata exceeded reserved storage')
        if errors:
            attempt(lambda: runner.write_json(owned / 'result.json', dict(passed=False, error=failure, cleanup_errors=list(errors))))
    except BaseException as error:
        errors.append(str(error))
        attempt(lambda: runner.write_json(owned / 'result.json', dict(passed=False, error=failure, cleanup_errors=list(errors))))
    finally:
        if resources is not None and resources.get('inputs'):
            attempt(resources['inputs'].stop, 2.1)
        if resources is not None and resources.get('disk'):
            attempt(resources['disk'].stop, 30)
        # Keep the independent stop/reap path available until the held Job
        # handle is released, including failed cleanup paths.
        if job is not None and job_empty and (process is None or process.returncode is not None) and not any(t.is_alive() for t in OPERATIONS):
            before_close = len(errors)
            attempt(lambda: windows.close(job))
            job_closed = len(errors) == before_close
        elif job is not None:
            errors.append('Owned Job handle retained: process/sample thread quiescence not established')
        if watchdog:
            watchdog.done.set()
            watchdog.thread.join(timeout=11)
            if watchdog.thread.is_alive():
                errors.append('Cleanup watchdog did not finish')
            if watchdog.error and watchdog.error not in errors:
                errors.append(watchdog.error)
    if errors:
        attempt(lambda: runner.write_json(owned / 'result.json', dict(passed=False, error=failure, cleanup_errors=list(errors))))
    reservation['release_safe'] = (not reservation.get('process_handle_close_uncertain') and
        (not reservation.get('worker_launch_attempted') or process is not None) and job_empty and job_closed and
        (process is None or process.returncode is not None) and
        (watchdog is None or not watchdog.thread.is_alive()) and
        not any(thread.is_alive() for thread in OPERATIONS))
    return errors


def sample_resources(plan, pinned, reservation, job, storage, initial, *, processes=True, trace=None, disk=None, deadline=None, inputs=None):
    config = plan['config']
    def phase(name, action):
        started = time.monotonic()
        if trace is not None:
            trace.append(dict(phase=name, event='start', sampled_ms=now_ms()))
        value = action()
        if trace is not None:
            trace.append(dict(phase=name, event='complete', seconds=time.monotonic()-started))
        return value
    input_errors = []
    def scan_inputs():
        try:
            phase('inputs', lambda: check_inputs(plan))
        except BaseException as error:
            input_errors.append(error)
    # Hot identity/census work keeps its .8s bound. Disk I/O has its own owned
    # 30s operation and publishes only completed, oldest-start-aware facts.
    input_thread = None
    if inputs is None:
        input_thread = threading.Thread(target=scan_inputs, daemon=True)
        input_thread.start()
    else:
        phase('completed-inputs', inputs.read)
    try:
        def bindings():
            need(stamp_lock(module('local-ci').host_lock_path()) == reservation['lock_identity'], 'Held host reservation lock replaced')
            for entry in pinned:
                need(stamp(entry['path']) == entry['stat'], 'Packet/reservation/plan drift')
        phase('reservation-and-pinned', bindings)
        census = phase('job-census', lambda: windows.query_job(job))
        def process_identities():
            nonlocal census
            if not processes or not census['pids']:
                return []
            try:
                snapshot = (windows.job_processes(job, census) if deadline is None else
                            windows.job_processes(job, census, deadline=deadline))
            except BaseException as error:
                causes = error_causes(error, reservation)
                if trace is not None:
                    trace.append(dict(phase='process-identities', event='error', pid=getattr(error, 'pid', None),
                        census_pids=list(census['pids']), causes=causes,
                        completed_processes=[dict(pid=v['pid'], created=v['created'])
                                             for v in getattr(error, 'completed_processes', ())],
                        retired_snapshots=getattr(error, 'retired_snapshots', [])))
                raise
            latest, values = snapshot['census'], snapshot['processes']
            if trace is not None and snapshot.get('retired_snapshots'):
                trace.append(dict(phase='process-identities', event='snapshot-retired',
                                  retired_snapshots=snapshot['retired_snapshots']))
            census = latest
            return values
        identities = phase('process-identities', process_identities)
        if disk is None:  # Direct component callers; supervision supplies its owned sampler.
            started_ms = now_ms()
            capacity = phase('capacity', lambda: [dict(path=p, free_bytes=shutil.disk_usage(p).free, sampled_ms=started_ms) for p in config['volumes']])
            total = phase('storage', storage.sample)
        else:
            observed = disk.read()
            capacity = [dict(value, sampled_ms=observed['started_ms']) for value in observed['value']['capacity']]
            total = observed['value']['total']
            if trace is not None and observed['value'].get('storage_rescans'):
                trace.append(dict(phase='storage', event='mutable-rescan',
                                  rescans=observed['value']['storage_rescans']))
        floor = LIMITS['start_free_bytes'] if initial else LIMITS['stop_free_bytes']
        need(all(v['free_bytes'] >= floor for v in capacity), 'Physical free capacity floor')
    finally:
        if input_thread is not None:
            input_thread.join()
    if input_errors:
        raise input_errors[0]
    return census, identities, capacity, total


def resource_state(plan, owned, approval_identity):
    config = plan['config']
    debit, adopted, priming = 0, [], None
    input_errors, input_thread = [], None
    if 'retained_origin_manifest' in config:
        def inputs():
            try:
                check_inputs(plan)
            except BaseException as error:
                input_errors.append(error)
        # As in live sampling, overlap independent read-only censuses. The outer
        # tracked initialization stays alive until this child has actually joined.
        input_thread = threading.Thread(target=inputs, daemon=True)
        input_thread.start()
    try:
        if 'retained_origin_manifest' in config:
            debit, adopted, priming = retained_origin(config, with_priming=True)
            need(any(e['path'] == config['retained_origin_manifest'] for e in plan['frozen']),
                 'Retained origin manifest must be frozen')
        if priming is not None:
            storage = primed_storage(priming)
        else:
            # Historical origins retain their explicitly conservative accounting.
            storage = Storage([owned, *config['history_roots'], *adopted])
            storage.total += debit
            for root in config['history_roots']:
                ledger = json.loads((Path(root) / 'storage-ledger.json').read_text())
                need(ledger['method'] == plan['storage_method'] and type(ledger['cumulative_owned_bytes']) is int and ledger['cumulative_owned_bytes'] >= 0, 'Invalid retained storage ledger')
                storage.total += ledger['cumulative_owned_bytes']
    finally:
        if input_thread is not None:
            input_thread.join()
            if input_errors:
                raise input_errors[0]
    pinned = [freeze(owned / name) for name in ('reservation.json', 'runner-plan.json', 'source-manifest.json')]
    pinned += [freeze(Path(p['path'])) for p in plan['packets']] + [approval_identity]
    if 'retained_origin_manifest' in config:
        identity = freeze(canonical(config['retained_origin_manifest']))
        need(identity == next(e for e in plan['frozen'] if e['path'] == identity['path']),
             'Retained origin manifest drift')
        pinned.append(identity)
    from scale_acceptance.guard import DiskObservation
    def disk_sample():
        capacity = [dict(path=p, free_bytes=shutil.disk_usage(p).free) for p in config['volumes']]
        total = storage.sample(mutable_roots=[owned],
            immutable_paths=[v['path'] for v in plan['frozen'] + pinned],
            deadline=observation.started + observation.seconds)
        return dict(capacity=capacity, total=total, storage_rescans=list(storage.rescans))
    observation = DiskObservation(disk_sample, launch=operation)
    return dict(storage=storage, pinned=pinned, last_progress_ms=plan['batch_started_ms'],
                disk=observation, inputs=InputObservation(plan))


def run_supervision(plan, owned, process, job, reservation, watchdog, approval_identity, resources=None):
    config = plan['config']
    check_execution_deadline(plan)
    need(now_ms()-plan['batch_started_ms'] < 600000, 'No actual contract progress for ten minutes')
    resources = resources or resource_state(plan, owned, approval_identity)
    if resources.get('disk') and resources['disk'].thread is None:
        disk_start = time.monotonic()
        resources['disk'].start()
        resources['disk'].after(disk_start)
    storage, pinned = resources['storage'], resources['pinned']
    packets = [p['value'] for p in plan['packets']]
    receipts = [Receipts() for _ in packets]
    last_progress, completed = plan['batch_started_ms'], 0
    progress_tick = time.monotonic() - max(0, (now_ms()-last_progress)/1000)
    initial, child, last_child = True, None, None
    started = time.monotonic()
    guards = {}
    published_attempts = set()
    observer = None
    while True:
        tick = time.monotonic()
        need(process.poll() is None, 'Runner exited before owned cleanup')
        check_execution_deadline(plan)
        need(time.monotonic()-started < 7200, 'Fixed channel deadline')
        need(0 <= now_ms()-last_progress < 600000 and time.monotonic()-progress_tick < 600, 'No actual contract progress for ten minutes')
        # A bounded sampling task keeps the hard watchdog independent of a hung
        # filesystem, input check, native census or runner hashing operation.
        result, errors = [], []
        trace = []
        resources['sample_trace'] = trace
        def sample():
            nonlocal observer
            try:
                sampled = sample_resources(plan, pinned, reservation, job, storage, initial, trace=trace,
                                           disk=resources.get('disk'), deadline=deadline, inputs=resources.get('inputs'))
                if observer is None:
                    execution_sha = next(p['sha256'] for p in pinned if p['path'] == str(owned / 'runner-plan.json'))
                    observer = StatusReader(process.pid, execution_sha, plan['reservation'], plan['runner_plan']['steps'])
                # Read result first: a visible result must already have its
                # terminal checkpoint. Avoid pairing a new result with an older
                # observation captured earlier in this sample.
                outcome_path = owned / 'worker-result.json'
                outcome = json.loads(outcome_path.read_text()) if outcome_path.exists() else None
                observed_at = time.monotonic()
                trace.append(dict(phase='runner-observation', event='start', sampled_ms=now_ms()))
                observed = observer.read(owned / 'runner-observation.json')
                trace.append(dict(phase='runner-observation', event='complete', seconds=time.monotonic()-observed_at))
                result.append((sampled, observed, outcome))
            except BaseException as error:
                errors.append(error)
        census_started_ms = now_ms()  # oldest start of this owned full observation
        deadline = time.monotonic()+.8
        thread = operation(sample)
        thread.join(max(0, deadline-time.monotonic()))
        need(not thread.is_alive(), 'Independent hard watchdog: guard sample late/blocked')
        if errors:
            raise errors[0]
        (census, identities, capacity, total), state, outcome = result[0]
        check_execution_deadline(plan)
        child = census_child(census, identities, process.pid, config['node'], last_child,
                             runner_birth=reservation.get('worker_birth'))
        if child:
            if not last_child or child['pid'] != last_child['pid']:
                need(all(v['free_bytes'] >= LIMITS['start_free_bytes'] for v in capacity), 'New command startup capacity floor')
            last_child = child
        attempts = state['attempts']
        reported_passed = sum(a['status'] == 'passed' for a in attempts)
        active_index = max(0, len(attempts)-1)
        need(active_index < len(packets), 'Runner attempt outside approved selection')
        if child:
            need((owned / 'batch/runner.lock').read_text() == str(process.pid), 'Live runner lock identity mismatch')
        for index in range(min(len(attempts), len(packets))):
            packet = dict(packets[index], runner_pid=process.pid, child_pid=child['pid'] if child else (last_child['pid'] if last_child else None))
            receipts[index].read(packet['receipt'], packet, None, census['pids'], guards,
                                 census_started_ms=census_started_ms)
            if attempts[index]['status'] == 'passed':
                need(receipts[index].cleaned or receipts[index].pending_exit is not None,
                     'Command completed without final observer receipt')
        pending_exit = any(receipt.pending_exit is not None for receipt in receipts)
        passed = sum(a['status'] == 'passed' and receipts[i].cleaned for i,a in enumerate(attempts))
        need(all(a['status'] in ('running', 'passed') for a in attempts), 'Runner observation reports failure')
        if outcome is not None:
            need(type(outcome['code']) is int and outcome['code'] == 0 and state['terminal']
                 and reported_passed == len(packets), 'Runner contracts incomplete/failed or missing terminal observation')
        if passed > completed:
            # Only actual completed steps WITH their matching cleanup receipts.
            completed, last_progress = passed, now_ms()
            resources['last_progress_ms'] = last_progress
            progress_tick = time.monotonic()
        input_started_ms = resources['inputs'].read() if resources.get('inputs') else census_started_ms
        value = dict(schema='chopper-small-contract-guard-v1', allowed=True,
            sampled_ms=min(census_started_ms, input_started_ms),
            last_progress_ms=last_progress, runner_pid=process.pid, child_pid=child['pid'] if child else None,
            owned_pids=census['pids'], reservation=plan['reservation'], reservation_held=True,
            windows_job_kill_on_close=census['kill_on_close'], batch_started_ms=plan['batch_started_ms'],
            cumulative_owned_bytes=total, volumes=capacity)
        write_control_json(owned / 'guard.json', value)
        watchdog.pulse()
        runner.write_json(owned / 'storage-ledger.json', dict(method=plan['storage_method'], cumulative_owned_bytes=total,
            sampled_ms=min((v['sampled_ms'] for v in capacity), default=value['sampled_ms'])))
        variants = guards.setdefault(value['sampled_ms'], [])
        variants.append(value)
        need(len(variants) <= 32, 'Bounded historical guard variants exceeded')
        # Retain only the last five seconds of trusted capacities in memory;
        # the complete census remains in guard-history.jsonl.
        guards = {t: v for t, v in guards.items() if now_ms()-t <= 6000}
        if attempts and child is None and attempts[-1]['status'] == 'running' and not pending_exit:
            publish_command_ready(owned, len(attempts), published_attempts)
        with (owned / 'guard-history.jsonl').open('a') as log:
            log.write(json.dumps(dict(value, process_identities=identities, job_flags=census['flags'], sample_trace=list(trace)))+'\n')
        if initial:
            runner.write_json(owned / 'ready.json', dict(runner_pid=process.pid))
            initial = False
        if outcome is not None and not pending_exit:
            return
        need(time.monotonic()-tick < 1, 'Atomic heartbeat exceeded one second')
        time.sleep(max(0, .5-(time.monotonic()-tick)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    prepare_parser = sub.add_parser('prepare')
    prepare_parser.add_argument('config', type=Path)
    prepare_parser.add_argument('output', type=Path)
    run_parser = sub.add_parser('run')
    run_parser.add_argument('plan', type=Path)
    run_parser.add_argument('--approve-sha256', required=True)
    qualification = sub.add_parser('qualify', help='complete selected SMALL path; no scale or actual-picker claim')
    qualification.add_argument('plan', type=Path)
    qualification.add_argument('--approve-sha256', required=True)
    qualification.add_argument('--config', type=Path, required=True)
    qualification.add_argument('--preflight', type=Path, required=True)
    qualification.add_argument('--preflight-sha256', required=True)
    qualification.add_argument('--first-command-control',action='store_true',help='one exact first command; never full qualification')
    internal = sub.add_parser('_worker', help=argparse.SUPPRESS)
    internal.add_argument('plan', type=Path)
    internal.add_argument('owned', type=Path)
    args = parser.parse_args()
    if args.mode == 'prepare':
        need(not args.output.exists(), 'Do not overwrite reviewed plans')
        plan = prepare(json.loads(args.config.read_text()))
        runner.write_json(args.output, plan)
        print(json.dumps(dict(plan=str(args.output.resolve()), sha256=runner.digest(args.output),
                             commands=[step['argv'] for step in plan['runner_plan']['steps']]), indent=2))
        return 0
    if args.mode == '_worker':
        return worker(args.plan, args.owned)
    if args.mode == 'qualify':
        return qualify(args.plan, args.approve_sha256, args.config,
                       dict(path=str(args.preflight), sha256=args.preflight_sha256),first_command_control=args.first_command_control)
    return supervise(args.plan, args.approve_sha256)


if __name__ == '__main__':
    raise SystemExit(main())
