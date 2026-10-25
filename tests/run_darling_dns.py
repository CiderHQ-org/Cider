#!/usr/bin/env python3
"""Check the production DNS import against Darling without public DNS.

The exact resolver section from libQuadraShims.m is compiled with a local
transport. Real Libinfo still performs hint validation and result allocation.
Only a newly created, unauthenticated test prefix is started or stopped.
The successful transport uses synthetic packets; a failed import may query
only 127.0.0.1, due to the test prefix's resolver configuration.

Run: python3 tests/run_darling_dns.py
If empty-prefix bootstrap is unsupported by the installed package, set
QUADRA_DNS_TEST_SYSTEM_TEMPLATE to an idle, initialized system prefix.
Only system overlay files and account metadata are copied, excluding Users.
"""
from pathlib import Path
import os
import shlex
import shutil
import stat
import subprocess
import tempfile
import time

project = Path(__file__).resolve().parents[1]
artifacts_name = os.environ.get('QUADRA_DNS_TEST_ARTIFACTS_DIR')
artifacts = Path(artifacts_name).resolve() if artifacts_name else None
if artifacts:
    artifacts.mkdir(parents=True, exist_ok=True)
scratch = Path(tempfile.mkdtemp(prefix='quadra-dns-test-', dir=artifacts or '/tmp'))
scratch.chmod(0o700)
sysroot = Path(os.environ.get('DARLING_SYSROOT', '/usr/libexec/darling'))
source = (project / 'libQuadraShims.m').read_text()
start = source.index('// Trace the exact resolver requests made by Roblox.')
last = 'DYLD_INTERPOSE(quadra_getaddrinfo, getaddrinfo)'
end = source.index(last, start) + len(last)
macros = []
for name in ('DYLD_INTERPOSE', 'QUADRA_NEXT'):
    at = source.index('#define ' + name + '(')
    macros.append(source[at:source.index('\n\n', at)])
adaptation = '''
#include "dns_concurrency.h"
extern void *quadra_dns_fixture_symbol(void *, const char *);
#define dlsym quadra_dns_fixture_symbol
#define RTLD_NEXT ((void *)-1)
static void write_str(const char *text) { (void)text; }
static void print_num(long long value) { (void)value; }
static int quadra_env_cached(const char *key, volatile int *cache) {
    (void)key; (void)cache; return 0;
}
static int quadra_is_blocked_telemetry(const char *node) { (void)node; return 0; }
int quadra_dns_resolve(const char *node, const char *service,
                         const void *hints, void **result) {
    (void)node; (void)service; (void)hints; (void)result; return -1;
}
void quadra_sleep_us(unsigned int micros) {
    struct { long seconds, nanoseconds; } delay = {micros / 1000000, (micros % 1000000) * 1000};
    long ignored;
    __asm__ volatile("syscall" : "=a"(ignored) : "a"(35L), "D"(&delay), "S"(0L)
                     : "rcx", "r11", "memory");
}
'''
interposer_source = scratch / 'production_dns.c'
interposer_source.write_text(adaptation + '\n'.join(macros) + '\n' + source[start:end] + '\n')
compiler = ['clang', '-target', 'x86_64-apple-darwin', '-fuse-ld=lld',
            '-isysroot', str(sysroot), '-mmacosx-version-min=11.0',
            '-O2', '-Wall', '-Wextra', '-Wno-unused-function',
            '-Werror=incompatible-function-pointer-types', '-I', str(project)]
library = scratch / 'dns_fixture.dylib'
binary = scratch / 'dns_fixture'
subprocess.run(compiler + ['-dynamiclib', '-Wl,-undefined,dynamic_lookup',
               str(interposer_source), str(project / 'tests/darling_dns_transport.c'),
               '-o', str(library)], check=True)
subprocess.run(compiler + [str(project / 'tests/darling_dns_test.c'), '-lresolv',
                          '-o', str(binary)], check=True)
prefix = Path(tempfile.mkdtemp(prefix='quadra-dns-prefix-', dir='/tmp'))
prefix.chmod(0o700)
# Some packaged Darling builds need their initialized system overlay even
# for an empty test. This optional template never copies Users, runtime logs,
# databases, session files, sockets, FIFOs, or prefix process markers.
template_name = os.environ.get('QUADRA_DNS_TEST_SYSTEM_TEMPLATE')
if template_name:
    template = Path(template_name).resolve(strict=True)
    def ignore_special(directory, names):
        ignored = set()
        for name in names:
            mode = os.lstat(Path(directory) / name).st_mode
            if stat.S_ISSOCK(mode) or stat.S_ISFIFO(mode) or name.startswith('.init') or name.startswith('.darlingserver'):
                ignored.add(name)
        return ignored
    for name in ('usr', 'System', 'Volumes', 'bin', 'sbin'):
        original = template / name
        if original.is_dir():
            shutil.copytree(original, prefix / name, symlinks=True, ignore=ignore_special)
        elif original.is_symlink():
            (prefix / name).symlink_to(os.readlink(original))
    for name in ('passwd', 'master.passwd', 'group', 'memberd.conf'):
        original = template / 'private/etc' / name
        if original.is_file():
            (prefix / 'private/etc').mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, prefix / 'private/etc' / name)
# shellspawn's Unix socket must be visible through the host upper layer as
# prefix/var/run. Start from empty directories, never session/runtime files.
for name in ('var/run', 'var/db', 'var/log', 'var/tmp/launchd',
             'private/var/run', 'private/var/log', 'private/tmp'):
    (prefix / name).mkdir(parents=True, exist_ok=True)
# Guard the negative import test too: an unredirected legacy query may reach
# only loopback, never the host's public resolver configuration.
resolver_directory = prefix / 'private/etc'
resolver_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
(resolver_directory / 'resolv.conf').write_text('nameserver 127.0.0.1\noptions timeout:1 attempts:1\n')
environment = dict(os.environ, DPREFIX=str(prefix))
for key in ('LD_PRELOAD', 'DYLD_INSERT_LIBRARIES', 'DYLD_LIBRARY_PATH'):
    environment.pop(key, None)
command = shlex.join(['env', 'DYLD_FORCE_FLAT_NAMESPACE=1',
                     'DYLD_INSERT_LIBRARIES=/Volumes/SystemRoot' + str(library),
                     '/Volumes/SystemRoot' + str(binary)])
log = scratch / 'runtime.log'
print('Unauthenticated DNS fixture artifacts:', scratch, flush=True)
try:
    deadline = time.monotonic() + 45
    while True:
        with log.open('w') as output:
            os.chmod(log, 0o600)
            process = subprocess.Popen(['darling', 'shell', '/bin/bash', '-c', command],
                                       env=environment, stdout=output, stderr=subprocess.STDOUT)
            try:
                status = process.wait(timeout=max(1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                status = 124
        if status == 0 or 'shellspawn.sock' not in log.read_text() or time.monotonic() + 1 >= deadline:
            break
        time.sleep(1)
    for line in log.read_text().splitlines():
        if line.startswith(('PASS ', 'FAIL ')):
            print(line, flush=True)
    print('DNS fixture exit:', status, flush=True)
    raise SystemExit(status)
finally:
    subprocess.run(['darling', 'shutdown'], env=environment, timeout=8,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if 'process' in locals():
        process.wait(timeout=5)
