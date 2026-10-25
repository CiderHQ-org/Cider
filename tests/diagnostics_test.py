from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from quadra import diagnostics


class DiagnosticSymbolsTests(unittest.TestCase):
    def test_overlay_mapping_uses_runtime_but_preserves_prefix_override(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix, runtime = Path(directory) / 'prefix', Path(directory) / 'runtime'
            relative = Path('usr/lib/system/libsystem_kernel.dylib')
            source, override = runtime / relative, prefix / relative
            source.parent.mkdir(parents=True)
            source.write_bytes(b'runtime library')
            roots = (prefix, runtime)
            self.assertEqual(diagnostics._host_path(str(override), roots), str(source))
            self.assertEqual(diagnostics._host_path('/' + str(relative), roots), str(source))
            override.parent.mkdir(parents=True)
            override.write_bytes(b'custom library')
            self.assertEqual(diagnostics._host_path(str(override), roots), str(override))
            host = Path(directory) / 'libhost.so'
            host.write_bytes(b'host library')
            self.assertEqual(diagnostics._host_path('/Volumes/SystemRoot' + str(host), roots), str(host))

    def test_objective_c_method_names_keep_spaces(self):
        output = '0000000000001010 T -[NSView viewDidMoveToWindow]\n0000000000001020 T _next\n'
        with patch.object(diagnostics, '_macho_layout', return_value=(0, [(0, 8192, 0, 8192)])), \
                patch.object(diagnostics.subprocess, 'run', return_value=Mock(stdout=output)):
            names = diagnostics._macho_names('AppKit', [0x1016], 'llvm-nm')
        self.assertEqual(names, {0x1016: '-[NSView viewDidMoveToWindow]+0x6'})
