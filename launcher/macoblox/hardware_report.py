"""Collect local hardware coverage without account data or uploads."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

from . import __version__, gpus

STAGES = ('startup', 'join', 'leave', 'shutdown', 'fullscreen', 'suspend_resume')


def _xwayland_version():
    """The Xwayland release (`24.1.14`), or None where it is not installed."""
    program = shutil.which('Xwayland')
    if not program:
        return None
    try:
        text = subprocess.run([program, '-version'], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'Xwayland Version (\d+(?:\.\d+)*)', text.stderr + text.stdout)
    return match[1] if match else None


def _input(core, environment=None):
    """What decides whether the camera lock works: the window backend, raw mouse, and the
    mouse-lock lines the newest launch log recorded (counts of each distinct line; no paths)."""
    settings = core.load_settings()
    lines = {}
    try:
        newest = max(Path(core.LOGS).glob('launch-*.log'), key=lambda path: path.stat().st_mtime)
        with newest.open(errors='replace') as stream:
            for line in stream.read(32 * 1024 * 1024).splitlines():
                at = line.find('[Quadra Input]')
                if at >= 0 and 'addLocalMonitor' not in line:
                    text = line[at:at + 160].strip()
                    lines[text] = lines.get(text, 0) + 1
    except (OSError, ValueError):
        pass
    return {'display_backend': settings.get('display_backend'), 'raw_mouse': settings.get('raw_mouse'),
            'log': [{'line': text, 'count': count} for text, count in list(lines.items())[:25]]}


def _desktop(environment):
    return {'wayland': bool(environment.get('WAYLAND_DISPLAY')), 'x11': bool(environment.get('DISPLAY')),
            'session_type': environment.get('XDG_SESSION_TYPE', ''),
            'desktop': environment.get('XDG_CURRENT_DESKTOP', ''), 'xwayland': _xwayland_version()}


def collect(output_dir=None, *, graphics=False, gameplay=None):
    from . import core
    output_dir = Path(output_dir) if output_dir else core.CACHE_DIR / 'diagnostics'
    output_dir.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    for key in ('LD_PRELOAD', 'DYLD_INSERT_LIBRARIES', 'DYLD_LIBRARY_PATH', 'DYLD_FRAMEWORK_PATH', 'DPREFIX'):
        environment.pop(key, None)
    prefix = Path(core.DARLING_SYSROOT).parent.parent
    doctor = prefix / 'bin/ciderdarling-doctor'
    matrix = prefix / 'libexec/ciderdarling/hardware-matrix.py'
    probe = prefix / 'libexec/ciderdarling/cider-gl-probe'
    report = {'schema_version': 1, 'cider_version': __version__,
              'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'architecture': platform.machine(), 'kernel': platform.release(),
              'allowed_cpus': len(os.sched_getaffinity(0)), 'gpus': gpus.enumerate_gpus(),
              'runtime': core.DARLING_RUNTIME.get('metadata') or {'name': core.DARLING_RUNTIME['runtime']},
              'desktop': _desktop(os.environ), 'input': _input(core),
              'coverage': {'host_graphics': 'not_run', 'gameplay': {stage: 'not_tested' for stage in STAGES}}}
    if gameplay:
        for stage, result in gameplay.items():
            if stage not in STAGES or result not in ('pass', 'fail', 'not_tested'):
                raise ValueError('Invalid gameplay observation')
        report['coverage']['gameplay'].update(gameplay)
        report['coverage']['gameplay_source'] = 'user_reported; not inferred from host probes'
    if doctor.is_file():
        try:
            result = subprocess.run([sys.executable, str(doctor), '--json', '--sysroot', str(core.DARLING_SYSROOT)],
                                    env=environment, capture_output=True, text=True, timeout=15)
            if result.returncode or len(result.stdout) > 1024 * 1024:
                raise ValueError('Runtime hardware inventory failed')
            report['host'] = json.loads(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            report['inventory_error'] = str(error)
    if graphics:
        report['m2vk'] = _m2vk(core, environment)
        report['coverage']['m2vk'] = report['m2vk']['status']
        if not (matrix.is_file() and probe.is_file()):
            report['coverage']['host_graphics'] = 'unavailable'
        else:
            with tempfile.TemporaryDirectory(prefix='quadra-hardware-') as directory:
                path = Path(directory) / 'matrix.json'
                try:
                    result = subprocess.run([sys.executable, str(matrix), '--probe', str(probe), '--frames', '120',
                                             '--output', str(path)], env=environment, capture_output=True,
                                            text=True, timeout=300)
                    if not path.is_file() or path.stat().st_size > 1024 * 1024:
                        raise ValueError('Hardware matrix did not produce a bounded report')
                    report['graphics_matrix'] = json.loads(path.read_bytes())
                    report['coverage']['host_graphics'] = 'pass' if result.returncode == 0 else 'fail'
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    report['coverage']['host_graphics'] = 'error'
                    report['graphics_error'] = str(error)
    descriptor, name = tempfile.mkstemp(prefix='quadra-hardware-', suffix='.json', dir=output_dir)
    with os.fdopen(descriptor, 'w') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    return Path(name)


def _m2vk(core, environment):
    """Quadra M2VK's own view of the GPU: the device and driver it opens, whether the runtime has
    measured that exact combination, and whether a test copy ran on it. No paths or account data."""
    from . import graphics as renderer
    if not core.metal_built():
        return {'status': 'not_built'}
    environment = dict(environment, **renderer.metal_environment(
        core.METAL_DIR, core.CACHE_DIR / 'metal-shader-cache', preload=False))
    return renderer.metal_report(environment, core.METAL_HOST_LIBRARY)


def cli(argv):
    parser = argparse.ArgumentParser(prog='quadrahq --hardware-report', description=__doc__)
    parser.add_argument('--output', type=Path, help='Report directory; existing files are preserved')
    parser.add_argument('--graphics', action='store_true', help='Run host GPU, MSAA, 1/2 CPU and lifecycle checks')
    parser.add_argument('--gameplay', action='append', default=[], metavar='STAGE=pass|fail|not_tested',
                        help='Record an observation separately from automated host results: ' + ', '.join(STAGES))
    args = parser.parse_args(argv)
    try:
        gameplay = dict(value.split('=', 1) for value in args.gameplay)
        print(collect(args.output, graphics=args.graphics, gameplay=gameplay))
        return 0
    except (OSError, ValueError) as error:
        parser.error(str(error))
