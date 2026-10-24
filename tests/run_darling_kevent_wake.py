#!/usr/bin/env python3
"""Check ordinary kqueue wake-ups and MACOBLOX_KEVENT_POLL_MS in a disposable Darling prefix.

Runs tests/darling_kevent_wake_test.c twice with the shim loaded: without the cap (the idle wait must last its
full second) and with a cap of 100 ms (the idle wait must end after about 100 ms with no events, and every
wake-up case must still pass). Needs a built shim (default build/libMacOBloxShims.dylib, or --shim). No game,
account, installed prefix or compositor is used; a prefix that fails to start is retried.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
from macoblox import runtime


def run(client, binary, shim, cap):
    values = {'DYLD_FORCE_FLAT_NAMESPACE': '1', 'DYLD_INSERT_LIBRARIES': '/Volumes/SystemRoot' + str(shim)}
    if cap:
        values['MACOBLOX_KEVENT_POLL_MS'] = str(cap)
    script = ''.join(f'export {key}={value}; ' for key, value in values.items()) + 'exec "$@"'
    for attempt in range(3):
        prefix = Path(tempfile.mkdtemp(prefix='quadra-kevent-prefix-')) / 'prefix'
        environment = {key: value for key, value in os.environ.items()
                       if key not in ('DPREFIX', 'DYLD_INSERT_LIBRARIES', 'DYLD_FRAMEWORK_PATH', 'LD_PRELOAD')}
        environment.update(DPREFIX=str(prefix))
        command = [client, 'shell', '/bin/bash', '-c', script, 'kevent-wake', '/Volumes/SystemRoot' + str(binary), str(cap)]
        log = Path(str(binary) + f'.{cap}.log')
        with log.open('w') as output:
            process = subprocess.Popen(command, env=environment, stdout=output, stderr=subprocess.STDOUT)
            try:
                process.wait(timeout=90)
            except subprocess.TimeoutExpired:
                process.kill()
        subprocess.run([client, 'shutdown'], env=environment, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
        text = log.read_text(errors='replace')
        if 'RESULT' in text:
            return text
        print(f'attempt {attempt + 1}: no result (client status {process.returncode}); retrying')
    return ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shim', type=Path, default=ROOT / 'build/libMacOBloxShims.dylib')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    selected = runtime.resolve_runtime()
    sysroot, client = Path(selected['sysroot']), selected['executable']
    output = (args.output_dir or Path(tempfile.mkdtemp(prefix='quadra-kevent-'))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    binary = output / 'kevent-wake-test'
    subprocess.run(['clang', '-target', 'x86_64-apple-darwin', '-fuse-ld=lld', '-isysroot', str(sysroot),
                    '-mmacosx-version-min=11.0', '-O1', '-Wall', '-Wextra',
                    str(ROOT / 'tests/darling_kevent_wake_test.c'), '-o', str(binary)], check=True, timeout=60)
    failures = 0
    for cap in (0, 100):
        text = run(client, binary, args.shim.resolve(), cap)
        print(f'--- cap {cap or "off"} ms')
        for line in text.splitlines():
            if line.startswith(('PASS', 'FAIL', 'INFO', 'RESULT')):
                print(line)
        if 'RESULT PASS' not in text:
            failures += 1
    print(f'Evidence: {output}')
    print('FAIL' if failures else 'PASS: wake-ups work with and without the cap, and the cap cuts an idle wait short')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
