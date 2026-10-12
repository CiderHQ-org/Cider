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

    def install_cider_metadata(self):
        path = self.cider / "libexec/darling/usr/share/ciderdarling/runtime.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "name": "CiderDarling",
                                    "architecture": "x86_64", "source_revision": "fixture"}))
        return path

    def discover(self, current=None, pinned=None, **environment):
        return runtime.installed_runtimes(current, dict(self.environment, **environment),
                                          self.selection, regular_clients=[self.cider / "bin/darling", self.stock / "bin/darling"],
                                          cider_directory=self.base / "versions", pinned=pinned)

    def test_discovery_keeps_client_root_and_provider_together(self):
        self.install_cider_metadata()
        choices = self.discover()
        self.assertEqual(set(choices), {"regular", "ciderdarling"})
        self.assertEqual(choices["regular"]["executable"], str(self.stock / "bin/darling"))
        self.assertEqual(choices["ciderdarling"]["sysroot"], str(self.cider / "libexec/darling"))

    def test_discovery_rejects_missing_clients_and_damaged_cider_metadata(self):
        path = self.install_cider_metadata()
        path.write_text("invalid")
        self.assertEqual(set(self.discover()), {"regular"})
        (self.stock / "bin/darling").unlink()
        self.assertEqual(self.discover(), {})

    def test_flatpak_has_no_host_runtime_switches(self):
        self.install_cider_metadata()
        self.assertEqual(self.discover(FLATPAK_ID="org.ciderhq.Cider"), {})

    def test_roundtrip_switch_preserves_both_custom_prefixes(self):
        self.install_cider_metadata()
        original = self.select("regular")
        original["prefix"] = str(self.base / "custom regular prefix")
        self.selection.write_text(json.dumps(original))
        cider = self.discover(original)["ciderdarling"]
        cider["prefix"] = str(self.base / "custom cider prefix")
        runtime.save_selection(cider, self.selection, current=original)
        regular = self.discover(cider)["regular"]
        self.assertEqual(regular["prefix"], original["prefix"])
        runtime.save_selection(regular, self.selection, current=cider)
        self.assertEqual(self.discover(regular)["ciderdarling"]["prefix"], cider["prefix"])
        self.assertEqual(runtime.read_selection(self.selection)["runtime"], "regular")
        self.assertEqual(self.selection.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.selection.parent.glob(".runtime-*")), [])

    def test_failed_atomic_switch_preserves_previous_selection(self):
        original = self.select()
        before = self.selection.read_bytes()
        target = dict(original, runtime="regular", executable=str(self.stock / "bin/darling"),
                      sysroot=str(self.stock / "libexec/darling"))
        with patch.object(runtime.os, "replace", side_effect=OSError("read-only directory")):
            with self.assertRaises(OSError):
                runtime.save_selection(target, self.selection, current=original)
        self.assertEqual(self.selection.read_bytes(), before)
        self.assertEqual(list(self.selection.parent.glob(".runtime-*")), [])

    def test_switch_remembers_initial_runtime_without_installer_config(self):
        self.install_cider_metadata()
        original = self.resolve()
        original["prefix"] = str(self.base / "legacy custom prefix")
        target = self.discover(original)["ciderdarling"]
        runtime.save_selection(target, self.selection, current=original)
        self.assertEqual(self.discover(target)["regular"]["prefix"], original["prefix"])

    def test_version_directory_discovery_prefers_saved_version(self):
        self.install_cider_metadata()
        current = self.select()
        newer = self.base / "versions/new-version"
        (newer / "bin").mkdir(parents=True)
        client = newer / "bin/darling"
        client.write_text("#!/bin/sh\nexit 0\n"); client.chmod(0o755)
        metadata = newer / "libexec/darling/usr/share/ciderdarling/runtime.json"
        metadata.parent.mkdir(parents=True)
        metadata.write_text((self.cider / "libexec/darling/usr/share/ciderdarling/runtime.json").read_text())
        choices = self.discover(current)
        self.assertEqual(choices["ciderdarling"]["executable"], current["executable"])
        (self.cider / "bin/darling").unlink()
        self.assertEqual(self.discover(current)["ciderdarling"]["executable"], str(client))

    def cider_version(self, name, revision):
        version = self.base / "versions" / name
        client = version / "bin/darling"
        client.parent.mkdir(parents=True)
        client.write_text("#!/bin/sh\nexit 0\n"); client.chmod(0o755)
        metadata = version / "libexec/darling/usr/share/ciderdarling/runtime.json"
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({"schema_version": 1, "name": "CiderDarling",
                                        "architecture": "x86_64", "source_revision": revision}))
        return client

    def test_pinned_version_wins_over_remembered_older_revision(self):
        pin = "a" * 40
        old = self.cider_version("b" * 40, "b" * 40)
        current = dict(self.select(), executable=str(old),
                       sysroot=str(old.parent.parent / "libexec/darling"))
        self.selection.write_text(json.dumps(current))
        self.assertEqual(self.discover(current, pinned=pin)["ciderdarling"]["executable"], str(old))
        new = self.cider_version(pin, pin)
        choice = self.discover(current, pinned=pin)["ciderdarling"]
        self.assertEqual(choice["executable"], str(new))
        # The selected prefix stays with the variant.
        self.assertEqual(choice["prefix"], current["prefix"])
        # An interrupted install (other metadata in the pinned directory) is
        # not preferred.
        metadata = new.parent.parent / "libexec/darling/usr/share/ciderdarling/runtime.json"
        metadata.write_text(json.dumps({"schema_version": 1, "name": "CiderDarling",
                                        "architecture": "x86_64", "source_revision": "c" * 40}))
        self.assertEqual(self.discover(current, pinned=pin)["ciderdarling"]["executable"], str(old))

    def test_pin_is_read_from_the_installer(self):
        pin = runtime.pinned_ciderdarling()
        self.assertRegex(pin["revision"], r"^[0-9a-f]{40}$")
        self.assertRegex(pin["manifest"], r"^[0-9a-f]{64}$")
        source = (Path(runtime.__file__).resolve().parents[2] / "install.sh").read_text()
        self.assertIn(f"CIDER_DARLING_REVISION={pin['revision']}\n", source)
        installer = self.base / "install.sh"
        for text in ("", "CIDER_DARLING_REVISION=$(cat pin)\nCIDER_DARLING_MANIFEST=" + "0" * 64,
                     "CIDER_DARLING_REVISION=" + "a" * 40 + "\n"):
            installer.write_text(text)
            self.assertIsNone(runtime.pinned_ciderdarling(installer))
        self.assertIsNone(runtime.pinned_ciderdarling(self.base / "missing.sh"))

    def test_remember_updates_only_the_matching_variant(self):
        regular, cider = self.select("regular"), self.select("ciderdarling")
        runtime.save_selection(regular, self.selection, current=cider)
        newer = dict(cider, executable="/opt/ciderdarling/new/bin/darling",
                     sysroot="/opt/ciderdarling/new/libexec/darling")
        self.assertTrue(runtime.remember_runtime(newer, self.selection))
        saved = runtime.read_selection(self.selection)
        self.assertEqual(saved["runtime"], "regular")
        self.assertEqual(runtime.remembered_runtimes(saved)["ciderdarling"]["executable"],
                         newer["executable"])
        runtime.save_selection(cider, self.selection, current=regular)
        runtime.remember_runtime(newer, self.selection)
        saved = runtime.read_selection(self.selection)
        self.assertEqual((saved["runtime"], saved["executable"], saved["prefix"]),
                         ("ciderdarling", newer["executable"], cider["prefix"]))
        self.assertEqual(runtime.remembered_runtimes(saved)["regular"]["prefix"], regular["prefix"])
        self.selection.unlink()
        self.assertFalse(runtime.remember_runtime(newer, self.selection))
        self.assertFalse(self.selection.exists())

    def test_inherited_server_log_variables_need_an_opt_in(self):
        inherited = {"DSERVER_LOG_STDERR": "1", "DSERVER_LOG_LEVEL": "debug", "KEEP": "1"}
        with patch.dict(os.environ, inherited, clear=True), \
                patch.object(core, "DARLING_RUNTIME", {"runtime": "ciderdarling"}):
            notes = []
            env = core.darling_environment(notes=notes)
            self.assertNotIn("DSERVER_LOG_STDERR", env)
            self.assertNotIn("DSERVER_LOG_LEVEL", env)
            self.assertEqual(env["KEEP"], "1")
            self.assertEqual(len(notes), 1)
            self.assertIn("DSERVER_LOG_LEVEL, DSERVER_LOG_STDERR", notes[0])
            # CiderDarling's verbose log setting asks for debug, not stderr.
            env = core.darling_environment({"cider_verbose_server_log": True})
            self.assertEqual(env["DSERVER_LOG_LEVEL"], "debug")
            self.assertNotIn("DSERVER_LOG_STDERR", env)
            with patch.object(core, "DARLING_RUNTIME", {"runtime": "regular"}):
                self.assertNotIn("DSERVER_LOG_LEVEL",
                                 core.darling_environment({"cider_verbose_server_log": True}))
        with patch.dict(os.environ, dict(inherited, CIDER_KEEP_DSERVER_LOG="1"), clear=True):
            notes = []
            env = core.darling_environment(notes=notes)
            self.assertEqual(env["DSERVER_LOG_STDERR"], "1")
            self.assertEqual(notes, [])

    def test_incomplete_cider_version_is_never_regular_darling(self):
        version = self.base / "versions/incomplete"
        client = version / "bin/darling"
        client.parent.mkdir(parents=True)
        client.write_text("#!/bin/sh\nexit 0\n"); client.chmod(0o755)
        (version / "libexec/darling").mkdir(parents=True)
        choices = runtime.installed_runtimes(environment=self.environment, selection_file=self.selection,
                                            regular_clients=[client], cider_directory=self.base / "versions")
        self.assertEqual(choices, {})
