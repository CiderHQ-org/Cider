"""Real setup/update regression with a saved restricted channel and stale log.

GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a python3 tests/roblox_update_ui.py
"""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import Mock, patch

temporary = tempfile.TemporaryDirectory()
base = Path(temporary.name)
os.environ.update(XDG_CONFIG_HOME=str(base / 'config'), XDG_CACHE_HOME=str(base / 'cache'),
                  XDG_DATA_HOME=str(base / 'data'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
threading.Thread.start = lambda self: None
from quadra import app, core
from gi.repository import Adw, Gio

application = Adw.Application(application_id='org.quadrahq.Quadra.UpdateTest',
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
application.register(None)
release = {'version': '0.744.0.7441080', 'clientVersionUpload': 'version-212bac6bdccd4673'}
stale = base / 'stale.log'
stale.write_text('[FLog::UpdateController] UpdateController: versionQueryUrl: '
                 + core.VERSION_URL + '/channel/zbeta\n'
                 '[FLog::UpdateController] version response: '
                 + json.dumps(dict(release, version='0.745.0.7450000'))
                 + '\nflow end: app_closed_for_update\n')
settings = dict(core.DEFAULT_SETTINGS, roblox_channel='zbeta', discord_rpc=False)

def response(url, **kwargs):
    assert url == core.VERSION_URL, url  # a gated request must fail this regression
    return io.BytesIO(json.dumps(release).encode())

with ExitStack() as context:
    context.enter_context(patch.object(core, 'load_settings', return_value=settings))
    context.enter_context(patch.object(core, 'save_settings'))
    installed = context.enter_context(patch.object(core, 'installed_version', return_value=None))
    context.enter_context(patch.object(core, 'roblox_pids', return_value=[]))
    context.enter_context(patch.object(core, 'missing_tools', return_value=[]))
    opener = context.enter_context(patch.object(core, 'open_public', side_effect=response))
    context.enter_context(patch.object(core, 'check_launcher_update', return_value=(False, '', '')))
    window = app.LauncherWindow(application)
    context.callback(window.destroy)
    window.last_log = stale
    page = window.settings_page
    context.enter_context(patch.object(page, '_in_thread', side_effect=lambda work, done: done(work(), None)))
    install = context.enter_context(patch.object(page, 'install_update', return_value=True))
    window.setup._start_install()
    assert window.setup.installing
    assert install.call_args.args == (release['clientVersionUpload'],)
    assert install.call_args.kwargs['channel'] == ''
    assert install.call_args.kwargs['expected_version'] == release['version']
    window.end(resume_pending=False)
    window.setup._finished(None)
    assert window.setup.pages.get_visible_child_name() == 'ready'
    installed.return_value = release['version']
    window._check_startup_update()
    assert opener.call_count == 2
    assert page.check_updates()  # ordinary manual checks use release too
    assert opener.call_count == 3

print('PASS: setup, startup and manual updates use public release with saved zbeta and a stale required-update log')
