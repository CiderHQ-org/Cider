"""Exercise installer decisions with stubbed builds; never install host packages."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from macoblox import runtime
from runtime_update_fixture import release_fixture


ROOT = Path(__file__).resolve().parents[1]


class InstallerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.functions = self.base / "installer-functions.sh"
        source = (ROOT / "install.sh").read_text()
        self.assertTrue(source.endswith('main "$@"; exit\n'))
        self.functions.write_text(source.removesuffix('main "$@"; exit\n') + '\nCIDER_DARLING_PINNED=1\n')
        self.environment = dict(os.environ, HOME=str(self.base),
                                XDG_CONFIG_HOME=str(self.base / "config"),
                                XDG_CACHE_HOME=str(self.base / "cache"),
                                XDG_DATA_HOME=str(self.base / "data"),
                                NO_COLOR="1", TERM="dumb", FIXTURE=str(self.base))
        for key in ("DPREFIX", "DARLING_SYSROOT", "DARLING_BUILD_JOBS"):
            self.environment.pop(key, None)

    def test_release_snapshot_selects_the_exact_ci_archive_checksums(self):
        release = release_fixture()
        file = self.base / 'release.json'
        file.write_text(json.dumps(release))
        output = self.checked('''
CIDER_DARLING_RELEASE_FILE="$FIXTURE/release.json"
resolve_ciderdarling_release
printf '%s|%s|%s|%s' "$CIDER_DARLING_REVISION" "$CIDER_DARLING_INSTALL" "$CIDER_DARLING_PREBUILT_ARCH" "$CIDER_DARLING_PREBUILT_ARCH_MANIFEST"
''')
        self.assertTrue(output.endswith(f'{"a" * 40}|/opt/ciderdarling/{"a" * 40}|{"c" * 64}|{"d" * 64}'))

    def test_invalid_release_is_rejected_even_with_python_optimization(self):
        file = self.base / 'release.json'
        for change in ('path', 'missing-build', 'minimum'):
            data = release_fixture()
            if change == 'path':
                data['builds']['arch']['archive'] = '../bad.tar.xz'
            elif change == 'missing-build':
                del data['builds']['arch']
            else:
                data['minimum_cider'] = '999.0'
            file.write_text(json.dumps(data))
            result = self.shell('CIDER_DARLING_RELEASE_FILE="$FIXTURE/release.json"\nresolve_ciderdarling_release',
                                PYTHONOPTIMIZE='1')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Invalid or incompatible', result.stderr)

    def shell(self, body, **environment):
        # A new session has no controlling terminal: prompts that read
        # /dev/tty fail instead of waiting for the person running the tests.
        return subprocess.run(["bash", "-c", '. "$1"\n' + body, "test", str(self.functions)],
                              env=dict(self.environment, **environment),
                              capture_output=True, text=True, timeout=20, start_new_session=True)

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

    def test_install_runtime_does_not_update_launcher_or_activate_runtime(self):
        file = self.base / 'config/ciderhq/runtime.json'
        original = {'schema_version': 1, 'runtime': 'regular',
                    'executable': '/usr/bin/darling', 'sysroot': '/usr/libexec/darling',
                    'prefix': str(self.base / 'saved-prefix')}
        runtime.save_selection(original, file)
        stub = '''
ensure_darling() {
  printf 'ensured:%s\\n' "$DARLING_RUNTIME"
  DARLING_EXECUTABLE=$CIDER_DARLING_INSTALL/bin/darling
  export DARLING_SYSROOT=$CIDER_DARLING_INSTALL/libexec/darling
}
do_install() { exit 91; }
install_tools() { exit 92; }
main --install-runtime --darling ciderdarling --yes
'''
        output = self.checked(stub)
        self.assertIn('ensured:ciderdarling', output)
        self.assertFalse((self.base / 'data/CiderHQ').exists())
        # Regular Darling stays selected; the new CiderDarling is remembered.
        saved = runtime.read_selection(file)
        self.assertEqual({key: saved[key] for key in runtime.SELECTION_KEYS},
                         {key: original[key] for key in runtime.SELECTION_KEYS})
        cider = runtime.remembered_runtimes(saved)['ciderdarling']
        pin = runtime.pinned_ciderdarling(ROOT / 'install.sh')['revision']
        self.assertEqual(cider['executable'], f'/opt/ciderdarling/{pin}/bin/darling')
        self.assertEqual(cider['prefix'], str(self.base / '.ciderdarling'))
        # An update of the selected CiderDarling switches to the new version
        # and keeps its prefix.
        old = {'schema_version': 1, 'runtime': 'ciderdarling',
               'executable': '/opt/ciderdarling/old/bin/darling',
               'sysroot': '/opt/ciderdarling/old/libexec/darling',
               'prefix': str(self.base / 'cider prefix')}
        runtime.save_selection(old, file, current=original)
        self.checked(stub)
        saved = runtime.read_selection(file)
        self.assertEqual(saved['executable'], f'/opt/ciderdarling/{pin}/bin/darling')
        self.assertEqual(saved['prefix'], old['prefix'])
        self.assertEqual(runtime.remembered_runtimes(saved)['regular']['prefix'], original['prefix'])
        # Without a saved choice nothing is selected behind the user's back.
        file.unlink()
        self.checked(stub)
        self.assertFalse(file.exists())

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
REPLACE_INCOMPLETE_RUNTIME=1
ciderdarling_matches() { return 1; }
sudo() { exit 90; }
build_darling_source() { exit 91; }
ensure_darling
''')
        self.assertEqual(result.returncode, 1)
        self.assertIn('incomplete or mismatched metadata', result.stdout)
        self.assertIn('not a CiderDarling version directory', result.stderr)
        self.assertEqual(sentinel.read_text(), 'existing runtime')

    def test_interrupted_pinned_install_is_replaced_only_when_allowed(self):
        body = '''
DARLING_RUNTIME=ciderdarling; load_darling_selection
CIDER_DARLING_INSTALL="$FIXTURE/versions/$CIDER_DARLING_REVISION"
ciderdarling_matches() { return 1; }
detect_package_manager() { printf apt-get; }
confirm_darling_build() { return 0; }
sudo() { printf 'sudo:%s\\n' "$*"; "$@"; }
build_darling_source() { printf 'built\\n'; }
'''
        pin = runtime.pinned_ciderdarling(ROOT / 'install.sh')['revision']
        root = self.base / 'versions' / pin
        (root / 'bin').mkdir(parents=True)
        (root / 'bin/partial').write_text('interrupted')
        # No terminal to ask in and no flag: kept, with the way out.
        result = self.shell(body + 'ensure_darling')
        self.assertEqual(result.returncode, 1)
        self.assertIn('--replace-incomplete-runtime', result.stderr)
        self.assertTrue((root / 'bin/partial').exists())
        output = self.checked(body + 'REPLACE_INCOMPLETE_RUNTIME=1\nensure_darling')
        self.assertIn(f'sudo:rm -rf -- {root}', output)
        self.assertIn('built', output)
        self.assertFalse(root.exists())
        # The command line flag sets the same switch.
        self.assertEqual(self.checked('''
banner() { :; }; do_install_runtime() { printf '%s' "$REPLACE_INCOMPLETE_RUNTIME"; }
main --install-runtime --darling ciderdarling --replace-incomplete-runtime''').strip(), '1')

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

    def prebuilt_fixture(self):
        """A release archive and manifest like CiderDarling's CI publishes."""
        import hashlib
        source = (ROOT / 'install.sh').read_text()
        def constant(name):
            return next(line.split('=', 1)[1] for line in source.splitlines() if line.startswith(name + '='))
        revision, series = constant('CIDER_DARLING_REVISION'), constant('CIDER_DARLING_MANIFEST')
        tree = self.base / 'tree' / revision
        (tree / 'bin').mkdir(parents=True)
        (tree / 'bin/darling').write_text('#!/bin/sh\nexit 0\n')
        (tree / 'bin/darling').chmod(0o4755)
        metadata = tree / 'libexec/darling/usr/share/ciderdarling/runtime.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({'schema_version': 1, 'name': 'CiderDarling', 'architecture': 'x86_64',
                                        'source_revision': revision, 'patch_manifest_sha256': series}))
        release = self.base / 'release'
        release.mkdir()
        name = f'ciderdarling-{revision}-x86_64-arch'
        subprocess.run(['tar', '-cJf', release / f'{name}.tar.xz', '-C', self.base / 'tree', revision], check=True)
        digest = hashlib.sha256((release / f'{name}.tar.xz').read_bytes()).hexdigest()
        (release / f'{name}.json').write_text(json.dumps({
            'schema_version': 1, 'name': 'CiderDarling', 'source_revision': revision,
            'patch_manifest_sha256': series, 'archive': f'{name}.tar.xz', 'archive_sha256': digest,
            'install_prefix': f'/opt/ciderdarling/{revision}', 'min_glibc': '2.17',
            'shared_libraries': ['libc.so.6'], 'native_libraries': ['libavcodec.so.99']}))
        return revision, digest

    PREBUILT_STUBS = '''
CIDER_DARLING_INSTALL="$FIXTURE/versions/$CIDER_DARLING_REVISION"
ciderdarling_prebuilt_flavor() { printf arch; }
install_ciderdarling_libraries() { printf 'libraries:%s\\n' "$1"; }
curl() { local output=''; while (($#)); do [[ $1 == -o ]] && { output=$2; shift; }; local url=$1; shift; done
  printf '%s\\n' "$url" >> "$FIXTURE/downloads"; cp -- "$FIXTURE/release/${url##*/}" "$output"; }
sudo() { local argument arguments=(); for argument in "$@"; do [[ $argument == --same-owner ]] || arguments+=("$argument"); done; "${arguments[@]}"; }
ciderdarling_client_is_setuid_root() { [[ -u $1 ]]; }
setcap() { printf 'setcap %s\\n' "$*" >> "$FIXTURE/commands"; }
'''

    def test_prebuilt_runtime_is_downloaded_verified_and_installed(self):
        revision, digest = self.prebuilt_fixture()
        output = self.checked(self.PREBUILT_STUBS + f'CIDER_DARLING_PREBUILT_ARCH={digest}\n'
                              'try_ciderdarling_prebuilt pacman && CIDER_DARLING_INSTALL="$CIDER_DARLING_INSTALL" ciderdarling_matches')
        self.assertIn('libraries:pacman', output)
        target = self.base / 'versions' / revision
        self.assertTrue((target / 'bin/darling').is_file())
        self.assertFalse((self.base / 'versions' / f'.partial-{revision}').exists())
        self.assertEqual(list((self.base / 'cache/ciderhq/installer').glob('prebuilt-*')), [])
        downloads = (self.base / 'downloads').read_text().split()
        self.assertEqual(downloads, [
            f'https://github.com/CiderHQ-org/CiderDarling/releases/download/bin-{revision[:12]}/'
            f'ciderdarling-{revision}-x86_64-arch.{suffix}' for suffix in ('tar.xz', 'json')])
        self.assertIn('cap_sys_admin=ep', (self.base / 'commands').read_text())

    def test_prebuilt_runtime_falls_back_or_stops_safely(self):
        revision, digest = self.prebuilt_fixture()
        # No pinned archive for this family, or compiling asked for: no download.
        for setup in ('CIDER_DARLING_PREBUILT_ARCH=', f'CIDER_DARLING_PREBUILT_ARCH={digest}; CIDER_DARLING_FROM_SOURCE=1'):
            result = self.shell(self.PREBUILT_STUBS + setup + '\ntry_ciderdarling_prebuilt pacman')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertFalse((self.base / 'downloads').exists())
        # A missing release builds from source; a wrong checksum stops setup.
        result = self.shell(self.PREBUILT_STUBS + f'CIDER_DARLING_PREBUILT_ARCH={digest}\n'
                            'curl() { return 22; }\ntry_ciderdarling_prebuilt pacman')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        result = self.shell(self.PREBUILT_STUBS + f'CIDER_DARLING_PREBUILT_ARCH={"0" * 64}\n'
                            'try_ciderdarling_prebuilt pacman || echo fell-back-to-source')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('fell-back-to-source', result.stdout)  # setup stops instead
        self.assertIn('does not match its pinned checksum', result.stdout + result.stderr)
        # Libraries of another generation: compile instead.
        result = self.shell(self.PREBUILT_STUBS + f'CIDER_DARLING_PREBUILT_ARCH={digest}\n'
                            'ciderdarling_missing_libraries() { printf libjpeg.so.8; }\ntry_ciderdarling_prebuilt pacman')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('libjpeg.so.8', result.stdout)
        self.assertFalse((self.base / 'versions' / revision).exists())

    def test_prebuilt_family_and_library_checks(self):
        release = self.base / 'os-release'
        cases = {'ID=cachyos\nID_LIKE=arch\n': 'arch', 'ID=fedora\n': ''}
        for text, expected in cases.items():
            release.write_text(text)
            output = self.checked('command() { [[ $2 == pacman ]]; }; ciderdarling_prebuilt_flavor',
                                  CIDER_OS_RELEASE=str(release))
            self.assertEqual(output, expected)
        manifest = self.base / 'manifest.json'
        manifest.write_text(json.dumps({'shared_libraries': ['libc.so.6'],
                                        'native_libraries': ['libavcodec.so.99', 'libnot-here.so.4']}))
        self.assertEqual(self.checked(f'ciderdarling_missing_libraries "{manifest}"').strip(), 'libnot-here.so.4')

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
mkdir -p "$XDG_CACHE_HOME/ciderhq/installer/darling-source-earlier/build"
build_darling_source apt-get
''', DARLING_BUILD_JOBS='7', CIDER_RUNTIME_LOG_RECORD=str(self.base / 'build-log'))
        # The build tree goes after a successful install, earlier ones before
        # a new build; the log stays where the launcher's record points.
        installer = self.base / 'cache/ciderhq/installer'
        self.assertEqual(list(installer.glob('darling-source-*')), [])
        log = Path((self.base / 'build-log').read_text().strip())
        self.assertEqual(log.parent, installer)
        self.assertRegex(log.name, r'^darling-build-\d{8}-\d{6}-\w+\.log$')
        self.assertIn('source-ready', log.read_text())
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        commands = (self.base / 'commands').read_text().splitlines()
        for argument in (f'-DCMAKE_INSTALL_PREFIX={self.base}/runtime', '-DCIDER_SHUTDOWN_ON_INSTALL=OFF',
                         '-DENABLE_METAL=OFF', '-DCIDER_APPLY_PATCHES=ON', '-DTARGET_i386=OFF'):
            self.assertIn(argument, commands)
        index = commands.index('--parallel')
        self.assertEqual(commands[index + 1], '7')
