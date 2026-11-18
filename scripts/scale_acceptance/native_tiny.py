"""Explicit tiny domain for the native controller; never a scale-slot owner."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import threading
import time
from .native_scale_identity import Lineage, digest, path, stamp
from .verify import read_json, require, sha256

SCHEMA = 'native-tiny-qualification-v1'
INPUT_BYTES = 1024**2
NEW_BYTES = 64*1024**2
METADATA = dict(read_bytes=768*1024**2, visits=2_000_000)


def metadata_limits(value):
    require(set(value) == {'read_bytes', 'visits'} and
            all(type(amount) is int and amount > 0 for amount in value.values()),
            'explicit positive tiny metadata/tool-input allowances required')


def budget_check():
    if 'budget' in globals():
        budget.check()


def budget_usage():
    if 'budget' not in globals():
        return None
    return dict(charged_read_bytes=budget.read_bytes, directory_entries_and_opens=budget.visits,
                exhausted=budget.failed, allowance=budget.limits)


def cold_admission_seconds(plan):
    require(plan['os'] in ('Linux','Windows'), 'selected native cold-admission platform required')
    return 30 if plan['os']=='Windows' else 2


def enabled(plan):
    return 'qualification' in plan


def pinned_json(item, limit):
    p = path(item['path'])
    before = stamp(p)
    require(p.stat().st_size <= limit and sha256(p) == digest(item['sha256']), 'tiny pinned record hash/size mismatch')
    value = read_json(p, limit)
    require(stamp(p) == before, 'tiny pinned record changed during admission')
    return value, before


def recipe(shape, rows=127):
    from .native_scale_control import native_recipe
    from .recipe import dimensions
    width, count, size = dimensions(shape, 'native', rows)
    value = native_recipe(shape)
    value.update(width=width, rows=count, bytes=size, tiny=True)
    return value


def reference(plan):
    item = plan['qualification']['scale_plan']
    p = path(item['path'])
    before = stamp(p)
    require(p.stat().st_size <= 4*1024**2 and sha256(p) == digest(item['sha256']),
            'tiny scale-reference bytes mismatch')
    value = read_json(p, 4*1024**2)
    require(stamp(p) == before and not enabled(value), 'tiny reference must be an immutable scale plan')
    return value


def retained_roots(plan, scale):
    """An unstarted Windows scale namespace is an absence, not zero history."""
    absent = plan['qualification'].get('unstarted_scale_roots', [])
    require(isinstance(absent, list) and len(set(absent)) == len(absent), 'exact unstarted-root list required')
    require(not absent or (plan['os'] == 'Windows' and
            set(absent) <= {scale['owned_root'], scale['campaign']}), 'cannot omit retained native history')
    require(all(not os.path.lexists(path(r)) for r in absent), 'unstarted scale namespace appeared')
    return set(scale['owned_roots']) - set(absent)


def validate(plan):
    from .native_scale_control import LIMITS, validate_preparation
    q = plan['qualification']
    require(q['schema'] == SCHEMA and q['input_bytes'] == INPUT_BYTES and q['new_bytes'] in (NEW_BYTES,256*1024**2),
            'fixed tiny allowances required')
    if q['new_bytes'] != NEW_BYTES:
        grant=q['namespace_disk_authority']
        require(plan['os']=='Windows' and set(grant)=={'selection','authority'},'Windows disk-only authority required')
        selection,_=pinned_json(grant['selection'],65536);pinned_json(grant['authority'],65536)
        require(selection['schema']=='chopper-owner-disk-authority-selection-v1' and
            selection['namespace_disk_bytes']==q['new_bytes'] and selection['previous_terminal_upper_bound_bytes']==NEW_BYTES and
            selection['authority']['sha256']==grant['authority']['sha256'],'matching namespace disk authority required')
    metadata_limits(q['metadata_per_process'])
    require(type(q['stop_unix']) in (int, float) and type(q['launch_cutoff_unix']) in (int, float)
            and q['launch_cutoff_unix'] < q['stop_unix'], 'explicit parent absolute clocks required')
    scale = reference(plan)
    validate_preparation(scale)
    for key in ('os', 'host', 'features', 'limits', 'product', 'python', 'tools', 'dependencies',
                'package', 'executable', 'package_receipt', 'build_proof', 'selected639_lineage'):
        require(plan[key] == scale[key], 'tiny must retain selected scale inventory/policy: '+key)
    require(plan['limits'] == LIMITS, 'tiny cannot alter guard bounds')
    require(retained_roots(plan, scale) <= set(plan['owned_roots']), 'tiny must retain complete scale history')
    old_source, source = scale['source_reservation'], plan['source_reservation']
    require(set(old_source['roots']) <= set(source['roots']) and source['bytes'] == old_source['bytes'],
            'tiny must preserve source roots and reservation')
    for key in ('owned_root', 'campaign'):
        fresh = path(plan[key])
        require(all(fresh != path(r) and not fresh.is_relative_to(path(r)) and
                    not path(r).is_relative_to(fresh) for r in scale['owned_roots']),
                'tiny requires fresh separate namespaces')
    namespace = path(q['namespace'])
    require(all(path(plan[k]).is_relative_to(namespace) for k in ('owned_root', 'campaign')) and
            all(namespace != path(r) and not namespace.is_relative_to(path(r)) and
                not path(r).is_relative_to(namespace)
                for r in [*scale['owned_roots'], *old_source['roots']]), 'separate complete tiny namespace required')
    require(plan['peers'] == {}, 'tiny never uses scale peer receipts')
    peers = q.get('peers', {})
    require(peers == {} or (plan['os'] == 'Windows' and set(peers) == {'D', 'G'}), 'tiny native peer domain mismatch')
    for peer in peers.values():
        require(set(peer) == {'report', 'qualification', 'completion', 'campaign_record'}, 'complete tiny peer custody required')
        for item in peer.values():
            digest(item['sha256'])
            require(path(item['path']).is_relative_to(namespace), 'tiny peer imports must count toward namespace ceiling')
    require(plan['reservation']['lock_path'] == scale['reservation']['lock_path'], 'original host lock required')
    require(isinstance(q['original_lock_stat'], list) and len(q['original_lock_stat']) == 6,
            'original lock identity required')
    require(sum(f['bytes'] for f in plan['fixtures'].values()) +
            plan['fixtures']['D']['bytes'] + len(b'broken\n') <= INPUT_BYTES,
            'tiny aggregate generated input ceiling')
    # Caps and Job semantics are unchanged; only dimensions may shrink.
    for shape in ('D', 'G'):
        require(plan['fixtures'][shape] == recipe(shape, plan['fixtures'][shape]['rows']),
                'exact supported tiny recipe required')
    return scale


def namespace_advancement(namespace, baseline, previous_observation, previous_history, completed, original_stat, *, expected_host, pins=None):
    """Advance the existing cumulative snapshot only through closed successful siblings."""
    pins = {} if pins is None else pins
    def read(item,maximum=4*1024**2):
        value,before=pinned_json(item,maximum);pins[path(item['path'])]=before;return value
    old=read(previous_history);point=read(previous_observation)
    require(old['schema']=='native-tiny-namespace-history-v1' and path(old['namespace'])==namespace and
        old['observation']==previous_observation and completed,'exact previous namespace authority required')
    anchor=old['baseline'];anchor_fields={row['path']:row['stat'] for row in anchor['entries']}
    anchor_sum=sum(History._baseline_charges(anchor).values())
    observed=point['unchanged_current_identities']['tiny']
    require(point['component_only'] is True and old['origin_carry_bytes']==point['tiny_origin_carry'] and
        observed['files']==len(anchor_fields) and observed['successful_charge_sum']==anchor_sum and
        observed['digest']==hashlib.sha256(json.dumps(anchor_fields,sort_keys=True).encode()).hexdigest(),
        'previous namespace point/baseline mismatch')
    roots={str(path(row['path'])) for row in anchor['roots']};upper=0
    entries={row['path']:row for row in baseline['entries']}
    require(all(name in entries and entries[name]['stat']==fields for name,fields in anchor_fields.items()),
        'retained namespace identities changed')
    for item in completed:
        require(set(item)=={'path','plan','qualification','completion','independent'},'complete successful sibling proof required')
        root=path(item['path']);prior=read(item['plan']);q=read(item['qualification']);done=read(item['completion']);audit=read(item['independent'])
        require(root.parent==namespace and str(root) not in roots and prior['os']=='Windows' and
            path(prior['qualification']['namespace'])==namespace and prior['qualification']['namespace_history']==previous_history and prior['host']==q['host']==expected_host and
            path(prior['owned_root'])==root/'data' and path(prior['campaign'])==root/'campaign' and
            path(item['qualification']['path'])==root/'data/qualification-result.json' and
            path(item['completion']['path'])==root/'campaign/Windows-tiny-completed.json' and
            q['schema']==SCHEMA and q['passed'] is True and q['evidence_kind']=='native-tiny' and
            q['scale_acceptance'] is False and q['scale_slots_consumed']==0 and q['plan_sha256']==item['plan']['sha256'] and
            q['original_lock']['stat']==original_stat and q['original_lock']['original_descriptor_closed'] is True and
            q['original_lock']['capture_eof_joined'] is True and done['passed'] is True and
            done['plan_sha256']==item['plan']['sha256'] and done['qualification_sha256']==item['qualification']['sha256'] and
            audit['schema']=='native178-full-tiny-after-exit-v1' and audit['qualification_passed'] is True and
            audit['qualification_sha256']==item['qualification']['sha256'] and audit['original_lock_stat']==original_stat and
            audit['administrative_recovery'] is False and audit['independent_probe_released'] is True and
            audit['original_byte_zero_available'] is True and len(audit['phases'])==9 and audit['owned_births'],
            'positive complete successful sibling closure required')
        expected={shape+'-'+stage for shape in ('D','G') for stage in ('generation','Run','verify')}
        expected.update('D-'+stage for stage in ('failure-prepare','failure','failure-verify'))
        require({path(row['directory']).name for row in audit['phases']}==expected and
            all(path(row['directory']).parent==root/'data' and row['empty_owned_job'] is True for row in audit['phases']),
            'complete successful sibling phase identities required')
        roots.add(str(root))
        # Root-level parent receipts/captures, q and completion can close after the last disk sample.
        tail=sum(row['charge_bytes'] for row in baseline['entries'] if Path(row['path']).parent==root or
            Path(row['path']) in (path(item['qualification']['path']),path(item['completion']['path'])))
        require(prior['qualification']['new_bytes'] in (NEW_BYTES,256*1024**2),'known previous aggregate disk ceiling required')
        upper=max(upper,prior['qualification']['new_bytes']+tail)
    require({row['path'] for row in baseline['roots']}==roots,'only retained and proved completed namespace roots required')
    amount=sum(History._baseline_charges(baseline).values())
    origin=max(point['tiny_origin_carry'],upper-amount)
    fields={row['path']:row['stat'] for row in baseline['entries']}
    return dict(schema='native-tiny-namespace-advancement-v1',component_only=True,tiny_origin_carry=origin,
        previous_observation=previous_observation,previous_history=previous_history,completed_namespaces=completed,
        retained_upper_bytes=upper,physical_peak=None,unchanged_current_identities=dict(tiny=dict(files=len(fields),
            successful_charge_sum=amount,sampled_bytes=origin+amount,
            digest=hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest())))


def namespace_retirement_debt(plan, baseline):
    """Carry only missing retired Tiny namespace upper debt into the native pool."""
    q=plan['qualification'];namespace=path(q['namespace']);root=path(plan['owned_root']).parent
    require(q['new_bytes'] in (NEW_BYTES,256*1024**2) and root.is_relative_to(namespace) and
        namespace in {path(row['path']) for row in baseline['roots']},'complete retained Tiny namespace baseline required')
    History._baseline_charges(baseline)
    current=sum(row['charge_bytes'] for row in baseline['entries'] if path(row['path']).is_relative_to(namespace))
    late={root/'data/qualification-result.json',path(plan['campaign'])/'Windows-tiny-completed.json'}
    tail=sum(row['charge_bytes'] for row in baseline['entries'] if path(row['path']).parent==root or path(row['path']) in late)
    return max(0,q['new_bytes']+tail-current)  # Closed ceiling plus known late files; never a measured physical peak.


class History:
    """Reuse original retained debt without adopting or opening its large input."""
    def __init__(self, plan):
        scale = validate(plan)
        self.plan = plan
        self.scale = scale
        self.record = path(plan['qualification']['scale_plan']['path'])
        self.before = stamp(self.record)
        self.namespace_baseline = self.namespace_prior = None
        self.namespace_pins = {}
        for item in plan['qualification'].get('namespace_disk_authority', {}).values():
            _, before = pinned_json(item, 65536)
            self.namespace_pins[path(item['path'])] = before
        if 'namespace_history' in plan['qualification']:
            self._namespace_history(plan)
        if plan['os'] == 'Linux':
            self.original = Lineage(scale)
            self.value, self.baselines = self.original.value, self.original.baselines
        else:
            # Windows needs actual OS-local allocation/carry evidence. A Linux
            # logical length or an empty invented baseline cannot admit it.
            item = plan['qualification'].get('windows_history')
            require(item is not None, 'tiny Windows blocked: OS-local retained allocation/carry descriptor missing')
            p = path(item['path'])
            history, before = pinned_json(item, 64*1024**2)
            require(history['schema'] == 'native-tiny-windows-history-v1' and
                    history['host'] == plan['host'] and history['scale_plan'] == plan['qualification']['scale_plan']
                    and history['provenance'], 'actual Windows history provenance required')
            origin = history['allocation_origin']
            require(origin['kind'] == 'fresh-native-baseline; legacy metrics retained separately' and
                    origin['legacy_records'], 'Windows measurement origin and retained legacy metrics required')
            self.pins = {p: before}
            for pin in [*history['provenance'], *origin['legacy_records']]:
                p = path(pin['path'])
                before = stamp(p)
                require(p.stat().st_size <= 64*1024**2 and sha256(p) == digest(pin['sha256']) and
                        stamp(p) == before, 'Windows history provenance drift')
                self.pins[p] = before
            self.baselines = history['baselines']
            self.allocation_origin = origin
            require(type(history['prior_generation_ms']) is int and history['prior_generation_ms'] >= 0,
                    'retained Windows OS debit required')
            self.value = dict(prior_generation_ms=history['prior_generation_ms'],
                              prior_storage={'Windows': history['prior_storage']})
            if 'retained_windows_d' in history:
                from .native_scale_identity import retained_windows_d
                self.retained_d=retained_windows_d(plan,history['retained_windows_d'],self.pins)
                require(history['prior_generation_ms'] >= self.retained_d['started']['prior_generation_ms'],
                        'retained Windows OS debit cannot refund')
            previous = self._previous_windows_storage(history, plan)
            if previous is not None:
                self.allocation_origin = dict(origin, retained_transition=history['retained_transition'],
                                              retained_carry={})
            latest=None
            if 'latest_source_history' in history:
                latest,before=pinned_json(history['latest_source_history'],64*1024**2)
                self.pins[path(history['latest_source_history']['path'])]=before
                require(latest['schema']=='native-tiny-windows-history-v1' and latest['host']==plan['host'],
                        'latest source history host/schema mismatch')
            for pool, roots in (('native', retained_roots(plan, scale)), ('source', scale['source_reservation']['roots'])):
                require({r['path'] for r in self.baselines[pool]['roots']} == set(roots),
                        'complete Windows retained roots required')
                prior = self.value['prior_storage']['Windows'][pool]
                require(all(type(prior[k]) is int and prior[k] >= 0 for k in
                        ('sum_bytes', 'entry_count', 'carry_bytes', 'prior_sampled_aggregate_highwater_bytes')),
                        'actual Windows baseline counters required')
                if previous is None:
                    require(prior['carry_bytes'] == prior['sum_bytes'] ==
                            prior['prior_sampled_aggregate_highwater_bytes'] >= 0,
                            'Windows current measurement-origin carry required; no invented historical allocation')
                else:
                    old, receipt = previous
                    old_baseline = old['baselines'][pool]
                    expected_roots={r['path'] for r in old_baseline['roots']}
                    if hasattr(self,'retained_d'):
                        from .native_scale_identity import windows_root_union
                        expected_roots=set(windows_root_union(expected_roots,self.retained_d['plan']['owned_roots']
                            if pool=='native' else self.retained_d['plan']['source_reservation']['roots']))
                    require(expected_roots == {r['path'] for r in self.baselines[pool]['roots']},
                            'retained transition roots changed')
                    old_charges = self._baseline_charges(old_baseline)
                    current = self._baseline_charges(self.baselines[pool])
                    old_prior = old['prior_storage'][pool]
                    require(all(type(old_prior[k]) is int and old_prior[k] >= 0 for k in
                                ('sum_bytes', 'entry_count', 'carry_bytes', 'prior_sampled_aggregate_highwater_bytes')),
                            'previous admitted counters invalid')
                    require(old_prior['sum_bytes'] == sum(old_charges.values()) and
                            old_prior['entry_count'] == len(old_charges) and
                            old_prior['carry_bytes'] == old_prior['prior_sampled_aggregate_highwater_bytes'] >=
                            old_prior['sum_bytes'], 'previous admitted carry mismatch')
                    admitted = receipt['preparation_storage'][pool]
                    require(admitted['current_origin_bytes'] == old_prior['sum_bytes'] and
                            admitted.get('sampled_highwater_carry_bytes', admitted['current_origin_bytes']) ==
                            old_prior['carry_bytes'], 'previous preflight allocation/carry mismatch')
                    growth = sum(max(0, amount-old_charges.get(key, 0)) for key, amount in current.items())
                    previous_plan=None
                    if hasattr(self,'retained_d'):
                        previous_plan,_=pinned_json(history['retained_transition']['previous_plan'],4*1024**2)
                    carry=self.transition_carry(old_prior,old_baseline,self.baselines[pool],
                        retained=getattr(self,'retained_d',None),pool=pool,previous_plan=previous_plan,
                        latest_source=latest if pool=='source' else None)
                    require(prior['sum_bytes'] == sum(current.values()) and prior['entry_count'] == len(current) and
                            prior['carry_bytes'] == prior['prior_sampled_aggregate_highwater_bytes'] == carry,
                            'retained transition cannot refund sampled allocation')
                    self.allocation_origin['retained_carry'][pool] = dict(
                        previous_carry_bytes=old_prior['carry_bytes'], new_identity_or_growth_bytes=growth,
                        retired_identity_bytes=sum(amount for key, amount in old_charges.items() if key not in current),
                        current_baseline_bytes=prior['sum_bytes'], carry_bytes=carry)
        self.check()

    @staticmethod
    def transition_carry(old_prior, before, current, *, retained=None, pool=None, previous_plan=None, latest_source=None):
        old=History._baseline_charges(before);new=History._baseline_charges(current)
        carry=old_prior['carry_bytes']+sum(max(0,amount-old.get(key,0)) for key,amount in new.items())
        if retained:
            if pool=='native':carry+=namespace_retirement_debt(previous_plan,current)
            carry=max(carry,retained['floors'][pool])
        if latest_source is not None:
            require(pool=='source' and latest_source['schema']=='native-tiny-windows-history-v1',
                    'latest history applies only to the source pool')
            baseline=latest_source['baselines']['source'];prior=latest_source['prior_storage']['source']
            latest=History._baseline_charges(baseline)
            require(all(type(prior[k])is int and prior[k]>=0 for k in
                ('sum_bytes','entry_count','carry_bytes','prior_sampled_aggregate_highwater_bytes')) and
                prior['sum_bytes']==sum(latest.values()) and prior['entry_count']==len(latest) and
                prior['carry_bytes']==prior['prior_sampled_aggregate_highwater_bytes']>=prior['sum_bytes'] and
                {row['path']for row in baseline['roots']}<={row['path']for row in current['roots']},
                'latest source baseline/counters/root coverage invalid')
            carry=max(carry,prior['carry_bytes']+sum(max(0,amount-latest.get(key,0))for key,amount in new.items()))
        return carry

    @staticmethod
    def _baseline_charges(baseline):
        charges = {(str(Path(item['path'])), item['stat']['dev'], item['stat']['ino']): item['charge_bytes']
                   for item in baseline['entries']}
        require(len(charges) == len(baseline['entries']) and
                all(type(amount) is int and amount >= 0 for amount in charges.values()) and
                sum(charges.values()) == baseline['sum_bytes'], 'retained transition baseline charges invalid')
        return charges

    def _namespace_history(self, plan):
        """Retain a nonempty old namespace baseline; new siblings are growth."""
        q = plan['qualification']
        item = q['namespace_history']
        value, before = pinned_json(item, 4*1024**2)
        self.namespace_pins[path(item['path'])] = before
        require(plan['os'] == 'Windows' and value['schema'] == 'native-tiny-namespace-history-v1' and
                path(value['namespace']) == path(q['namespace']), 'namespace history mismatch')
        point, before = pinned_json(value['observation'], 4*1024**2)
        self.namespace_pins[path(value['observation']['path'])] = before
        if point.get('schema')=='native-tiny-namespace-advancement-v1':
            expected=namespace_advancement(path(q['namespace']),value['baseline'],point['previous_observation'],
                point['previous_history'],point['completed_namespaces'],q['original_lock_stat'],expected_host=plan['host'],pins=self.namespace_pins)
            require(point==expected and value.get('completed_namespaces')==point['completed_namespaces'] and
                all(value.get(key)==point[key] for key in ('previous_observation','previous_history')),
                'completed namespace advancement mismatch')
        baseline, prior = value['baseline'], value['prior_storage']
        charges = self._baseline_charges(baseline)
        fields = {item['path']:item['stat'] for item in baseline['entries']}
        observed = point['unchanged_current_identities']['tiny']
        require(point['component_only'] is True and type(value['origin_carry_bytes']) is int and
                value['origin_carry_bytes'] >= 0 and
                value['origin_carry_bytes'] == point['tiny_origin_carry'] and
                {key:observed[key] for key in ('files','successful_charge_sum','digest')} ==
                    dict(files=len(fields),successful_charge_sum=sum(charges.values()),
                         digest=hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()) and
                observed['sampled_bytes'] == value['origin_carry_bytes']+baseline['sum_bytes'] and
                prior == dict(sum_bytes=baseline['sum_bytes'],entry_count=len(charges),
                    carry_bytes=value['origin_carry_bytes']+baseline['sum_bytes'],
                    prior_sampled_aggregate_highwater_bytes=value['origin_carry_bytes']+baseline['sum_bytes']),
                'namespace history point/carry mismatch')
        roots = [path(root['path']) for root in baseline['roots']]
        require(roots and len(set(roots)) == len(roots) and
                all(root.parent == path(q['namespace']) for root in roots) and
                all(any(path(name).is_relative_to(root) for root in roots) for name in fields),
                'namespace history must seal retained direct children')
        require(all(not path(plan[key]).is_relative_to(root) for root in roots for key in ('owned_root','campaign')),
                'namespace history overlaps fresh session')
        self.namespace_baseline, self.namespace_prior = baseline, prior

    @staticmethod
    def _same_scale_policy(previous, current):
        from .native_scale_control import LIMITS
        legacy = dict(LIMITS, sample_seconds=1, stale_seconds=5)
        legacy.pop('disk_observation_seconds')
        timing = previous['limits'] == current['limits'] or (
            previous['limits'] == legacy and current['limits'] == LIMITS)
        refresh = {'dependencies', 'environment_sha256', 'limits', 'tools'}
        same_tools = (len(previous['tools']) == len(current['tools']) and
            {item['path']:{k:v for k,v in item.items() if k != 'sha256'} for item in previous['tools']} ==
            {item['path']:{k:v for k,v in item.items() if k != 'sha256'} for item in current['tools']})
        return not enabled(previous) and timing and same_tools and (
            {k:v for k,v in previous.items() if k not in refresh} ==
            {k:v for k,v in current.items() if k not in refresh})

    def _previous_windows_storage(self, history, plan):
        transition = history.get('retained_transition')
        if transition is None:
            return None
        require(set(transition) == {'schema', 'previous_plan', 'previous_preflight'} and
                transition['schema'] == 'native-tiny-retained-transition-v1', 'retained transition proof required')
        item = transition['previous_plan']
        previous_plan, before = pinned_json(item, 8*1024**2)
        self.pins[path(item['path'])] = before
        require(previous_plan['os'] == 'Windows' and previous_plan['host'] == plan['host'],
                'previous retained Windows plan mismatch')
        previous_reference = previous_plan['qualification']['scale_plan']
        previous_scale, before = pinned_json(previous_reference, 4*1024**2)
        self.pins[path(previous_reference['path'])] = before
        if hasattr(self,'retained_d'):
            from .native_scale_identity import windows_root_union
            previous_scale=dict(previous_scale,owned_roots=windows_root_union(
                previous_scale['owned_roots'],self.retained_d['plan']['owned_roots']),
                source_reservation=dict(previous_scale['source_reservation'],roots=windows_root_union(
                    previous_scale['source_reservation']['roots'],self.retained_d['plan']['source_reservation']['roots'])))
        require(self._same_scale_policy(previous_scale, self.scale),
                'retained transition scale policy changed')
        item = previous_plan['qualification']['windows_history']
        previous, before = pinned_json(item, 64*1024**2)
        self.pins[path(item['path'])] = before
        require(previous['schema'] == 'native-tiny-windows-history-v1' and previous['host'] == plan['host'] and
                previous['scale_plan'] == previous_reference and
                previous['prior_generation_ms'] <= history['prior_generation_ms'], 'previous retained history mismatch')
        item = transition['previous_preflight']
        receipt_path = path(item['path'])
        records = (receipt_path, receipt_path.parent/'worker-result.json',
                   receipt_path.parent/'runner/status.json', receipt_path.parent/'preparation-plan.json')
        before = {p: stamp(p) for p in records}
        receipt = preflight(path(transition['previous_plan']['path']), previous_plan, receipt_path, item['sha256'])
        require(read_json(records[1])['preparation_storage'] == receipt['preparation_storage'],
                'previous preflight allocation/carry mismatch')
        require(all(stamp(p) == value for p, value in before.items()), 'previous preflight custody drift')
        self.pins.update(before)
        return previous, receipt

    def check(self):
        retained_roots(self.plan, self.scale)
        require(stamp(self.record) == self.before, 'tiny scale reference drift')
        if hasattr(self, 'original'):
            self.original.check()
        else:
            require(all(stamp(p) == s for p, s in self.pins.items()), 'Windows retained history drift')
        require(all(stamp(p) == s for p,s in self.namespace_pins.items()), 'retained namespace history drift')


def peer_pins(plan):
    return [pin for peer in plan['qualification'].get('peers', {}).values() for pin in peer.values()]


def peer_report(plan, shape, actual_sha=None):
    """Tiny Windows parity requires a clean tiny Linux seal, never scale output."""
    if plan['os'] != 'Windows':
        return None
    peers = plan['qualification'].get('peers', {})
    require(set(peers) == {'D', 'G'}, 'tiny Windows blocked: clean same-size Linux tiny peers required')
    item = peers[shape]
    require(set(item) == {'report', 'qualification', 'completion', 'campaign_record'}, 'complete tiny peer custody required')
    def pinned(key):
        return pinned_json(item[key], 8*1024**2)[0]
    envelope, qualified, completed, committed = (pinned(k) for k in
        ('report', 'qualification', 'completion', 'campaign_record'))
    require(qualified['schema'] == SCHEMA and qualified['passed'] is True and qualified['os'] == 'Linux'
            and qualified['scale_acceptance'] is False and qualified['scale_slots_consumed'] == 0
            and qualified['original_lock']['original_descriptor_closed'] is True
            and qualified['original_lock']['original_owner_lock_absent'] is True,
            'clean released Linux tiny qualification required')
    require(completed['passed'] is True and completed['evidence_kind'] == 'native-tiny'
            and completed['qualification_sha256'] == item['qualification']['sha256']
            and completed['plan_sha256'] == qualified['plan_sha256'], 'final Linux tiny completion required')
    require(envelope['os'] == envelope['host']['os'] == 'Linux' and envelope['passed'] is True
            and envelope['evidence_kind'] == 'native-tiny' and envelope['slot'] == 'Linux'+shape
            and envelope['product'] == plan['product']['commit']
            and envelope['plan_sha256'] == qualified['plan_sha256'] == committed['plan_sha256']
            and committed['passed'] is True and committed['evidence_kind'] == 'native-tiny'
            and committed['sha256'] == item['report']['sha256'], 'tiny Linux report/campaign custody mismatch')
    report = envelope['report']
    require(report['shape'] == shape and report['rows'] == plan['fixtures'][shape]['rows']
            and (actual_sha is None or report['source_sha256'] == actual_sha), 'tiny peer size/source mismatch')
    return report


def preflight(plan_path, plan, receipt_path, exact_sha):
    """Match the complete maintained #177 result, not an operator's pass label."""
    receipt_path = path(str(receipt_path))
    result, _ = pinned_json(dict(path=str(receipt_path), sha256=exact_sha), 16*1024**2)
    require(result['schema'] == 'chopper-acceptance-preflight-v1' and result['status'] == 'passed'
            and result['profile'] == 'native' and result['plan_sha256'] == sha256(plan_path)
            and result['workload_started'] is False and result['scale_slot_consumed'] is False,
            'matching native preflight pass required')
    worker = receipt_path.parent/'worker-result.json'
    require(sha256(worker) == result['worker_receipt_sha256'], 'preflight worker custody mismatch')
    status = read_json(receipt_path.parent/'runner/status.json', 16*1024**2)
    require(status['summary'] == dict(passed=1, incomplete=0) and len(status['attempts']) == 1 and
            status['attempts'][0]['status'] == 'passed' and status['attempts'][0]['exit_code'] == 0,
            'terminal maintained preflight runner pass required')
    preparation = read_json(receipt_path.parent/'preparation-plan.json')
    root = Path(preparation['root'])
    attempt = status['attempts'][0]
    from .native_scale_host import module
    runner = module('validation-runner')
    require(runner.identity_record(root, attempt['inputs'], plan_path)['sha256'] == sha256(plan_path) and
            runner.identity_record(root, attempt['artifacts'], worker)['sha256'] == result['worker_receipt_sha256'],
            'preflight runner plan/artifact custody mismatch')
    require(all(result['host'][k] == plan['host'][k] for k in result['host']), 'preflight actual host mismatch')
    checker = result['checker']
    require(checker['files'] and checker['files'].get(checker['path']) == checker['sha256'],
            'complete preflight checker map required')
    root = path(checker['path']).parent
    require(any(root.is_relative_to(path(r)) for r in plan['source_reservation']['roots']),
            'preflight checker source reservation missing')
    require(receipt_path.is_relative_to(path((plan['qualification'] if enabled(plan) else plan['windows_execution'])['namespace'])),
            'tiny preflight evidence must count toward new namespace ceiling')
    for name, expected_sha in checker['files'].items():
        require(sha256(path(name)) == digest(expected_sha), 'preflight checker byte drift')
    require(checker['sha256'] == plan['harness']['sha256']['scripts/acceptance-preflight.py'],
            'preflight checker is not the selected harness')
    # Use the pinned producer's own inventory, including its helper packages;
    # a current partial list cannot validate historical or newly extended roots.
    from .native_scale_host import module
    producer = module('acceptance-preflight', scripts=root)
    require(set(map(str, producer.checker_sources())) == set(checker['files']),
            'preflight checker inventory drift')
    bindings = result['bindings']
    require(bindings['product'] == plan['product']['commit'] and bindings['harness'] == plan['harness']['commit']
            and bindings['harness_tree'] == plan['harness']['tree'] and bindings['host'] == plan['host'],
            'preflight selected native bindings mismatch')
    if plan.get('execution_kind') == 'batch':
        from .hosted_qualification import batch_admission
        batch_admission(plan,'native')
    return result


