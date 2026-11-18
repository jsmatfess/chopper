"""Bounded release tooling. Scale execution requires separate parent authorization."""
import argparse
import json
from pathlib import Path
from scale_acceptance.generate import prepare, write_new, fixture_identity
from scale_acceptance.verify import verify
from scale_acceptance.guard import run
from scale_acceptance.plan import make
from scale_acceptance.browser_plan import make_browser
from scale_acceptance.browser_scale_plan import make_scale
from scale_acceptance.browser_scale_guard import run_scale, copy_recovery_profile
from scale_acceptance.verify import read_json, require
from scale_acceptance.recipe import VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    identity = sub.add_parser('fixture-identity', help='cold streaming hash only; no CSV generation or acceptance')
    identity.add_argument('receipt', type=Path)
    identity.add_argument('--shape', choices=['D', 'G'], required=True)
    identity.add_argument('--runtime', choices=['native', 'browser'], required=True)
    identity.add_argument('--rows', type=int)
    gen = sub.add_parser('prepare')
    gen.add_argument('directory', type=Path)
    gen.add_argument('--shape', choices=['D', 'G'], required=True)
    gen.add_argument('--runtime', choices=['native', 'browser'], required=True)
    gen.add_argument('--rows', type=int, help='tiny control, 1..2000; omitted means selected full scale')
    gen.add_argument('--borrowed-packet', type=Path)
    gen.add_argument('--borrowed-packet-sha256')
    check = sub.add_parser('verify')
    check.add_argument('job', type=Path)
    check.add_argument('fixture', type=Path)
    check.add_argument('receipt', type=Path)
    check.add_argument('--output', type=Path)
    check.add_argument('--bitmap-dir', type=Path, required=True)
    check.add_argument('--peer', type=Path)
    batch = sub.add_parser('run')
    batch.add_argument('manifest', type=Path)
    batch.add_argument('directory', type=Path)
    batch.add_argument('policy', type=Path)
    plan = sub.add_parser('plan')
    plan.add_argument('directory', type=Path)
    plan.add_argument('--shape', choices=['D', 'G'])
    plan.add_argument('--frozen', type=Path)
    browser = sub.add_parser('browser-plan', help='prepare tiny-only frozen production integration; never launch')
    browser.add_argument('directory', type=Path)
    browser.add_argument('--frozen', type=Path, required=True)
    browser.add_argument('--rows', type=int, default=127)
    scale = sub.add_parser('browser-scale-plan', help='prepare one explicit scale shape; never launch')
    scale.add_argument('directory', type=Path)
    scale.add_argument('--frozen', type=Path, required=True)
    execute = sub.add_parser('browser-scale-run', help='parent-only approved, reserved Windows attempt')
    execute.add_argument('manifest', type=Path)
    execute.add_argument('policy', type=Path)
    execute.add_argument('--approval', type=Path, required=True)
    execute.add_argument('--preflight', type=Path)
    execute.add_argument('--preflight-sha256')
    recovery=sub.add_parser('browser-scale-copy-profile',help='internal bounded closed-profile copy; never Run')
    recovery.add_argument('definition',type=Path)
    recovery.add_argument('--sha256',required=True)
    args = parser.parse_args()
    if args.command=='browser-scale-copy-profile':
        print(json.dumps(copy_recovery_profile(dict(path=str(args.definition),sha256=args.sha256))))
    elif args.command == 'fixture-identity':
        import time
        require(not args.receipt.exists() and not args.receipt.is_symlink(), 'fresh identity receipt required')
        started = time.monotonic()
        result = dict(generator=VERSION, shape=args.shape, runtime=args.runtime,
                      fixture=fixture_identity(args.shape, args.runtime, args.rows),
                      generated_input_bytes=0, stored_input_verified=False,
                      elapsed_seconds=time.monotonic()-started)
        write_new(args.receipt, result)
        print(json.dumps(result))
    elif args.command == 'prepare':
        borrowed = None
        require(bool(args.borrowed_packet) == bool(args.borrowed_packet_sha256), 'borrowed packet path/hash pair')
        if args.borrowed_packet:
            from scale_acceptance.hosted_qualification import bound_json
            from scale_acceptance.browser_scale_identity import validate_packet
            packet = bound_json(dict(path=str(args.borrowed_packet), sha256=args.borrowed_packet_sha256))
            validate_packet(packet)
            require(packet['mode'] == 'qualify' and packet['shape'] == args.shape, 'borrowed Tiny packet only')
            borrowed = packet['borrowed_input']
        print(json.dumps(prepare(args.directory, args.shape, args.runtime, args.rows, borrowed=borrowed)))
    elif args.command == 'verify':
        result = verify(args.job, args.fixture, args.output, args.bitmap_dir, args.peer)
        write_new(args.receipt, result)
        print(json.dumps(dict(rows=result['rows'], chunks=len(result['chunks']))))
    elif args.command == 'browser-plan':
        print(json.dumps(make_browser(args.directory, args.frozen, args.rows)))
    elif args.command == 'browser-scale-plan':
        print(json.dumps(make_scale(args.directory, args.frozen)))
    elif args.command == 'browser-scale-run':
        require(bool(args.preflight) == bool(args.preflight_sha256), 'preflight path/hash must be supplied together')
        return run_scale(args.manifest, args.policy, args.approval, preparation=(
            dict(path=str(args.preflight), sha256=args.preflight_sha256) if args.preflight else None))
    elif args.command == 'plan':
        print(json.dumps(make(args.directory, args.shape, args.frozen)))
    else:
        require(read_json(args.manifest).get('contract') not in ('browser-scale-v1', 'browser-scale-tiny-v1'),
                'use browser-scale-run with explicit parent approval')
        return run(args.manifest, args.directory, args.policy)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
