"""First-launch setup pages, sharing the launcher's Roblox installer."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk, Pango  # noqa: E402

from . import __version__, core  # noqa: E402
from .i18n import _  # noqa: E402

_STYLE = """
.setup-wizard {
  background-image: linear-gradient(155deg, alpha(@accent_bg_color, 0.10), transparent 65%);
}
.setup-wizard .setup-title { font-size: 30px; font-weight: 800; letter-spacing: -0.6px; }
.setup-wizard .setup-subtitle { font-size: 15px; }
.setup-wizard .setup-eyebrow { font-size: 11px; font-weight: 700; letter-spacing: 1.2px; }
.setup-wizard .setup-step { padding: 16px; border-radius: 14px; }
.setup-wizard .setup-number {
  min-width: 30px; min-height: 30px; border-radius: 50%;
  background-color: alpha(@accent_bg_color, 0.15); color: @accent_color; font-weight: 700;
}
.setup-wizard .setup-note { padding: 14px 16px; border-radius: 12px; }
.setup-wizard .setup-action { min-height: 38px; padding-left: 24px; padding-right: 24px; }
.setup-wizard .setup-path { font-family: monospace; font-size: 11px; }
.setup-wizard .setup-progress { min-height: 8px; }
"""
_provider = None


def _install_style():
    global _provider
    if _provider is None:
        _provider = Gtk.CssProvider()
        _provider.load_from_data(_STYLE.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), _provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def _label(text, *, classes=(), centered=False):
    return Gtk.Label(label=_(text), wrap=True,
                     xalign=0.5 if centered else 0,
                     justify=Gtk.Justification.CENTER if centered else Gtk.Justification.LEFT,
                     css_classes=list(classes))


class SetupWizard(Adw.Bin):
    """A welcome, installation overview, progress and ready screen."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.installing = False
        self.install_failed = False
        _install_style()
        self.add_css_class("setup-wizard")
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Cider", css_classes=["heading"]))
        self.back = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text=_("Back"), visible=False)
        self.back.add_css_class("flat")
        self.back.connect("clicked", lambda *_args: self.show("welcome"))
        header.pack_start(self.back)
        header.pack_end(Gtk.Label(label=f"v{__version__}", css_classes=["caption", "dim-label"]))
        toolbar.add_top_bar(header)

        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
                               transition_duration=180, vexpand=True)
        self.pages.add_named(self._welcome(), "welcome")
        self.pages.add_named(self._overview(), "overview")
        self.pages.add_named(self._progress_page(), "progress")
        self.pages.add_named(self._ready(), "ready")
        toolbar.set_content(self.pages)
        self.set_child(toolbar)
        self.show("welcome")

    def _page(self, title, description, icon=None):
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                       margin_top=28, margin_bottom=28, margin_start=24, margin_end=24,
                       valign=Gtk.Align.CENTER, vexpand=True)
        if icon:
            image = Gtk.Image(icon_name=icon, pixel_size=56, halign=Gtk.Align.CENTER)
            image.add_css_class("accent")
            body.append(image)
        body.append(_label(title, classes=("setup-title",), centered=True))
        body.append(_label(description, classes=("setup-subtitle", "dim-label"), centered=True))
        clamp = Adw.Clamp(maximum_size=580, tightening_threshold=420, child=body)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=clamp)
        return scroll, body

    def _actions(self, primary, callback, secondary=None, secondary_callback=None):
        actions = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER, margin_top=6)
        if secondary:
            button = Gtk.Button(label=_(secondary), css_classes=["flat", "setup-action"])
            button.connect("clicked", secondary_callback)
            actions.append(button)
        button = Gtk.Button(label=_(primary), css_classes=["suggested-action", "pill", "setup-action"])
        button.connect("clicked", callback)
        actions.append(button)
        return actions, button

    def _welcome(self):
        page, body = self._page("Welcome to Cider", "Play Roblox on your Linux desktop.")
        logo = Gtk.Image.new_from_file(str(core.ICONS / "ciderhq-128.png"))
        logo.set_pixel_size(88)
        logo.set_halign(Gtk.Align.CENTER)
        body.prepend(logo)
        body.append(_label("A short setup downloads Roblox and gets it ready to launch. "
                           "You’ll sign in inside Roblox when you’re done.", centered=True))
        actions, _button = self._actions("Get started", lambda *_args: self.show("overview"),
                                        "Not now", lambda *_args: self.window.dismiss_setup())
        body.append(actions)
        body.append(_label("An independent launcher for Roblox on Linux",
                           classes=("caption", "dim-label"), centered=True))
        return page

    @staticmethod
    def _step(number, title, description):
        row = Gtk.Box(spacing=14, css_classes=["card", "setup-step"])
        row.append(Gtk.Label(label=str(number), valign=Gtk.Align.START, css_classes=["setup-number"]))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5, hexpand=True)
        text.append(_label(title, classes=("heading",)))
        text.append(_label(description, classes=("dim-label",)))
        row.append(text)
        return row

    def _overview(self):
        page, body = self._page("Here’s what happens next", "Everything you need to start playing, in one place.")
        steps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        steps.append(self._step(1, "Download Roblox", "Get the official macOS client directly from Roblox."))
        steps.append(self._step(2, "Prepare Darling", "Darling runs macOS apps on Linux. "
                                "Cider prepares the files Roblox needs."))
        steps.append(self._step(3, "Make it yours", "Sign in to Roblox, then choose your graphics, "
                                "mouse and launcher preferences in Settings."))
        body.append(steps)

        folders = Gtk.Expander(label=_("Where your files go"))
        locations = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=10,
                            margin_start=12, margin_end=12)
        for title, path in (("Roblox and its downloads", core.DATA_DIR),
                            ("Darling’s app environment", core.DARLING_PREFIX),
                            ("Launcher settings", core.CONFIG_DIR)):
            locations.append(_label(title, classes=("caption", "dim-label")))
            label = Gtk.Label(label=str(path), wrap=True, xalign=0, selectable=True,
                              css_classes=["setup-path"])
            label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            locations.append(label)
        folders.set_child(locations)
        body.append(folders)
        self.overview_note = _label("You can change launcher preferences at any time.",
                                    classes=("caption", "dim-label"), centered=True)
        body.append(self.overview_note)
        actions, self.install_button = self._actions("Install Roblox", self._start_install)
        body.append(actions)
        return page

    def _progress_page(self):
        page, body = self._page("Getting Roblox ready", "This can take a few minutes. "
                               "Keep Cider open while setup finishes.", "folder-download-symbolic")
        self.spinner = Gtk.Spinner(spinning=False, halign=Gtk.Align.CENTER)
        body.append(self.spinner)
        self.progress = Gtk.ProgressBar(css_classes=["setup-progress"], margin_top=8)
        body.append(self.progress)
        self.status = _label("Checking the latest Roblox version…", centered=True)
        body.append(self.status)
        self.error = Gtk.Label(wrap=True, xalign=0, selectable=True, visible=False,
                               css_classes=["setup-note", "card"])
        body.append(self.error)
        self.error_actions, self.retry_button = self._actions(
            "Try again", self._start_install, "Back", lambda *_args: self.show("overview"))
        self.error_actions.set_visible(False)
        body.append(self.error_actions)
        return page

    def _ready(self):
        page, body = self._page("You’re ready to play", "Roblox is installed. "
                               "Your next step is to open it and sign in.", "emblem-ok-symbolic")
        note = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                       css_classes=["card", "setup-note"])
        note.append(_label("Sign in inside Roblox", classes=("heading",)))
        note.append(_label("Use your Roblox account on the sign-in screen. "
                           "You don’t enter your password in this launcher."))
        note.append(_label("Quick Login is another option: get a code in Roblox, "
                           "then enter it on a phone or browser where you’re already signed in.",
                           classes=("dim-label",)))
        body.append(note)
        actions, _button = self._actions(
            "Launch Roblox", lambda *_args: self.window.complete_setup(launch=True),
            "Open launcher", lambda *_args: self.window.complete_setup())
        body.append(actions)
        body.append(_label("You can find this guide again in the launcher menu.",
                           classes=("caption", "dim-label"), centered=True))
        return page

    def show(self, name):
        self.pages.set_visible_child_name(name)
        self.back.set_visible(name == "overview")
        if name == "overview":
            installed = bool(core.installed_version())
            self.install_button.set_label(_("Continue") if installed else _("Install Roblox"))
            self.overview_note.set_label(_("Roblox is already installed. Your settings and sign-in are kept.")
                                         if installed else _("You can change launcher preferences at any time."))

    def _start_install(self, *_args):
        if self.installing:
            return
        if core.installed_version() and not self.install_failed:
            self.show("ready")
            return
        self.installing = True
        self.show("progress")
        self.error.set_visible(False)
        self.error_actions.set_visible(False)
        self.progress.set_fraction(0)
        self.spinner.set_spinning(True)
        self.status.set_label(_("Checking the latest Roblox version…"))
        missing = core.missing_tools()
        if missing:
            self._finished(RuntimeError(_("Required programs are missing: {programs}. "
                                         "Run the Cider installer to finish installing them, then try again.",
                                         programs=", ".join(missing))))
            return
        accepted = self.window.settings_page.check_updates(
            install=True, on_progress=self._progress, on_complete=self._finished)
        if accepted is False:
            self._finished(RuntimeError(_("Another operation is in progress. Wait for it to finish, then try again.")))

    def _progress(self, fraction, text):
        self.progress.set_fraction(max(0, min(1, fraction)))
        # Keep setup copy about the work the user is waiting for. Compiler and
        # framework details remain available in a failure's full error text.
        if fraction >= 0.97:
            text = _("Finishing setup…")
        elif fraction >= 0.94:
            text = _("Preparing Roblox to run on Linux…")
        elif fraction >= 0.9:
            text = _("Installing Roblox…")
        self.status.set_label(text)

    def _finished(self, error):
        self.installing = False
        self.spinner.set_spinning(False)
        if error:
            self.install_failed = True
            self.status.set_label(_("Setup couldn’t finish"))
            self.error.set_label(str(error) or repr(error))
            self.error.set_visible(True)
            self.error_actions.set_visible(True)
        else:
            self.install_failed = False
            self.progress.set_fraction(1)
            self.show("ready")