def launch_check(plan):
    require(time.time() < plan['qualification']['launch_cutoff_unix'], 'parent tiny launch cutoff expired')


def check_clock(plan):
    require(time.time() < plan['qualification']['stop_unix'], 'parent tiny absolute stop expired')


class ReadBudget:
    """Conservative Python file-open charges, not physical I/O or an RSS cap.

    One supervisor, nine caretakers/workers and six phase children: at most 25
    metered controller processes. Product invocations read only tiny fixtures.
    The maintained Linux operator has a separate meter using the selected
    per-process limits; include it separately in the batch's remaining budget.
    Imports before main are charged once from their loaded module paths.
    """
    def __init__(self, plan, plan_path):
        self.read_bytes, self.visits, self.failed = 0, 0, False
        self.local, self.mutex = threading.local(), threading.RLock()
        self.limits = plan['qualification']['metadata_per_process']
        metadata_limits(self.limits)
        paths = {Path(m.__file__).resolve() for m in tuple(sys.modules.values())
                 if getattr(m, '__file__', None) and Path(m.__file__).is_file()}
        paths.add(plan_path)
        self.read_bytes = sum(p.stat().st_size for p in paths)
        self.visits = 2*len(paths)
        self.check()
        sys.addaudithook(self.audit)

    def check(self):
        if self.failed or self.read_bytes > self.limits['read_bytes'] or self.visits > self.limits['visits']:
            self.failed = True
            raise ValueError('tiny metadata/tool-input allowance exceeded')

    def audit(self, event, args):
        if getattr(self.local, 'busy', False) or self.failed or event not in ('open', 'os.scandir', 'os.listdir'):
            return
        with self.mutex:
            self.local.busy = True
            try:
                if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
                    if not args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                        p = Path(os.fsdecode(args[0]))
                        s = p.stat()
                        self.visits += 1
                        if stat.S_ISREG(s.st_mode):
                            self.read_bytes += s.st_size
                elif event in ('os.scandir', 'os.listdir'):
                    self.visits += 2*(len(os.listdir(args[0]))+1)
                self.check()
            finally:
                self.local.busy = False


