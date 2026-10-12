import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from macoblox import core, runtime


class RuntimeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.selection = self.base / "runtime.json"
        self.stock = self.base / "regular"
        self.cider = self.base / "cider darling"
        for directory in (self.stock, self.cider):
            (directory / "bin").mkdir(parents=True)
            (directory / "bin/darling").write_text("#!/bin/sh\nexit 0\n")
            (directory / "bin/darling").chmod(0o755)
            (directory / "libexec/darling").mkdir(parents=True)
        self.environment = {"PATH": str(self.stock / "bin")}

    def select(self, variant="ciderdarling"):
        directory = self.cider if variant == "ciderdarling" else self.stock
        data = {"schema_version": 1, "runtime": variant,
                "executable": str(directory / "bin/darling"),
                "sysroot": str(directory / "libexec/darling"),
                "prefix": str(self.base / ("cider-prefix" if variant == "ciderdarling" else "regular-prefix"))}
        self.selection.write_text(json.dumps(data))
        return data

    def resolve(self, **environment):
        return runtime.resolve_runtime(dict(self.environment, **environment), self.selection)

    def test_both_installed_explicit_choice_wins_over_path(self):
        for variant in ("regular", "ciderdarling"):
            selected = self.select(variant)
            resolved = self.resolve()
            for key in ("runtime", "executable", "sysroot", "prefix"):
                self.assertEqual(resolved[key], selected[key])

    def test_default_root_matches_client_on_path(self):
        resolved = self.resolve()
        self.assertEqual(resolved["runtime"], "regular")
        self.assertEqual(resolved["executable"], str(self.stock / "bin/darling"))
        self.assertEqual(resolved["sysroot"], str(self.stock / "libexec/darling"))

    def test_missing_selected_client_does_not_launch_stock(self):
        selected = self.select()
        Path(selected["executable"]).unlink()
        self.assertEqual(self.resolve()["executable"], selected["executable"])

    def test_build_environment_does_not_replace_selected_launch_root(self):
        selected = self.select()
        resolved = self.resolve(DARLING_SYSROOT=str(self.stock / "libexec/darling"))
        self.assertEqual(resolved["sysroot"], selected["sysroot"])

    def test_flatpak_ignores_host_choice_and_invalid_host_configuration(self):
        self.selection.write_text("invalid")
        resolved = self.resolve(FLATPAK_ID="org.ciderhq.Cider")
        self.assertEqual(resolved["sysroot"], "/app/libexec/darling")
        self.assertEqual(resolved["executable"], str(self.stock / "bin/darling"))

    def test_explicit_prefix_override_preserves_selected_executable(self):
        selected = self.select()
        resolved = self.resolve(DPREFIX=str(self.base / "custom-prefix"))
        self.assertEqual(resolved["executable"], selected["executable"])
        self.assertEqual(resolved["prefix"], str(self.base / "custom-prefix"))

    def test_malformed_unknown_and_relative_configuration_rejected(self):
        for data in ("invalid", "[]", '{"schema_version": 99}'):
            self.selection.write_text(data)
            with self.assertRaises(RuntimeError):
                self.resolve()
        for key in ("executable", "sysroot", "prefix"):
            selected = self.select()
            for bad in ("relative", "/path\nextra", 123):
                selected[key] = bad
                self.selection.write_text(json.dumps(selected))
                with self.assertRaises(RuntimeError):
                    self.resolve()

    def test_native_workqueue_switch_comes_only_from_selected_metadata(self):
        selected = self.select()
        data = {"schema_version": 1, "name": "CiderDarling", "source_revision": "fixture",
                "source_fixes": ["workqueue_stack_reset_x86_64"]}
        path = Path(selected["sysroot"]) / "usr/share/ciderdarling/runtime.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data))
        self.assertEqual(runtime.guest_variables(self.resolve()["metadata"]), ["MACOBLOX_NATIVE_WORKQUEUE=1"])
        self.select("regular")
        self.assertEqual(runtime.guest_variables(self.resolve()["metadata"]), [])
        self.assertEqual(runtime.guest_variables({"source_fixes": "workqueue_stack_reset_x86_64"}), [])

    def test_version_query_and_environment_use_selected_runtime_and_prefix(self):
        with patch.object(core, "DARLING_EXECUTABLE", str(self.cider / "bin/darling")), \
                patch.object(core, "DARLING_PREFIX", self.base / "cider-prefix"), \
                patch.object(core.subprocess, "run") as run:
            run.return_value.stdout = "selected\n"
            self.assertEqual(core.darling_version(), "selected")
            self.assertEqual(run.call_args.args[0], [str(self.cider / "bin/darling"), "--version"])
            self.assertEqual(core.darling_environment()["DPREFIX"], str(self.base / "cider-prefix"))

    def test_missing_tools_checks_selected_client_even_when_stock_is_installed(self):
        def which(program):
            return None if program == str(self.cider / "bin/missing") else "/fixture/bin/program"
        with patch.object(core, "DARLING_EXECUTABLE", str(self.cider / "bin/missing")), \
                patch.object(core, "DARLING_SYSROOT", self.cider / "libexec/darling"), \
                patch.object(core.shutil, "which", side_effect=which):
            self.assertIn("darling", core.missing_tools())

    def test_switching_runtime_invalidates_shim_build_stamp(self):
        with patch.object(core, "DARLING_SYSROOT", self.stock / "libexec/darling"):
            original = core._shim_sources_hash()
        with patch.object(core, "DARLING_SYSROOT", self.cider / "libexec/darling"):
            self.assertNotEqual(original, core._shim_sources_hash())
