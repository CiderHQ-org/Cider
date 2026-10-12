from pathlib import Path
import signal
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from macoblox import core
from session_fixture import bare_session


class ProcessScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base=Path(self.temporary.name)
        self.prefix=self.base/"selected prefix"
        context=patch.object(core, "DARLING_PREFIX", self.prefix)
        context.start(); self.addCleanup(context.stop)

    def mount(self, prefix, *, mounted=None, work=None):
        def escape(path): return str(path).replace("\\", "\\134").replace(" ", "\\040").replace("\t", "\\011").replace("\n", "\\012")
        return "12 1 0:20 / {} rw - overlay overlay rw,lowerdir=/darling,upperdir={},workdir={}\n".format(
            escape(prefix if mounted is None else mounted), escape(prefix), escape(str(prefix)+".workdir" if work is None else work))

    def test_server_prefix_uses_exact_argument_and_canonical_path(self):
        self.prefix.mkdir()
        alias=self.base/"alias"; alias.symlink_to(self.prefix)
        commands=[(10,["darlingserver",str(self.prefix),"1000"]),
                  (11,["darlingserver",str(self.prefix)+" other","1000"]),
                  (12,["python", "darlingserver",str(self.prefix)]),
                  (13,["/usr/bin/darlingserver",str(alias),"1000"])]
        with patch.object(core,"_user_commands",return_value=commands):
            self.assertEqual(core._darlingservers(),[10,13])
        with patch.object(core.os,"readlink",return_value=str(self.base)):
            self.assertTrue(core._server_for_prefix(10,["darlingserver","selected prefix"]))
        self.assertFalse(core._server_for_prefix(10,["darlingserver"]))

    def test_mountinfo_matches_exact_escaped_overlay(self):
        self.assertEqual(core._mountinfo_prefix(self.mount(self.prefix)), self.prefix)
        self.assertEqual(core._mountinfo_prefix("garbage\n"+self.mount(self.prefix)),self.prefix)
        tabbed=self.base/"with\ttab"
        self.assertEqual(core._mountinfo_prefix(self.mount(tabbed)),tabbed)

    def test_ambiguous_rootless_wrong_workdir_and_unrelated_mount_are_unknown(self):
        other=self.base/"other"
        for data in ("", "12 1 0:20 / / rw - ext4 root rw\n", self.mount(self.prefix, work=other),
                     self.mount(self.prefix,mounted=other),self.mount(self.prefix)+self.mount(other)):
            self.assertIsNone(core._mountinfo_prefix(data))

    def test_only_proven_selected_orphans_are_returned(self):
        processes=[(1,"orphan-selected"),(2,"orphan-other"),(3,"live"),(4,None),(5,"unknown")]
        prefixes={1:self.prefix,2:self.base/"other",5:None}
        with patch.object(core,"_user_commands",return_value=[(9,["darlingserver",str(self.base/"other")])]), \
                patch.object(core,"_mount_namespace",return_value="live"), \
                patch.object(core,"_darling_processes",return_value=processes), \
                patch.object(core,"_process_prefix",side_effect=lambda pid:prefixes[pid]):
            self.assertEqual(core._orphaned_darling_processes(),[1])

    def test_unreadable_process_scope_is_preserved(self):
        with patch.object(core.Path,"stat",side_effect=PermissionError("fixture")):
            self.assertFalse(core._process_in_prefix(1, {"selected"}))
        with patch.object(core.Path,"read_text",side_effect=PermissionError("fixture")):
            self.assertIsNone(core._process_prefix(1))

    def test_scoped_signals_use_stable_handles_and_close_every_descriptor(self):
        def open_descriptor(pid):
            if pid==3: raise ProcessLookupError("exited")
            return 100+pid
        with patch.object(core.os,"pidfd_open",side_effect=open_descriptor) as opened, \
                patch.object(core.signal,"pidfd_send_signal") as send, \
                patch.object(core.os,"close") as close, \
                patch.object(core.os,"kill") as numeric_kill, \
                patch.object(core,"_process_state",return_value="R"):
            core._terminate([1,2,1,3],wait=0,scope=lambda pid:pid==1)
        self.assertEqual([call.args[0] for call in opened.call_args_list],[1,2,3])
        self.assertEqual([call.args for call in send.call_args_list],[(101,signal.SIGTERM),(101,signal.SIGKILL)])
        self.assertEqual([call.args[0] for call in close.call_args_list],[102,101])
        numeric_kill.assert_not_called()

    def test_scope_failure_closes_handle_without_signaling(self):
        def rejected(_): raise PermissionError("scope disappeared")
        with patch.object(core.os,"pidfd_open",return_value=101), \
                patch.object(core.signal,"pidfd_send_signal") as send, \
                patch.object(core.os,"close") as close:
            with self.assertRaises(PermissionError): core._terminate([1],wait=0,scope=rejected)
        close.assert_called_once_with(101); send.assert_not_called()

    def test_dead_target_has_no_escalation(self):
        with patch.object(core.os,"pidfd_open",return_value=101), \
                patch.object(core.signal,"pidfd_send_signal") as send, \
                patch.object(core.os,"close") as close, \
                patch.object(core,"_process_state",return_value="Z"):
            core._terminate([1],wait=0,scope=lambda _:True)
        send.assert_called_once_with(101,signal.SIGTERM);close.assert_called_once_with(101)

    def test_restart_checks_scope_for_all_descendants_and_orphans(self):
        with patch.object(core,"_darlingservers",return_value=[10]), \
                patch.object(core,"_prefix_namespaces",return_value={"selected"}), \
                patch.object(core,"_with_descendants",return_value=[10,11,22]), \
                patch.object(core,"_container_processes",return_value=[12]), \
                patch.object(core,"_orphaned_darling_processes",return_value=[13]), \
                patch.object(core,"_process_in_prefix",side_effect=lambda pid, namespaces:pid!=22), \
                patch.object(core,"_terminate") as terminate, \
                patch.object(core,"clear_stale_darling"):
            core.restart_darling()
            processes,servers=terminate.call_args_list
            self.assertEqual(processes.args[0],[11,12,13,22])
            self.assertFalse(processes.kwargs["scope"](22))
            self.assertTrue(processes.kwargs["scope"](11))
            self.assertEqual(servers.args[0],[10])

    def test_startup_orphan_cleanup_rechecks_scope(self):
        with patch.object(core,"_orphaned_darling_processes",return_value=[13]), \
                patch.object(core,"_terminate") as terminate:
            self.assertEqual(core.clear_orphaned_darling(),1)
        terminate.assert_called_once()
        self.assertEqual(terminate.call_args.args,([13],))
        scope=terminate.call_args.kwargs["scope"]
        # Rechecked after the pidfd is open: still this user's mldr, outside
        # every live darlingserver's namespace, in the selected prefix.
        namespaces={13:"orphaned",20:"live"}
        def check(exe="/usr/libexec/darling/mldr", namespace="orphaned", prefix=None, uid=None):
            namespaces[13]=namespace
            with patch.object(core,"NOROOT_LIB",None), \
                    patch.object(core.Path,"stat",return_value=SimpleNamespace(st_uid=core.os.getuid() if uid is None else uid)), \
                    patch.object(core.os,"readlink",return_value=exe), \
                    patch.object(core,"_mount_namespace",side_effect=lambda pid:namespaces[pid]), \
                    patch.object(core,"_user_commands",return_value=[(20,["darlingserver","prefix"])]), \
                    patch.object(core,"_process_prefix",return_value=self.prefix.resolve() if prefix is None else prefix):
                return scope(13)
        self.assertTrue(check())
        self.assertFalse(check(exe="/usr/bin/bash"))
        self.assertFalse(check(namespace="live"))
        self.assertFalse(check(prefix=self.base/"other prefix"))
        self.assertFalse(check(uid=core.os.getuid()+1))

    def test_live_namespaces_require_selected_server_and_exclude_host_namespace(self):
        namespaces={core.os.getpid():"host",10:"selected",11:"host",12:None,13:"other"}
        with patch.object(core,"_mount_namespace",side_effect=lambda pid:namespaces[pid]), \
                patch.object(core.Path,"stat",return_value=SimpleNamespace(st_uid=core.os.getuid())), \
                patch.object(core.Path,"read_bytes",return_value=b"darlingserver\0fixture\0"), \
                patch.object(core,"_server_for_prefix",side_effect=lambda pid, argv:pid==10):
            self.assertEqual(core._prefix_namespaces([10,11,12,13]),{"selected"})

    def test_unknown_launcher_namespace_cannot_expand_cleanup(self):
        with patch.object(core,"_mount_namespace",return_value=None):
            self.assertEqual(core._prefix_namespaces([10]),set())

    def test_container_selection_preserves_other_prefix_and_unreadable_namespace(self):
        with patch.object(core,"_prefix_namespaces",return_value={"selected"}), \
                patch.object(core,"_darling_processes",return_value=[(10,"selected"),(11,"other"),(12,None)]):
            self.assertEqual(core._container_processes([1]),[10])

    def test_roblox_scan_is_prefix_scoped_and_uses_exact_executable_names(self):
        commands=[(1,["/Applications/RobloxPlayer"]),(2,["RobloxPlayer"]),
                  (3,["RobloxCrashHandler"]),(4,["RobloxCrashHandler.exe"]),
                  (5,["python","RobloxPlayer"])]
        with patch.object(core,"_prefix_namespaces",return_value={"selected"}), \
                patch.object(core,"_user_commands",return_value=commands), \
                patch.object(core,"_process_in_prefix",side_effect=lambda pid, ns:pid in (1,3)):
            self.assertEqual(core.roblox_pids(),[1,3])
            self.assertEqual(core.roblox_pids(("RobloxPlayer",)),[1])

    def test_fresh_roblox_scope_rejects_pid_reused_by_another_executable_or_prefix(self):
        with patch.object(core.Path,"read_bytes",return_value=b"launchd\0"), \
                patch.object(core,"_process_in_prefix",return_value=True) as scope:
            self.assertFalse(core._roblox_process_in_prefix(1,{"selected"}))
            scope.assert_not_called()
        with patch.object(core.Path,"read_bytes",return_value=b"RobloxPlayer\0"), \
                patch.object(core,"_process_in_prefix",return_value=False):
            self.assertFalse(core._roblox_process_in_prefix(1,{"selected"}))
        with patch.object(core.Path,"read_bytes",side_effect=PermissionError("fixture")):
            self.assertFalse(core._roblox_process_in_prefix(1,{"selected"}))

    def test_one_shot_crash_signal_rechecks_after_open_and_uses_pidfd(self):
        events=[]
        with patch.object(core.os,"pidfd_open",side_effect=lambda pid:events.append(("open",pid)) or pid+100), \
                patch.object(core.signal,"pidfd_send_signal",side_effect=lambda fd,sig:events.append(("send",fd,sig))), \
                patch.object(core.os,"close") as close, \
                patch.object(core.os,"kill") as numeric:
            def scope(pid): events.append(("scope",pid));return pid==1
            core._signal_scoped([1,2,1],signal.SIGKILL,scope)
        self.assertEqual(events,[("open",1),("scope",1),("send",101,signal.SIGKILL),("open",2),("scope",2)])
        self.assertEqual([call.args[0] for call in close.call_args_list],[101,102])
        numeric.assert_not_called()

    def test_missing_pidfd_support_preserves_targets_without_numeric_fallback(self):
        with patch.object(core.os,"pidfd_open"), \
                patch.object(core.os,"kill") as numeric, \
                patch.object(core.signal,"pidfd_send_signal") as send:
            del core.os.pidfd_open
            core._terminate([1],wait=0,scope=lambda _:True)
            core._signal_scoped([1],signal.SIGKILL,lambda _:True)
        numeric.assert_not_called();send.assert_not_called()

    def test_stop_and_crash_cleanup_have_fresh_scope_guards(self):
        with patch.object(core,"roblox_pids",return_value=[1,2]), \
                patch.object(core,"_prefix_namespaces",return_value={"selected"}), \
                patch.object(core,"_roblox_process_in_prefix",side_effect=lambda pid,*args:pid==1), \
                patch.object(core,"_terminate") as terminate, \
                patch.object(core,"_signal_scoped") as send:
            core.stop_roblox()
            self.assertTrue(terminate.call_args.kwargs["scope"](1))
            self.assertFalse(terminate.call_args.kwargs["scope"](2))
            core._kill_crash_handlers()
            self.assertEqual(send.call_args.args[:2],([1,2],signal.SIGKILL))
            self.assertTrue(send.call_args.args[2](1))
            self.assertFalse(send.call_args.args[2](2))

    def test_frontend_cleanup_preserves_unverified_descendants_and_never_kills_group(self):
        process=Mock(pid=10);process.poll.return_value=None
        with patch.object(core,"_prefix_namespaces",return_value={"selected"}), \
                patch.object(core,"_with_descendants",return_value=[10,11,22]), \
                patch.object(core,"_process_in_prefix",side_effect=lambda pid,ns:pid==11), \
                patch.object(core,"_terminate") as terminate, \
                patch.object(core.os,"killpg") as kill_group:
            core._terminate_frontend(process)
            descendants,frontend=terminate.call_args_list
            self.assertEqual(descendants.args[0],[11,22])
            self.assertTrue(descendants.kwargs["scope"](11))
            self.assertFalse(descendants.kwargs["scope"](22))
            self.assertTrue(frontend.kwargs["scope"](10))
            self.assertFalse(frontend.kwargs["scope"](99))
            process.poll.return_value=0
            self.assertFalse(frontend.kwargs["scope"](10))
        process.wait.assert_called_once_with(timeout=2);kill_group.assert_not_called()

    def test_session_finish_uses_scoped_roblox_and_owned_frontend_cleanup(self):
        session=bare_session()
        session.process=Mock();session.process.poll.return_value=None
        session.dns=None;session.audio=None
        with patch.object(core,"roblox_pids",return_value=[1]), \
                patch.object(core,"_terminate_roblox") as terminate, \
                patch.object(core,"_terminate_frontend") as frontend:
            session.finish()
        terminate.assert_called_once_with([1],wait=1)
        frontend.assert_called_once_with(session.process)

    def test_session_poll_drops_cached_pids_reused_in_other_prefix(self):
        session=bare_session()
        session.process=Mock();session.process.poll.return_value=None
        session.audio=None;session.seen_roblox=True;session.started_at=time.time()
        session.game_pids=[11,22];session.scanned_at=time.time();session.gone_since=None
        with patch.object(core.QUIT_SENTINEL.__class__,"exists",return_value=False), \
                patch.object(core,"_prefix_namespaces",return_value={"selected"}), \
                patch.object(core,"_process_state",return_value="R"), \
                patch.object(core,"_roblox_process_in_prefix",side_effect=lambda pid,*args:pid==11), \
                patch.object(core,"roblox_pids") as scan:
            self.assertIsNone(session.poll())
        self.assertEqual(session.game_pids,[11]);scan.assert_not_called()


if __name__ == "__main__": unittest.main()