class PublicationWatch:
    """Sample first public-directory visibility through closed runner captures."""
    def __init__(self, data):
        import threading
        self.data, self.error, self.observed = data, None, False
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.observe, daemon=True)

    def sample(self):
        folder = self.data/'output'
        if self.observed or not folder.exists():
            return
        # The first visible public directory must already contain the complete
        # native manifest and every listed CSV. Final streaming checks follow.
        import json
        manifest = folder/'manifest.jsonl'
        records = [json.loads(line) for line in manifest.read_bytes().splitlines()]
        require(records and records[0]['type'] == 'job', 'partial native publication: missing job')
        outputs = records[1:]
        require(all(r['type'] == 'output' for r in outputs) and
                sum(r['rows'] for r in outputs) == read_json(self.data/'fixture.json')['rows'] and
                {p.name for p in folder.iterdir()} == {'manifest.jsonl', *(r['path'] for r in outputs)} and
                all((folder/r['path']).stat().st_size == r['csv_bytes'] for r in outputs),
                'partial native public directory observed')
        self.observed = True

    def observe(self):
        try:
            while not self.stopped.wait(.001):
                self.sample()
        except BaseException as error:
            self.error = error

    def start(self):
        require(not (self.data/'output').exists(), 'tiny public destination must begin absent')
        self.thread.start()

    def finish(self):
        self.stopped.set()
        self.thread.join(timeout=2)
        require(not self.thread.is_alive(), 'publication observer did not join')
        if self.error:
            raise self.error
        self.sample()
        require(self.observed, 'no complete native publication observed')


