"""Check relocation without running Darling or changing installed runtimes."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('relocate_runtime',
    Path(__file__).resolve().parents[1] / 'packaging/nix/relocate-runtime.py')
relocation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relocation)


class NixRuntimeTests(unittest.TestCase):
    def test_relocation_keeps_offsets_and_nested_guest_paths(self):
        prefix = '/opt/ciderdarling/' + 'a' * 40
        replacement = '/usr/lib64/quadrahq-runtime/' + 'a' * 30
        server = (prefix + '/bin/darlingserver').encode()
        loader = (prefix + '/libexec/darling/usr/libexec/darling/mldr').encode()
        original = b'\x7fELF\0' + server + b'\0' + loader + b'\0untouched\0'
        result = relocation.relocate(original, prefix, replacement)
        self.assertEqual(len(result), len(original))
        self.assertIn((replacement + '/bin/darlingserver\0').encode(), result)
        self.assertIn((replacement + '/libexec/darling/usr/libexec/darling/mldr\0').encode(), result)
        self.assertEqual(result.index(b'untouched'), original.index(b'untouched'))

    def test_guest_install_names_are_preserved(self):
        original = b'/System/Library/Frameworks/AppKit.framework/AppKit\0/usr/lib/libSystem.B.dylib\0'
        self.assertEqual(relocation.relocate(original, '/opt/ciderdarling/' + 'a' * 40,
                                            '/usr/lib64/quadrahq-runtime/' + 'a' * 30), original)

    def test_shortening_paths_would_break_compiled_string_lengths(self):
        with self.assertRaises(ValueError):
            relocation.relocate(b'/opt/ciderdarling/revision\0', '/opt/ciderdarling/revision', '/usr')

    @unittest.skipUnless(shutil.which('clang'), 'requires clang')
    def test_rootless_copy_can_write_nix_store_modes_without_changing_other_programs(self):
        source = Path(__file__).resolve().parents[1] / 'flatpak/darling-noroot.c'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / 'noroot.so'
            subprocess.run(['clang', '-shared', '-fPIC', '-O2', '-DMACOBLOX_NIX_STORE',
                            str(source), '-ldl', '-o', str(library)], check=True, capture_output=True)
            probe = root / 'permissions.c'
            probe.write_text('''
#include <stdlib.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
int main(int argc, char **argv) {
    struct stat info;
    if (argc != 3 || mkdir(argv[1], 0555) || stat(argv[1], &info)) return 1;
    if (!!(info.st_mode & 0200) != atoi(argv[2])) return 2;
    if (chmod(argv[1], 0555) || stat(argv[1], &info)) return 3;
    if (!!(info.st_mode & 0200) != atoi(argv[2])) return 4;
    if (fchmodat(-1, argv[1], 0555, 0) || stat(argv[1], &info)) return 5;
    if (!!(info.st_mode & 0200) != atoi(argv[2])) return 6;
    int fd = open(argv[1], O_RDONLY | O_DIRECTORY);
    if (fd < 0 || fchmod(fd, 0555) || fstat(fd, &info)) return 7;
    close(fd);
    return !!(info.st_mode & 0200) != atoi(argv[2]);
}
''')
            server = root / 'darlingserver'
            subprocess.run(['clang', str(probe), '-o', str(server)], check=True, capture_output=True)
            ordinary = root / 'ordinary-program'
            shutil.copy2(server, ordinary)
            env = dict(os.environ, LD_PRELOAD=str(library))
            subprocess.run([str(server), str(root / 'prefix'), '1'], env=env, check=True,
                           capture_output=True, timeout=5)
            subprocess.run([str(ordinary), str(root / 'ordinary'), '0'], env=env, check=True,
                           capture_output=True, timeout=5)
