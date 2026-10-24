#!/usr/bin/env python3
"""Watch a Mach-O fixture in a disposable Darling prefix with `quadrahq --watch-stalls`.

The fixture spins in nested functions on one thread and waits on a pipe on another. The
watcher must find the spinning thread, name its functions and show where the other waits.
Needs the built shim (build/libMacOBloxShims.dylib) and MACOBLOX_ALLOW_DEBUGGER=1 for the
fixture, which this runner sets. No game, account, installed prefix or compositor is used.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
from macoblox import diagnostics, runtime, stallwatch


def fixture_pid(name):
    for entry in os.listdir('/proc'):
        if entry.isdigit():
            try:
                command = Path(f'/proc/{entry}/cmdline').read_bytes().split(b'\0')[0].decode(errors='replace')
            except OSError:
                continue
            if Path(command).name == name:
                return int(entry)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shim', type=Path, default=ROOT / 'build/libMacOBloxShims.dylib')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--watch-seconds', type=float, default=5.0)
    args = parser.parse_args()
    selected = runtime.resolve_runtime()
    sysroot, client = Path(selected['sysroot']), selected['executable']
    output = (args.output_dir or Path(tempfile.mkdtemp(prefix='quadra-stall-watch-'))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    binary = output / 'stall-watch-fixture'
    subprocess.run(['clang', '-target', 'x86_64-apple-darwin', '-fuse-ld=lld', '-isysroot', str(sysroot),
                    '-mmacosx-version-min=11.0', '-O1', '-fno-omit-frame-pointer',
                    str(ROOT / 'tests/darling_stall_watch_test.c'), '-o', str(binary)],
                   check=True, timeout=60)
    values = {'MACOBLOX_ALLOW_DEBUGGER': '1', 'DYLD_FORCE_FLAT_NAMESPACE': '1',
              'DYLD_INSERT_LIBRARIES': '/Volumes/SystemRoot' + str(args.shim.resolve())}
    log_path = output / 'fixture.log'
    failures = []
    pid = process = environment = None
    prefix = None
    # A new Darling prefix sometimes makes its client exit before the program runs: try a fresh one.
    for attempt in range(3):
        prefix = Path(tempfile.mkdtemp(prefix='quadra-stall-watch-prefix-')) / 'prefix'
        environment = {key: value for key, value in os.environ.items()
                       if key not in ('DPREFIX', 'DYLD_INSERT_LIBRARIES', 'DYLD_FRAMEWORK_PATH', 'LD_PRELOAD')}
        environment.update(DPREFIX=str(prefix))
        command = [client, 'shell', '/bin/bash', '-c', 'exec /usr/bin/env "$@"', 'stall-watch-fixture',
                   *[f'{key}={value}' for key, value in values.items()],
                   '/Volumes/SystemRoot' + str(binary), '90']
        log = log_path.open('w')
        process = subprocess.Popen(command, env=environment, stdout=log, stderr=subprocess.STDOUT)
        log.close()
        deadline = time.monotonic() + 120
        while pid is None and time.monotonic() < deadline and process.poll() is None:
            pid = fixture_pid('stall-watch-fixture')
            time.sleep(0.5)
        if pid is not None:
            break
        subprocess.run([client, 'shutdown'], env=environment, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
        print(f'The fixture did not start (attempt {attempt + 1} of 3, client status {process.poll()}); '
              f'see {log_path}')
        print('  command:', ' '.join(command))
    try:
        if pid is None:
            return 1
        time.sleep(1.0)  # let both threads settle
        capture = output / 'capture.jsonl'
        until = time.monotonic() + args.watch_seconds
        stacks = stallwatch.capture(pid, capture, stop=lambda: time.monotonic() > until)
        if not stacks:
            failures.append('the shim did not allow reading the fixture (MACOBLOX_ALLOW_DEBUGGER)')
        records = stallwatch.load(capture)
        roots = (prefix, sysroot)
        symbols = diagnostics._symbolize(stallwatch._locations(records), diagnostics._symbolizer(), roots)
        text = stallwatch.render(records, [], symbols, everything=True)
        (output / 'report.txt').write_text(text)
        for name in ('stall_watch_inner', 'stall_watch_outer'):
            if name not in text:
                failures.append(f'{name} is not in the report of the spinning thread')
        waits = [stallwatch._name_of(symbols, location) for record in records if record['k'] == 'wait'
                 for location in ([record.get('pc')] + (record.get('s') or [])) if location]
        if not any('stall_watch_wait_for_pipe' in name for name in waits):
            failures.append('the thread waiting on the pipe was not placed in stall_watch_wait_for_pipe')
        if not any(record['k'] == 'run' and record.get('w') and record['tid'] == pid for record in records):
            failures.append('the main thread was not sampled while it slept')
    finally:
        subprocess.run([client, 'shutdown'], env=environment, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
        try:
            process.wait(timeout=30)
        except (NameError, subprocess.TimeoutExpired):
            pass
    print(f'Evidence: {output}')
    for failure in failures:
        print('FAIL:', failure)
    if not failures:
        print('PASS: the watcher named the spinning thread\'s functions and the pipe wait in Darling')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