def prepare_failure(plan, data):
    from .generate import prepare
    from .native_scale_fixture import checkpoint
    from .native_scale_control import create
    prepare(data, 'D', 'native', plan['fixtures']['D']['rows'])
    checked = checkpoint(data/'job.json', data/'fixture.json', plan['fixtures']['D'])
    with (data/'input.csv').open('ab') as stream:
        stream.write(b'broken\n')
    create(data/'failure.json', dict(valid_prefix=checked, malformed_suffix='broken\n',
           input_sha256=sha256(data/'input.csv'), bytes=(data/'input.csv').stat().st_size))


def failure_payload(plan, data):
    from .native_scale_control import LIMITS
    return dict(data=str(data), shape='D', recipe=plan['fixtures']['D'], limits=LIMITS,
        actual={str(data/n): dict(stat=stamp(data/n), sha256=sha256(data/n))
                for n in ('input.csv', 'job.json', 'fixture.json', 'failure.json')})


def failure_binding(plan, operation):
    from .native_scale_control import approved
    require(enabled(plan) and operation['shape'] == 'D' and
            operation['stage'] in ('failure', 'failure-verify'), 'explicit tiny failure journey required')
    data = path(operation['data'])
    require(data == path(plan['owned_root'])/'failure-data', 'fixed tiny failure directory required')
    require(sha256(operation['proposal']) == operation['proposal_sha256'] and
            approved(operation['proposal'], operation['approval']), 'exact tiny failure approval required')
    value = read_json(operation['proposal'], 64*1024**2)
    require(value == dict(schema='native-scale-proposal-v1', stage='failure',
            plan_sha256=operation['plan_sha256'], payload=failure_payload(plan, data)),
            'tiny failure proposal/input drift')


