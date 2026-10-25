#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the native Vulkan experiment in a dedicated disposable Darling prefix."""
from pathlib import Path
import argparse
import os
import shlex
import shutil
import stat
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(__file__).resolve().parents[2] / 'work/metal-backend-repro'
    parser.add_argument('--work', type=Path, default=default)
    parser.add_argument('--prefix', type=Path)
    parser.add_argument('--baseline', type=Path, help='optional stock disposable prefix to copy')
    parser.add_argument('--device', action='store_true', help='device/memory/queue probe only')
    parser.add_argument('--vertex', type=Path, help='local metallib created by shader_cache.py')
    parser.add_argument('--fragment', type=Path, help='local metallib created by shader_cache.py')
    options = parser.parse_args()
    work = options.work.resolve()
    prefix = (options.prefix or work / 'prefix').resolve()
    marker = prefix / '.quadra-metal-experiment'
    if prefix.exists() and not marker.is_file():
        raise SystemExit('Refusing an existing prefix without the experiment marker; choose a new path.')
    if not prefix.exists():
        if options.baseline:
            def ignore(directory, names):
                return [name for name in names
                        if name == '.init.pid' or name.startswith('.darlingserver') or
                        stat.S_ISSOCK(os.lstat(Path(directory) / name).st_mode)]
            shutil.copytree(options.baseline, prefix, symlinks=True, ignore=ignore)
        else:
            prefix.mkdir(parents=True)
        marker.write_text('Disposable native Metal/Vulkan experiment prefix\n')
    if options.device:
        arguments = [work / 'out/device-probe']
    elif options.vertex and options.fragment:
        arguments = [work / 'out/pipeline-probe', options.vertex.resolve(), options.fragment.resolve()]
    else:
        parser.error('choose --device or provide both --vertex and --fragment')
    for argument in arguments:
        if not argument.is_file():
            raise SystemExit(f'Probe input is missing: {argument}')
    host_path = lambda path: '/Volumes/SystemRoot' + str(path)
    exports = {'DYLD_LIBRARY_PATH': host_path(work / 'out'),
               'DYLD_FRAMEWORK_PATH': host_path(work / 'out'),
               'DYLD_FORCE_FLAT_NAMESPACE': '1',
               'MACOBLOX_METAL_SHADER_CACHE': host_path(work / 'shader-cache')}
    command = 'export ' + ' '.join(f'{key}={shlex.quote(value)}' for key, value in exports.items())
    command += '; exec ' + shlex.join(host_path(path) for path in arguments)
    env = dict(os.environ, DPREFIX=str(prefix))
    env.pop('DYLD_INSERT_LIBRARIES', None)
    if env.get('QUADRA_NOROOT_LIB'):
        env['LD_PRELOAD'] = env['QUADRA_NOROOT_LIB']
    log_path = work / 'probe.log'
    result = 1
    try:
        # Darling's server may inherit stdout; a regular file avoids a PIPE wait.
        with log_path.open('wb') as log:
            process = subprocess.run(['darling', 'shell', '/bin/bash', '-c', command], env=env,
                                     stdout=log, stderr=subprocess.STDOUT, timeout=25)
        result = process.returncode
    except subprocess.TimeoutExpired:
        print('Native Vulkan probe timed out')
    finally:
        print(log_path.read_text(errors='replace')[-8000:])
        try:
            subprocess.run(['darling', 'shutdown'], env=env, timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            print('Disposable Darling prefix shutdown timed out')
    print(f'Probe exit: {result}; log: {log_path}')
    raise SystemExit(result)


if __name__ == '__main__':
    main()
