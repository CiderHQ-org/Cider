"""Launcher helper bounds and skip behavior; all inputs and helper processes are authored."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from quadra import core, graphics, metal_preload
from session_fixture import bare_session

FAKE = r'''
import json, os, signal, subprocess, sys, time
mode=os.environ.get('PRELOAD_TEST_MODE','good')
if mode=='hang':
    child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
    with open(os.environ['PRELOAD_TEST_PIDS'],'w') as file: json.dump([os.getpid(),child.pid],file)
    def stop(_signal,_frame):
        child.wait(timeout=1)
        sys.exit(0)
    signal.signal(signal.SIGTERM,stop)
    print(json.dumps({'completed':0,'total':2,'failed':0}),flush=True)
    while True: time.sleep(.1)
if mode=='fail': sys.exit(2)
if mode=='orphan':
    child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(60)'],stdout=subprocess.PIPE)
    child.stdout.readline()
    with open(os.environ['PRELOAD_TEST_PIDS'],'w') as file: json.dump([os.getpid(),child.pid],file)
    sys.exit(0)
if mode=='stages':
    print(json.dumps({'phase':'libraries','completed':2,'total':2,'failed':0,'prepared':2,'stage_status':'complete'}),flush=True)
    print(json.dumps({'phase':'resources','completed':1,'total':1,'failed':0,'read_bytes':32,'stage_status':'complete'}),flush=True)
print('noise from a loader',flush=True)
print(json.dumps({'completed':0,'total':2,'failed':0}),flush=True)
print(json.dumps({'completed':2,'total':2,'failed':0,'status':'complete'}),flush=True)
'''


class MetalPreloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = dict(os.environ, MACOBLOX_METAL_SHADER_CACHE=str(self.root),
                                MACOBLOX_METAL_PRELOAD="1", MACOBLOX_METAL_PRELOAD_KEY="client-one")
        scope = hashlib.sha256(b"client-one").hexdigest()
        directory = self.root / "quadra-preload-v1"
        directory.mkdir()
        for index in range(2):
            (directory / f"pipeline-{scope}-{index:064x}.qmc").write_bytes(b"authored stub")
        self.helper = self.root / "helper.py"
        self.helper.write_text(FAKE)

    def test_empty_disabled_and_other_client_records_do_not_start_a_helper(self):
        for changes, expected in (({"MACOBLOX_METAL_PRELOAD": "0"}, "disabled"),
                                  ({"MACOBLOX_METAL_PRELOAD_KEY": "client-two"}, "empty")):
            with patch.object(metal_preload.subprocess, "Popen") as start:
                self.assertEqual(metal_preload.run("unused", {**self.environment, **changes})["status"], expected)
                start.assert_not_called()

    def test_progress_and_helper_failure_have_explicit_results(self):
        observations = []
        with patch.object(metal_preload, "__file__", str(self.helper)):
            result = metal_preload.run("unused", self.environment, progress=lambda *row: observations.append(row))
            self.assertEqual(result, {"status": "complete", "completed": 2, "total": 2, "failed": 0})
            self.assertEqual(observations[-1], (2, 2))
            result = metal_preload.run("unused", {**self.environment, "PRELOAD_TEST_MODE": "fail"})
            self.assertEqual(result["status"], "failed")

    def test_skip_ends_helper_and_its_descendant_before_returning(self):
        pids = self.root / "pids.json"
        cancel = threading.Event()
        def progress(_done, _total):
            if pids.exists():
                cancel.set()
        with patch.object(metal_preload, "__file__", str(self.helper)):
            result = metal_preload.run("unused", {**self.environment, "PRELOAD_TEST_MODE": "hang", "PRELOAD_TEST_PIDS": str(pids)}, progress, cancel, timeout=5)
        self.assertEqual(result["status"], "skipped")
        for pid in json.loads(pids.read_text()):
            self.assertFalse(Path(f"/proc/{pid}").exists(), pid)

    def test_timeout_returns_after_reaping_helper(self):
        with patch.object(metal_preload, "__file__", str(self.helper)):
            result = metal_preload.run("unused", self.environment, timeout=0)
        self.assertEqual(result["status"], "timeout")

    def test_first_launch_can_run_library_and_resource_stages_without_pipeline_records(self):
        progress = []
        with patch.object(metal_preload, "__file__", str(self.helper)):
            result = metal_preload.run("unused", {**self.environment, "MACOBLOX_METAL_PRELOAD_KEY": "new-client", "PRELOAD_TEST_MODE": "stages"},
                library_pack=self.root / "pack", resource_root=self.root,
                stage_progress=lambda *row: progress.append(row))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["stages"]["libraries"]["prepared"], 2)
        self.assertEqual(result["stages"]["resources"]["read_bytes"], 32)
        self.assertTrue(all(stage in {row[0] for row in progress} for stage in ("libraries", "resources", "pipelines")))

    def test_memory_pressure_skips_or_terminates_preparation(self):
        with patch.object(metal_preload.startup_preload, "available_memory", return_value=1), \
                patch.object(metal_preload.subprocess, "Popen") as start:
            self.assertEqual(metal_preload.run("unused", self.environment)["status"], "memory-limited")
            start.assert_not_called()
        with patch.object(metal_preload, "__file__", str(self.helper)), \
                patch.object(metal_preload.startup_preload, "resident_bytes", return_value=2 << 30):
            self.assertEqual(metal_preload.run("unused", self.environment)["status"], "memory-limited")

    def test_descendant_is_stopped_after_its_helper_leader_exits(self):
        pids = self.root / "orphan.json"
        with patch.object(metal_preload, "__file__", str(self.helper)):
            metal_preload.run("unused", {**self.environment, "PRELOAD_TEST_MODE": "orphan", "PRELOAD_TEST_PIDS": str(pids)}, timeout=2)
        child = json.loads(pids.read_text())[1]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                state = Path(f"/proc/{child}/stat").read_text().rsplit(")", 1)[1].split()[0]
            except FileNotFoundError:
                break
            if state == "Z":  # An adopted zombie cannot execute; only its new parent can reap it.
                break
            time.sleep(0.01)
        else:
            os.kill(child, 9)
            self.fail("preload descendant survived its helper's exit")

    def test_metal_settings_and_skip_reach_host_and_guest(self):
        session = bare_session(dict(core.DEFAULT_SETTINGS, renderer="metal", metal_diagnostics=True))
        session._metal_preload_skipped = True
        with patch.object(core, "host_vram_bytes", return_value=0), patch.object(core, "icon_argb_file", side_effect=OSError):
            host = session._graphics_environment()
            guest = dict(item.split("=",1) for item in session.shim_variables())
        for environment in (host, guest):
            self.assertEqual(environment["MACOBLOX_METAL_PRELOAD"], "1")
            self.assertEqual(environment["MACOBLOX_METAL_PRELOAD_IN_PROCESS"], "0")
            self.assertEqual(environment["MACOBLOX_METAL_DIAGNOSTICS"], "1")
        disabled = graphics.metal_environment("/a path/metal", "/a path/cache", preload=False)
        self.assertEqual(disabled["MACOBLOX_METAL_PRELOAD"], "0")
        self.assertEqual(disabled["MACOBLOX_METAL_PRELOAD_IN_PROCESS"], "0")