def expected_failure(plan, operation, batch, runner_root):
    """Prove the real parser consumed the valid prefix, not a setup denial."""
    data = Path(operation['data'])
    failure_binding(plan, operation)
    status = read_json(batch/'status.json', 8*1024**2)
    require(len(status['attempts']) == 1 and status['summary'] == dict(passed=0, incomplete=1),
            'one retained failed runner attempt required')
    attempt = status['attempts'][0]
    require(attempt['status'] == 'failed' and type(attempt['exit_code']) is int and attempt['exit_code'] > 0
            and attempt['argv'] == [plan['executable']['path'], 'run', '--config', str(data/'job.json'), '--yes']
            and attempt['runtime']['executable_sha256'] == plan['executable']['sha256'],
            'actual malformed product invocation required')
    for name in ('input.csv', 'job.json', 'fixture.json', 'failure.json'):
        key = str((data/name).relative_to(runner_root))
        require(attempt['inputs'][key]['sha256'] == sha256(data/name), 'malformed runner input binding mismatch')
    config, meta = read_json(data/'job.json'), read_json(data/'fixture.json')
    from .native_scale_fixture import validate_metadata
    from .verify import expected_header, inspect_row
    validate_metadata(data/'job.json', data/'fixture.json', plan['fixtures']['D'])
    with (data/'input.csv').open('rb') as stream:
        require(stream.readline() == expected_header(meta['width']), 'malformed prefix header')
        for index in range(meta['rows']):
            require(inspect_row(stream.readline(meta['width']+1), meta['width'], meta['rows']) == index,
                    'malformed prefix row')
        require(stream.read() == b'broken\n', 'exact malformed suffix required')
    text = (batch/'1-stderr.log').read_text()
    # Native CsvIntake numbers the header too; the malformed suffix follows
    # every valid row. Match its actual diagnostic, never just a nonzero exit.
    require('chopper: CSV record '+str(meta['rows']+2)+' has 1 fields, expected 3' in text.splitlines(),
            'expected actual-work CSV parse failure/location missing')
    require(not Path(config['output']).exists() and not any((data/'temp').iterdir()),
            'malformed Run published output or leaked temp')
    require({p.name for p in data.iterdir()} == {'input.csv', 'job.json', 'fixture.json', 'failure.json', 'temp'},
            'malformed Run staging/extra siblings remain')
    return dict(product_exit_code=attempt['exit_code'], expected_parse_failure=True,
                valid_rows_consumed=meta['rows'], output_absent=True, staging_absent=True, temp_empty=True)


