#!/usr/bin/env python3
"""Check the real Metal.framework budget in a disposable Darling prefix.

Requires a built Metal.framework and libquadra_metal_host.so in --metal-dir.
No compositor, game, account, installed framework or existing prefix is used.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metal-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--sysroot', type=Path)
    parser.add_argument('--darling')
    args = parser.parse_args()
    selected = runtime.resolve_runtime()
    sysroot = args.sysroot or Path(selected['sysroot'])
    client = args.darling or selected['executable']
    metal = args.metal_dir.resolve()
    output = (args.output_dir or Path(tempfile.mkdtemp(prefix='quadra-metal-budget-'))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    binary = output / 'metal-budget-test'
    subprocess.run(['clang', '-target', 'x86_64-apple-darwin', '-fuse-ld=lld',
                    '-isysroot', str(sysroot), '-mmacosx-version-min=11.0',
                    '-F' + str(metal), str(ROOT / 'tests/darling_metal_budget_test.m'),
                    '-framework', 'Metal', '-framework', 'Foundation', '-o', str(binary)],
                   check=True, timeout=30)
    prefix = Path(tempfile.mkdtemp(prefix='quadra-metal-budget-prefix-')) / 'prefix'
    values = {'DYLD_FRAMEWORK_PATH': '/Volumes/SystemRoot' + str(metal),
              'MACOBLOX_METAL_HOST_LIBRARY': str(metal / 'libquadra_metal_host.so'),
              'MACOBLOX_METAL_SHADER_CACHE': str(output / 'shader-cache'),
              'MACOBLOX_METAL_PRELOAD_IN_PROCESS': '0',
              'MACOBLOX_VRAM_BYTES': '134217728'}
    environment = {key: value for key, value in os.environ.items()
                   if key not in ('DPREFIX', 'DYLD_INSERT_LIBRARIES', 'DYLD_FRAMEWORK_PATH', 'LD_PRELOAD')}
    environment.update(values, DPREFIX=str(prefix))
    command = [client, 'shell', '/bin/bash', '-c',
               'unset DYLD_INSERT_LIBRARIES LD_PRELOAD; exec /usr/bin/env "$@"', 'metal-budget-test',
               *[f'{key}={value}' for key, value in values.items()], '/Volumes/SystemRoot' + str(binary)]
    log_path = output / 'metal-budget.log'
    try:
        with log_path.open('w') as log:
            result = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=40)
    finally:
        subprocess.run([client, 'shutdown'], env=environment, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15)
    text = log_path.read_text(errors='replace')
    for line in text.splitlines():
        if 'PASS:' in line or 'FAIL line' in line:
            print(line)
    print(f'Evidence: {log_path}')
    return 0 if result.returncode == 0 and 'PASS: real Metal' in text else 1


if __name__ == '__main__':
    raise SystemExit(main())
