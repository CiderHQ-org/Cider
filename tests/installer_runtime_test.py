"""Exercise installer decisions with stubbed builds; never install host packages."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from macoblox import runtime


ROOT = Path(__file__).resolve().parents[1]


class InstallerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.functions = self.base / "installer-functions.sh"
        source = (ROOT / "install.sh").read_text()
        self.assertTrue(source.endswith('main "$@"; exit\n'))
        self.functions.write_text(source.removesuffix('main "$@"; exit\n'))
        self.environment = dict(os.environ, HOME=str(self.base),
                                XDG_CONFIG_HOME=str(self.base / "config"),
                                XDG_CACHE_HOME=str(self.base / "cache"),
                                XDG_DATA_HOME=str(self.base / "data"),
                                NO_COLOR="1", TERM="dumb", FIXTURE=str(self.base))
        for key in ("DPREFIX", "DARLING_SYSROOT", "DARLING_BUILD_JOBS"):
            self.environment.pop(key, None)

    def shell(self, body, **environment):
        return subprocess.run(["bash", "-c", '. "$1"\n' + body, "test", str(self.functions)],
                              env=dict(self.environment, **environment),
                              capture_output=True, text=True, timeout=20)

    def checked(self, body, **environment):
        result = self.shell(body, **environment)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_default_and_cli_choices_and_invalid_values(self):
        body = '''
banner() { :; }; setup_plan() { :; }
do_install() { printf '%s|%s' "$DARLING_RUNTIME" "$PREFIX"; }
main '''
        self.assertEqual(self.checked(body + '--yes').lstrip('\n'), f'regular|{self.base}/.darling')
        self.assertEqual(self.checked(body + '--yes --darling ciderdarling').lstrip('\n'), f'ciderdarling|{self.base}/.ciderdarling')
        self.assertEqual(self.checked(body + '--yes --darling=regular').lstrip('\n'), f'regular|{self.base}/.darling')
        for options in ('--darling wrong', '--darling', '--darling='):
            self.assertNotEqual(self.shell(body + options).returncode, 0)

    def test_atomic_save_roundtrip_update_retains_selection_and_prefix(self):
        self.checked('''
DARLING_RUNTIME=ciderdarling
DARLING_EXECUTABLE="$FIXTURE/runtime with spaces/bin/darling"
DARLING_SYSROOT="$FIXTURE/runtime with spaces/libexec/darling"
PREFIX="$FIXTURE/custom prefix"
save_darling_selection
''')
        path = self.base / "config/ciderhq/runtime.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(path.parent.iterdir()), [path])
        output = self.checked('''
load_darling_selection
printf '%s|%s|%s' "$DARLING_RUNTIME" "$PREFIX" "$DARLING_EXECUTABLE"
''')
        self.assertEqual(output, f'ciderdarling|{self.base}/custom prefix|{self.base}/runtime with spaces/bin/darling')
        self.assertEqual(self.checked('DARLING_RUNTIME=regular; load_darling_selection; printf "%s" "$PREFIX"'), str(self.base / '.darling'))

    def test_metadata_reuse_and_no_upstream_package_fallback(self):
        output = self.checked('''
DARLING_RUNTIME=ciderdarling; load_darling_selection
CIDER_DARLING_INSTALL="$FIXTURE/runtime"
ciderdarling_matches() { return 0; }
try_darling_package() { exit 91; }
confirm_darling_build() { exit 92; }
ensure_darling
printf '%s|%s|%s' "$DARLING_EXECUTABLE" "$DARLING_SYSROOT" "$DPREFIX"
''')
        self.assertEqual(output, f'{self.base}/runtime/bin/darling|{self.base}/runtime/libexec/darling|{self.base}/.ciderdarling')

    def test_gui_and_installer_preserve_both_runtime_profiles(self):
        file = self.base / 'config/ciderhq/runtime.json'
        def entry(variant):
            return {'schema_version': 1, 'runtime': variant,
                    'executable': str(self.base / variant / 'bin/darling'),
                    'sysroot': str(self.base / variant / 'libexec/darling'),
                    'prefix': str(self.base / (variant + ' custom prefix'))}
        regular, cider = entry('regular'), entry('ciderdarling')
        runtime.save_selection(cider, file, current=regular)
        output = self.checked('''
DARLING_RUNTIME=regular
load_darling_selection
printf '%s|%s' "$PREFIX" "$DARLING_EXECUTABLE"
DARLING_SYSROOT=${DARLING_SELECTION[2]}
save_darling_selection
''')
        self.assertEqual(output, f"{regular['prefix']}|{regular['executable']}")
        history = runtime.remembered_runtimes(runtime.read_selection(file))
        self.assertEqual(history['ciderdarling']['prefix'], cider['prefix'])
        self.assertEqual(self.checked('DARLING_RUNTIME=ciderdarling; load_darling_selection; printf "%s" "$PREFIX"'), cider['prefix'])

    def test_declined_cider_build_never_installs_regular_darling(self):
        result = self.shell('''
DARLING_RUNTIME=ciderdarling; load_darling_selection
CIDER_DARLING_INSTALL="$FIXTURE/runtime"
ciderdarling_matches() { return 1; }
detect_package_manager() { printf apt-get; }
confirm_darling_build() { return 1; }
try_darling_package() { exit 91; }
build_darling_source() { exit 92; }
ensure_darling
''')
        self.assertEqual(result.returncode, 1)
        self.assertIn('CiderDarling compilation declined', result.stderr)

    def test_regular_selection_skips_cider_client_ahead_on_path(self):
        for name in ('regular', 'ciderdarling'):
            root = self.base / name
            (root / 'bin').mkdir(parents=True)
            client = root / 'bin/darling'
            client.write_text('#!/bin/sh\nexit 0\n'); client.chmod(0o755)
            (root / 'libexec/darling').mkdir(parents=True)
        metadata = self.base / 'ciderdarling/libexec/darling/usr/share/ciderdarling/runtime.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text('{}')
        output = self.checked('''
PATH="$FIXTURE/ciderdarling/bin:$FIXTURE/regular/bin:$PATH"
load_darling_selection
select_regular_darling
printf '%s|%s' "$DARLING_EXECUTABLE" "$DARLING_SYSROOT"
''')
        self.assertEqual(output, f'{self.base}/regular/bin/darling|{self.base}/regular/libexec/darling')

    def test_incomplete_version_directory_is_preserved(self):
        root = self.base / 'runtime'
        root.mkdir()
        sentinel = root / 'keep'
        sentinel.write_text('existing runtime')
        result = self.shell('''
DARLING_RUNTIME=ciderdarling; load_darling_selection
CIDER_DARLING_INSTALL="$FIXTURE/runtime"
ciderdarling_matches() { return 1; }
build_darling_source() { exit 91; }
ensure_darling
''')
        self.assertEqual(result.returncode, 1)
        self.assertIn('incomplete or mismatched metadata', result.stderr)
        self.assertEqual(sentinel.read_text(), 'existing runtime')

    def test_menu_can_select_either_runtime_and_cancel(self):
        body = '''
load_darling_selection
is_installed() { return 1; }; setup_plan() { :; }
choose() { CHOICE=$FAKE_CHOICE; FAKE_CHOICE=0; }
FAKE_CHOICE='''
        for choice, variant in ((0, 'regular'), (1, 'ciderdarling')):
            output = self.checked(body + str(choice) + '\nmenu_install\nprintf "%s" "$DARLING_RUNTIME"')
            self.assertEqual(output, variant)
        self.assertNotEqual(self.shell(body + '2\nmenu_install').returncode, 0)

    def test_explicit_jobs_and_auto_affinity_cap(self):
        self.assertEqual(self.checked('darling_build_jobs', DARLING_BUILD_JOBS='7'), '7')
        jobs = int(self.checked('darling_build_jobs'))
        self.assertGreaterEqual(jobs, 1)
        self.assertLessEqual(jobs, len(os.sched_getaffinity(0)))
        for value in ('0', '-1', 'oops', '8193', '999999999999999999'):
            self.assertNotEqual(self.shell('darling_build_jobs', DARLING_BUILD_JOBS=value).returncode, 0)

    def test_installed_cider_pin_and_manifest_must_match(self):
        root = self.base / 'runtime'
        client = root / 'bin/darling'
        client.parent.mkdir(parents=True)
        client.write_text('#!/bin/sh\nexit 0\n'); client.chmod(0o755)
        metadata = root / 'libexec/darling/usr/share/ciderdarling/runtime.json'
        metadata.parent.mkdir(parents=True)
        source = (ROOT / 'install.sh').read_text()
        def constant(name):
            return next(line.split('=', 1)[1] for line in source.splitlines() if line.startswith(name + '='))
        data = {'schema_version': 1, 'name': 'CiderDarling', 'architecture': 'x86_64',
                'source_revision': constant('CIDER_DARLING_REVISION'),
                'patch_manifest_sha256': constant('CIDER_DARLING_MANIFEST')}
        body = 'CIDER_DARLING_INSTALL="$FIXTURE/runtime"; ciderdarling_matches'
        metadata.write_text(json.dumps(data))
        self.checked(body)
        for key in ('source_revision', 'patch_manifest_sha256', 'name', 'architecture'):
            changed = dict(data, **{key: 'mismatch'})
            metadata.write_text(json.dumps(changed))
            self.assertNotEqual(self.shell(body).returncode, 0)

    def test_cider_build_passes_correct_prefix_flags_and_job_count(self):
        self.checked('''
DARLING_RUNTIME=ciderdarling
CIDER_DARLING_INSTALL="$FIXTURE/runtime"
install_darling_build_dependencies() { :; }
download_ciderdarling() { mkdir -p "$1"; printf 'source-ready\\n'; }
prepare_darling_compiler_compatibility() { exit 91; }
darling_literal_flags() { :; }
cmake() { printf '%s\\n' "$@" >> "$FIXTURE/commands"; }
sudo() { "$@"; mkdir -p "$CIDER_DARLING_INSTALL/bin"; touch "$CIDER_DARLING_INSTALL/bin/darling"; chmod 755 "$CIDER_DARLING_INSTALL/bin/darling"; }
ciderdarling_matches() { return 0; }
build_darling_source apt-get
''', DARLING_BUILD_JOBS='7')
        commands = (self.base / 'commands').read_text().splitlines()
        for argument in (f'-DCMAKE_INSTALL_PREFIX={self.base}/runtime', '-DCIDER_SHUTDOWN_ON_INSTALL=OFF',
                         '-DENABLE_METAL=OFF', '-DCIDER_APPLY_PATCHES=ON', '-DTARGET_i386=OFF'):
            self.assertIn(argument, commands)
        index = commands.index('--parallel')
        self.assertEqual(commands[index + 1], '7')