def verify_failure(plan, operation):
    from .native_scale_control import create
    batch = path(operation['failed_batch'])
    execution = read_json(batch.parent/'runner-plan.json', 8*1024**2)
    result = expected_failure(plan, operation, batch, Path(execution['root']))
    from .verify import verify
    # The failed attempt must leave both earlier complete exports intact.
    for shape in ('D', 'G'):
        data = path(plan['owned_root'])/(shape+'-data')
        before = read_json(path(plan['owned_root'])/(shape+'-verified.json'), 8*1024**2)
        require(verify(data/'job.json', data/'fixture.json', bitmap_dir=data/'temp') == before['report'],
                'malformed journey changed completed native export')
    create(operation['report'], result)


def complete_snapshot_absence(kernel, pid, deadline):
    """A complete TH32CS_SNAPPROCESS snapshot proves active PID absence."""
    import ctypes as C
    from ctypes import wintypes as W
    class Entry(C.Structure):
        _fields_=[('size',W.DWORD),('usage',W.DWORD),('pid',W.DWORD),('heap',C.c_size_t),
            ('module',W.DWORD),('threads',W.DWORD),('parent',W.DWORD),('priority',W.LONG),
            ('flags',W.DWORD),('exe',W.WCHAR*260)]
    kernel.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD]
    kernel.CreateToolhelp32Snapshot.restype=W.HANDLE
    for name in ('Process32FirstW','Process32NextW'):
        getattr(kernel,name).argtypes=[W.HANDLE,C.POINTER(Entry)]
        getattr(kernel,name).restype=W.BOOL
    require(time.monotonic()<deadline,'process snapshot deadline')
    C.set_last_error(0)
    handle=kernel.CreateToolhelp32Snapshot(2,0)
    require(handle not in (None,C.c_void_p(-1).value),'process snapshot create failed')
    pids=set()
    try:
        row=Entry();row.size=C.sizeof(row)
        C.set_last_error(0);more=kernel.Process32FirstW(handle,C.byref(row));error=C.get_last_error()
        while more:
            require(time.monotonic()<deadline and len(pids)<65536,'process snapshot bound')
            require(row.pid not in pids,'process snapshot duplicate PID')
            pids.add(row.pid)
            C.set_last_error(0);more=kernel.Process32NextW(handle,C.byref(row));error=C.get_last_error()
        require(time.monotonic()<deadline and error==18 and os.getpid()in pids,'complete process snapshot/canary required')
        require(pid not in pids,'unobserved PID present in active process snapshot')
    finally:
        require(kernel.CloseHandle(handle),'process snapshot close failed')
    require(time.monotonic()<deadline,'process snapshot close deadline')
    return dict(method='complete TH32CS_SNAPPROCESS absence',target_pid=pid,rows=len(pids),
        observer_canary=os.getpid(),termination_winerror=error,snapshot_handle_closed=True)


def unobserved_birth_exit(kernel, windows, pid, *, deadline):
    """Keep unknown-birth audit denials explicit; no arbitrary reuse allowance."""
    import ctypes as C
    access = 0x101000
    C.set_last_error(0)
    handle = kernel.OpenProcess(access,False,pid)
    if not handle:
        code = C.get_last_error()
        if code != 87:
            error = OSError(code,f'unobserved birth PID absence unproved: OpenProcess pid={pid} access={access:#x} winerror={code}')
            error.api,error.pid,error.requested_access,error.winerror = 'OpenProcess',pid,access,code
            if code==5:
                try:
                    absence=complete_snapshot_absence(kernel,pid,deadline)
                except BaseException as denied:
                    error.add_note('Complete process snapshot rejected: '+str(denied)[:1024])
                    raise error from denied
                return dict(pid=pid,birth_unknown=True,absent=True,open_api='OpenProcess',
                    requested_access=access,open_winerror=code,independent_absence=absence)
            raise error
        return dict(pid=pid,birth_unknown=True,absent=True,error=code)
    try:
        state = kernel.WaitForSingleObject(handle,0)
        require(state==0,f'unobserved birth still live or reused; cannot infer: pid={pid} wait0={state}')
        return dict(pid=pid,birth_unknown=True,signaled=True,absent=True)
    finally:windows.checked(kernel.CloseHandle(handle))


