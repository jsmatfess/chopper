"""Bounded native experiment sessions; no model invocation."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from experiment_session import cycle, execute, read, storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run', 'status', 'stop'])
    parser.add_argument('directory', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--decision', type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    try:
        if args.command == 'stop':
            (directory / 'STOP').touch(exist_ok=True)
            return 0
        if args.command == 'status':
            state = read(directory / 'controller-status.json')
            state['current_elapsed_seconds'] = time.time() - state['started_unix']
            state['current_stored_bytes'] = storage(directory)
            print(json.dumps(state, indent=2))
            return 0
        # Native Windows is the first supported unattended runtime. Fail closed
        # if its crash-containment Job cannot be established.
        if os.name != 'nt':
            raise ValueError('unattended execution currently requires native Windows crash containment')
        cycle.runner.contain_session()
        return execute(args.config, directory, args.decision)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f'experiment-controller: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