def linux_after_exit(root, exact_plan_sha, *, verifier_sha256=None):
    """The qualified Q8 kernel/cgroup proof, through the maintained command."""
    require(sys.platform.startswith('linux'), 'actual Linux audit required')
    started = time.monotonic()
    root = Path(root)
    require(not (root/'operator-failure.json').exists(), 'failed operator cannot qualify complete Linux Tiny')
    plan = read_json(root/'tiny-plan.json', 4*1024**2)
    require(sha256(root/'tiny-plan.json') == exact_plan_sha, 'audit plan pin drift')
    verifier = Path(__file__).resolve()
    expected = verifier_sha256 or plan['harness']['sha256']['scripts/scale_acceptance/native_tiny.py']
    require(sha256(verifier) == digest(expected), 'independent verifier code pin drift')
    qfile = Path(plan['owned_root'])/'qualification-result.json'
    q = read_json(qfile)
    completion_file = Path(plan['campaign'])/'Linux-tiny-completed.json'
    completion = read_json(completion_file)
    require(read_json(root/'qualify-exit.json')['code'] == 0 and q['passed'] is True and
            q['plan_sha256'] == exact_plan_sha and q['scale_acceptance'] is False and
            q['scale_slots_consumed'] == 0 and completion['passed'] is True and
            completion == dict(passed=True,evidence_kind='native-tiny',scale_acceptance=False,scale_slots_consumed=0,
                plan_sha256=exact_plan_sha,qualification_sha256=sha256(qfile)),
            'clean Linux qualification/completion custody missing')
    original = q['original_lock']
    require(original['original_descriptor_closed'] is True and original['original_owner_lock_absent'] is True,
            'original Linux descriptor/kernel release receipt missing')
    lock = Path(original['path'])
    actual = stamp(lock)
    require(actual == original['stat'] == plan['qualification']['original_lock_stat'], 'original lock file replaced')
    device = f'{os.major(actual[0]):02x}:{os.minor(actual[0]):02x}:{actual[1]}'
    pids = {original['owner_pid'],read_json(root/'controller-pid.json')['pid']}
    phases = []
    expected_phases = {shape+'-'+stage for shape in ('D','G') for stage in ('generation','Run','verify')}
    expected_phases.update('D-'+stage for stage in ('failure-prepare','failure','failure-verify'))
    containments = sorted(Path(plan['owned_root']).glob('*/containment.json'))
    require({item.parent.name for item in containments} == expected_phases,
            'complete exact nine-phase Linux roles required')
    for containment in containments:
        require(time.monotonic()-started < 30 and len(phases) < 9, 'bounded nine-phase Linux audit required')
        directory = containment.parent
        c = read_json(containment)
        pids.add(c['worker_pid'])
        pids.add(read_json(directory/'supervisor-ready.json')['caretaker_pid'])
        cleanup = read_json(directory/'cleanup.json')
        require(all(cleanup[key] is True for key in ('controller_eof','monitor_threads_joined','capture_writers_reaped'))
                and all(cleanup[key] == [] for key in ('remaining','cleanup_errors','errors')),
                'phase Linux cleanup incomplete: '+str(directory))
        cg = Path(c['cgroup'])
        if cg.exists():
            cs = cg.stat()
            require([cs.st_dev,cs.st_ino] == c['cgroup_identity'], 'cgroup replaced')
            members = {}
            from itertools import chain
            for path in chain((cg/'cgroup.procs',), cg.glob('**/cgroup.procs')):
                require(time.monotonic()-started < 30 and len(members) < 128, 'bounded cgroup census required')
                members[str(path)] = path.read_text()
            require(all(not value.strip() for value in members.values()), 'owned cgroup/descendant not empty')
            state = dict(path=str(cg),same_identity=True,members=members)
        else:
            state = dict(path=str(cg),absent=True)
        phases.append(dict(directory=str(directory),cleanup_sha256=sha256(directory/'cleanup.json'),cgroup=state))
    require(len(phases) == 9, 'complete nine-phase Linux cleanup evidence required')
    absent = {str(pid):not Path('/proc',str(pid)).exists() for pid in sorted(pids)}
    require(all(absent.values()), 'owned PID exists; investigate identity, never kill by name')
    matches = [line for line in Path('/proc/locks').read_text().splitlines() if device in line.split()]
    require(not matches, 'original inode still has kernel locks')
    require(stamp(lock) == actual and time.monotonic()-started < 30, 'final Linux lock identity/deadline')
    result = dict(schema='native178-q3-after-exit-proof-v1', qualification_sha256=sha256(qfile),
        completion_sha256=sha256(completion_file), original_lock_stat=actual,
        original_owner_lock_absent=True, other_locks_on_original_inode=matches,
        owned_pid_absent=absent, phases=phases,
        verifier_role=dict(path=str(verifier),sha256=sha256(verifier),separately_pinned=verifier_sha256 is not None))
    from .native_scale_control import create
    create(root/'after-exit-proof.json', result)
    print(json.dumps(dict(after_exit_sha256=sha256(root/'after-exit-proof.json'),qualification_passed=True)),flush=True)
    return 0


def after_exit(root, exact_plan_sha, *, verifier_sha256=None):
    """Independent full Tiny audit, after operator EOF/reap; never stops an actor."""
    if os.name != 'nt':
        return linux_after_exit(root, exact_plan_sha, verifier_sha256=verifier_sha256)
    import ctypes as C
    from .native_scale_identity import execution_shapes
    import time
    need, read, sha = require, read_json, sha256
    started=time.monotonic()
    require(os.name=='nt', 'native Windows audit required')
    root=Path(root);large=(root/'scale-plan.json').exists()
    plan_file=root/('scale-plan.json' if large else 'tiny-plan.json')
    plan=read(plan_file);qfile=Path(plan['owned_root'])/('scale-result.json' if large else 'qualification-result.json')
    execution=plan['windows_execution'] if large else plan['qualification']
    need(not (root/'operator-failure.json').exists(),'failed operator cannot establish acceptance')
    setup_only = not qfile.exists()
    closed_keeper = None
    if setup_only:
        failure = read(root/'controller-startup-failure.json')
        proof = failure['no_start_closed']
        need(failure['qualification'] is False and proof['handles_closed'] is True and proof['job']['pids'] == [],
             'positive startup tree closure required')
        if proof.get('no_ack') is True:
            need(failure['ack_delivery_started'] is False, 'ACK delivery uncertainty remains')
        elif proof.get('closed_keeper') is not None:
            record = proof['closed_keeper']
            closed_keeper = record['no_worker_owner_closed']
            need(record['native_preparation_failed'] == 'HostLock' and record['pending_calls'] is False and
                 closed_keeper['schema'] == 'native-windows-owner-closed-start-v1' and
                 all(closed_keeper.get(key) is True for key in ('keeper_reaped','capture_eof_joined',
                     'captures_closed','process_handle_closed','original_closed_after_keeper_reap')) and
                 closed_keeper['caretaker_requests'] == 0, 'positive no-worker keeper closure required')
        else:
            need(proof['original_never_acquired'] is True and
                 proof['prelock_failure']['native_preparation_failed'] in {
                     'selected plan read','metadata budget','qualification mode','plan stat','plan hash',
                     'plan read','plan validation','preflight custody','original lock stat','retained history','root absence'},
                 'positive prelock failure scope required')
        need(read(root/'qualify-exit.json')['code'] == proof['code'], 'startup exit mismatch')
        original = dict(path=plan['reservation']['lock_path'], stat=execution['original_lock_stat'],
                        original_descriptor_closed=True, capture_eof_joined=True)
        q = dict(passed=False, plan_sha256=exact_plan_sha, scale_acceptance=False, scale_slots_consumed=0)
    else:
        q=read(qfile);original=q['original_lock']
    if not setup_only:
        need(read(root/'qualify-exit.json')['code']==int(not q['passed']),'controller terminal mismatch')
    need(original['original_descriptor_closed'] and original['capture_eof_joined'],'original release/EOF missing')
    need(q['plan_sha256']==sha(plan_file) and (not q['passed'] or
        (q['scale_acceptance'] is large and q['scale_slots_consumed']==(len(execution_shapes(plan)) if large else 0))), 'exact native acceptance scope')
    require(sha(plan_file) == exact_plan_sha, 'audit plan pin drift')
    scripts=Path(plan['harness']['root'])/'scripts'
    verifier=Path(__file__).resolve()
    if verifier_sha256 is None:
        require(verifier.parent == scripts/'scale_acceptance', 'audit selected harness required')
    else:
        require(sha(verifier)==digest(verifier_sha256),'independent verifier code pin drift')
    for name in ('native-scale-runner.py','browser-small-windows.py','test-native-file-allocation.py',
                 'scale_acceptance/native_tiny.py','scale_acceptance/native_scale_identity.py'):
        require(sha(scripts/name)==plan['harness']['sha256']['scripts/'+name], 'audit source drift')
    from scale_acceptance.native_scale_host import module
    from scale_acceptance.native_scale_identity import stamp
    controls=module('test-native-file-allocation');windows=module('browser-small-windows');kernel=windows.kernel()
    births={}
    def known(value):
        if value is not None:births[(value['pid'],value['created'])]=value
    known(read(root/'Root-freeze.json')['operator_identity'])
    if (root/'controller-pid.json').exists():known(read(root/'controller-pid.json')['identity'])
    if closed_keeper is not None:known(dict(pid=closed_keeper['pid'],created=closed_keeper['created']))
    if not setup_only:known(original['owner_identity'])
    unknown=set();phases=[]
    for name in sorted(Path(plan['owned_root']).glob('*/cleanup.json')):
        directory=name.parent;cleanup=read(name)
        need(cleanup['remaining']==[] and cleanup['cleanup_errors']==[] and cleanup['controller_eof'] and
             cleanup['monitor_threads_joined'] and cleanup['capture_writers_reaped'],'phase ownership cleanup missing')
        if q['passed']:need(cleanup['errors']==[],'successful phase has primary cleanup error')
        containment=read(directory/'containment.json');ready=read(directory/'supervisor-ready.json')
        unknown.update((containment['worker_pid'],ready['caretaker_pid']))
        census=directory/'process-census.jsonl'
        need(census.stat().st_size<=16*1024**2,'bounded owned process census')
        for line in census.read_bytes().splitlines():
            for value in json.loads(line)['processes']:known(value)
        phases.append(dict(directory=str(directory),cleanup_sha256=sha(name),empty_owned_job=True))
    if q['passed']:
        expected={shape+'-'+stage for shape in execution_shapes(plan) for stage in ('generation','Run','verify')}
        if not large:expected.update('D-'+stage for stage in ('failure-prepare','failure','failure-verify'))
        need({Path(phase['directory']).name for phase in phases}==expected,'complete exact phase roles required')
        completion=read(Path(plan['campaign'])/('Windows-scale-completed.json' if large else 'Windows-tiny-completed.json'))
        need(completion['passed'] and completion['scale_result_sha256' if large else 'qualification_sha256']==sha(qfile) and
             completion['plan_sha256']==q['plan_sha256'],'completion custody mismatch')
        for shape in execution_shapes(plan):
            report=read(Path(plan['owned_root'])/(shape+'-verified.json'))
            need(report['passed'] and report['slot']=='Windows'+shape and report['evidence_kind']==('native-scale' if large else 'native-tiny'),
                 'actual independent verifier required')
            if large:
                from .native_scale_identity import Lineage
                lineage=Lineage(plan);claim=lineage.claim_path('Windows'+shape)
                need(sha(claim)==read(Path(plan['campaign'])/('Windows'+shape+'-consumed.json'))['claim_sha256'],
                     'actual canonical claim receipt required')
                need(shape!='G' or report['external_memory_claim']=='present','actual G spill required')
    if setup_only:need(phases == [], 'no-start proof contradicts phase execution')
    proof=controls.exited_births(tuple(births.values()))
    # Unobserved historical births stay unknown. Only actual PID absence or a
    # signaled held process can discharge these; never treat arbitrary reuse as proof.
    for pid in sorted(unknown-{pid for pid,_ in births}):
        proof.append(unobserved_birth_exit(kernel,windows,pid,deadline=started+30))
    lock=Path(original['path']);before=stamp(lock)
    need(before==original['stat']==execution['original_lock_stat'],'original inode/stat drift')
    import msvcrt
    fd=os.open(lock,os.O_RDWR);acquired=False
    try:
        value=os.fstat(fd)
        fd_before=[value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,value.st_mode]
        need([value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns]==before[:4],'independent original descriptor mismatch')
        os.lseek(fd,0,os.SEEK_SET);msvcrt.locking(fd,msvcrt.LK_NBLCK,1);acquired=True
        value=os.fstat(fd)
        need(stamp(lock)==before and
             [value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,value.st_mode]==fd_before,
             'original same-producer stat drift under probe')
    finally:
        if acquired:os.lseek(fd,0,os.SEEK_SET);msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
        try:
            value=os.fstat(fd)
            need([value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,value.st_mode]==fd_before,
                 'original descriptor drift before close')
        finally:os.close(fd)
    need(stamp(lock)==before and time.monotonic()-started<30,'final close/stat/deadline')
    result=dict(schema='native103-windows-scale-after-exit-v1' if large else 'native178-full-tiny-after-exit-v1',qualification_passed=q['passed'],
        qualification_sha256=None if setup_only else sha(qfile),setup_only=setup_only,
        startup_failure_sha256=sha(root/'controller-startup-failure.json') if setup_only else None,
        phases=phases,owned_births=proof,original_lock_stat=before,
        verifier_role=dict(path=str(verifier),sha256=sha(verifier),separately_pinned=verifier_sha256 is not None),
        original_byte_zero_available=True,independent_probe_released=True,administrative_recovery=False,
        seconds=time.monotonic()-started)
    if large:
        from .native_scale_identity import Lineage
        lineage=Lineage(plan)
        if hasattr(lineage,'retained_d'):
            result['retained_windows_d']=lineage.retained_d['descriptor']
            result['current_session_shapes']=['G']
    with (root/'after-exit-proof.json').open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps(dict(after_exit_sha256=sha(root/'after-exit-proof.json'),qualification_passed=q['passed'])),flush=True)
