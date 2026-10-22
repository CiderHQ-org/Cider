"""Switchable Grid, native GNOME and aubree.lat monochrome appearances.

Pure black behind a slowly drawn field of grey lines, a thin top bar, and
square "windows" with a small title bar in mono. No hue anywhere: state is
carried by filled against hollow, by brightness, and always by a text label
next to it. Archivo for the interface, JetBrains Mono for titles, versions
and other small facts (both ship in assets/fonts, SIL OFL).

Everything here is presentation: the settings pages keep their own widgets
and are only restyled by the stylesheet.
"""

import ctypes
import math
import random
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, GLib, Graphene, Gtk, Pango  # noqa: E402

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

UI_FONT = '"Archivo", "Adwaita Sans", "Inter", "Cantarell", sans-serif'
MONO_FONT = '"JetBrains Mono", "Adwaita Mono", "Source Code Pro", monospace'

# The palette of the site's stylesheet, by the same names.
NIGHT = "#000000"
CHROME = "#0a0a0a"
SURFACE = "#121212"
RAISE = "#1c1c1c"
LINE = "#2f2f2f"
LINE_LO = "#1e1e1e"
TEXT = "#e8e8e8"
DIM = "#9a9a9a"
FAINT = "#5c5c5c"
ACCENT = "#f0f0f0"
ACCENT2 = "#bdbdbd"
WARN = "#8a8a8a"
FOCUS_LINE = "#4d4d4d"

_NAMED_COLORS = {
    "window_bg_color": NIGHT, "window_fg_color": TEXT,
    "view_bg_color": CHROME, "view_fg_color": TEXT,
    "headerbar_bg_color": CHROME, "headerbar_fg_color": TEXT,
    "headerbar_border_color": LINE_LO, "headerbar_backdrop_color": CHROME,
    "headerbar_shade_color": "rgba(0, 0, 0, 0)", "headerbar_darker_shade_color": "rgba(0, 0, 0, 0)",
    "sidebar_bg_color": CHROME, "sidebar_fg_color": TEXT, "sidebar_backdrop_color": CHROME,
    "sidebar_shade_color": "rgba(0, 0, 0, 0)", "sidebar_border_color": LINE_LO,
    "secondary_sidebar_bg_color": CHROME, "secondary_sidebar_fg_color": TEXT,
    "card_bg_color": "rgba(30, 30, 30, 0.4)", "card_fg_color": TEXT, "card_shade_color": LINE_LO,
    "popover_bg_color": CHROME, "popover_fg_color": TEXT, "popover_shade_color": "rgba(0, 0, 0, 0)",
    "dialog_bg_color": SURFACE, "dialog_fg_color": TEXT,
    "thumbnail_bg_color": RAISE, "thumbnail_fg_color": TEXT,
    "accent_bg_color": ACCENT, "accent_fg_color": NIGHT, "accent_color": ACCENT,
    "destructive_bg_color": RAISE, "destructive_fg_color": TEXT, "destructive_color": TEXT,
    "success_bg_color": ACCENT, "success_fg_color": NIGHT, "success_color": ACCENT,
    "warning_bg_color": ACCENT2, "warning_fg_color": NIGHT, "warning_color": ACCENT2,
    "error_bg_color": RAISE, "error_fg_color": TEXT, "error_color": TEXT,
    "shade_color": "rgba(0, 0, 0, 0.5)", "scrollbar_outline_color": "rgba(0, 0, 0, 0)",
}

_CSS = """
* { border-radius: 0; }

window, popover, tooltip {
  font-family: %(ui)s;
  font-size: 13.5px;
  color: %(text)s;
}
window.background, window.csd { background-color: %(night)s; }
window.csd, window.csd.maximized { box-shadow: 0 0 0 1px %(line)s; }

selection { background-color: rgba(240, 240, 240, 0.26); color: #ffffff; }

*:focus-visible { outline: 2px solid %(accent)s; outline-offset: 2px; }

/* ── top bar ────────────────────────────────────────────── */

.topbar {
  min-height: 30px;
  padding: 0 4px 0 10px;
  background-color: rgba(10, 10, 10, 0.86);
  border-bottom: 1px solid %(line_lo)s;
  font-size: 12px;
}
.bar-host {
  font-family: %(mono)s;
  font-size: 11.5px;
  letter-spacing: 0.02em;
  color: %(accent)s;
  padding: 3px 8px;
}
.bar-item { color: %(dim)s; padding: 3px 8px; }
.bar-mono {
  font-family: %(mono)s;
  font-size: 11.5px;
  font-feature-settings: "tnum";
  color: %(faint)s;
  padding: 3px 8px;
}
.bar-mono.bright { color: %(text)s; }

.topbar windowcontrols { margin-left: 4px; }
.topbar windowcontrols > button {
  min-width: 20px;
  min-height: 20px;
  padding: 0;
  margin: 0 1px;
  border: none;
  background: none;
  color: %(faint)s;
}
.topbar windowcontrols > button > image { background: none; padding: 2px; }
.topbar windowcontrols > button:hover { background-color: %(raise_)s; color: %(text)s; }
.topbar windowcontrols > button.close:hover { background-color: rgba(255, 255, 255, 0.2); }

/* filled against hollow first, brightness second, and a label beside it */
.dot {
  min-width: 5px;
  min-height: 5px;
  border: 1px solid %(faint)s;
  background-color: transparent;
}
.dot.on {
  background-color: %(accent)s;
  border-color: %(accent)s;
  box-shadow: 0 0 6px rgba(240, 240, 240, 0.8);
}
.dot.busy { background-color: %(warn)s; border-color: %(warn)s; }
.dot.missing { background-color: transparent; border-color: %(text)s; }

/* ── windows ────────────────────────────────────────────── */

.win {
  background-color: rgba(18, 18, 18, 0.82);
  border: 1px solid %(line)s;
  box-shadow: 0 10px 34px rgba(0, 0, 0, 0.5);
  transition: border-color 160ms ease, box-shadow 160ms ease;
}
.win:hover, .win:focus-within {
  border-color: %(focus)s;
  box-shadow: 0 0 0 1px rgba(240, 240, 240, 0.16), 0 16px 48px rgba(0, 0, 0, 0.62);
}
.win-bar {
  min-height: 30px;
  padding: 0 6px 0 11px;
  background-color: rgba(10, 10, 10, 0.72);
  border-bottom: 1px solid %(line_lo)s;
}
.win-title {
  font-family: %(mono)s;
  font-size: 11.5px;
  letter-spacing: 0.02em;
  color: %(faint)s;
  transition: color 160ms ease;
}
.win:hover .win-title, .win:focus-within .win-title { color: %(accent)s; }
.win-note { font-family: %(mono)s; font-size: 10.5px; color: %(faint)s; padding-right: 5px; }
.win-body.padded { padding: 14px 15px; }

/* ── play window ────────────────────────────────────────── */

.pfp { border: 1px solid %(line)s; background-color: %(raise_)s; }
.about-name { font-size: 19px; font-weight: 600; letter-spacing: -0.015em; color: #ffffff; }
.about-version { font-family: %(mono)s; font-size: 11.5px; color: %(accent2)s; }
.about-live { font-size: 11.5px; color: %(faint)s; }

.fact { padding: 5px 0; }
.fact-name { font-size: 12.5px; color: %(text)s; }
.fact-note {
  font-family: %(mono)s;
  font-size: 10.5px;
  font-feature-settings: "tnum";
  color: %(faint)s;
}
.rule { min-height: 1px; background-color: %(line_lo)s; margin: 12px 0; }

/* ── link lists (the menu window) ───────────────────────── */

.sect {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: %(faint)s;
  margin: 12px 0 5px;
}
button.link {
  min-height: 0;
  padding: 5px 8px;
  margin: 0 -8px 1px;
  border: none;
  background: none;
  box-shadow: none;
  color: %(text)s;
  font-size: 13px;
  font-weight: 400;
  transition: background-color 120ms, color 120ms;
}
button.link:hover { background-color: %(raise_)s; color: %(accent)s; }
button.link:disabled { opacity: 0.45; }
button.link.current { background-color: rgba(200, 200, 200, 0.1); }
button.link.current .link-title { color: %(accent2)s; }
.link-note { font-family: %(mono)s; font-size: 10.5px; color: %(faint)s; }
button.link:hover .link-note { color: %(dim)s; }

/* ── console ────────────────────────────────────────────── */

.console { font-family: %(mono)s; font-size: 12.5px; padding: 18px 18px 14px; }
.console label { font-family: %(mono)s; font-size: 12.5px; }
.console .st { color: %(faint)s; }
.console .st.ok { color: %(accent)s; }
.console .st.wait { color: %(warn)s; }
.console .st.failed { color: %(text)s; }
.console .msg { color: #c2c2c2; }
.console .plain .msg { color: #7a7a7a; }
.console .prompt { color: %(accent)s; margin-top: 14px; }

/* ── buttons ────────────────────────────────────────────── */

button {
  padding: 5px 13px;
  border: 1px solid %(line)s;
  background-color: %(raise_)s;
  background-image: none;
  box-shadow: none;
  color: %(text)s;
  font-size: 12.5px;
  font-weight: 400;
  transition: border-color 140ms, color 140ms, background-color 140ms;
}
button:hover { border-color: %(accent)s; color: %(accent)s; background-color: %(raise_)s; }
button:active, button:checked { background-color: rgba(240, 240, 240, 0.12); color: %(accent)s; }
button:disabled { opacity: 0.45; }
button.suggested-action {
  background-color: rgba(240, 240, 240, 0.14);
  border-color: rgba(240, 240, 240, 0.4);
  color: %(accent)s;
}
button.suggested-action:hover { background-color: rgba(240, 240, 240, 0.22); }
/* hollow and bright: it takes something away, said by its label */
button.destructive-action { background-color: transparent; border-color: %(text)s; color: %(text)s; }
button.destructive-action:hover { background-color: rgba(240, 240, 240, 0.12); }
button.flat, button.image-button.flat, menubutton.flat > button {
  background-color: transparent;
  border-color: transparent;
  color: %(dim)s;
}
button.flat:hover, menubutton.flat > button:hover { background-color: %(raise_)s; border-color: transparent; color: %(text)s; }
button.flat:checked { background-color: rgba(240, 240, 240, 0.12); color: %(accent)s; }
button.image-button { padding: 5px 7px; }
button.flat.image-button, button.flat.toggle.image-button { min-width: 18px; min-height: 18px; padding: 4px 6px; }
button.big { padding: 9px 13px; font-size: 13.5px; font-weight: 500; }

/* tabs inside a window, set like the site's tags */
button.tab {
  font-family: %(mono)s;
  font-size: 10.5px;
  padding: 2px 8px;
  margin-right: 5px;
  background-color: %(raise_)s;
  border: 1px solid %(line_lo)s;
  color: %(dim)s;
}
button.tab:hover { border-color: %(focus)s; color: %(text)s; }
button.tab:checked {
  background-color: rgba(240, 240, 240, 0.14);
  border-color: rgba(240, 240, 240, 0.4);
  color: %(accent)s;
}
.tabs { padding: 12px 15px 2px; }

/* ── settings rows ──────────────────────────────────────── */

preferencespage, preferencespage > scrolledwindow, preferencespage viewport,
toolbarview, toolbarview > .top-bar, toolbarview > .bottom-bar, stack, viewport, scrolledwindow,
statuspage, toastoverlay, clamp {
  background-color: transparent;
  background-image: none;
  box-shadow: none;
}
preferencespage > scrolledwindow > viewport > clamp > box { margin: 14px 15px; border-spacing: 16px; }

preferencesgroup > box > box.header { margin-bottom: 7px; }
preferencesgroup > box > box.header label.title,
preferencesgroup > box > box.header label.heading {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: %(faint)s;
}
preferencesgroup > box > box.header > box.labels > label.body,
preferencesgroup > box > box.header label.description,
preferencespage > scrolledwindow > viewport > clamp > box > label.description {
  font-size: 12px;
  color: %(dim)s;
  opacity: 1;
}

list.boxed-list, list.boxed-list-separate > row, .card {
  background-color: rgba(30, 30, 30, 0.4);
  border: 1px solid %(line_lo)s;
  box-shadow: none;
  color: %(text)s;
}
list.boxed-list > row {
  background-color: transparent;
  border-bottom: 1px solid %(line_lo)s;
  outline-offset: -2px;
}
list.boxed-list > row:last-child { border-bottom: none; }
list.boxed-list > row.activatable:hover { background-color: %(raise_)s; }
list.boxed-list > row.activatable:active { background-color: rgba(240, 240, 240, 0.08); }
row .title { font-size: 13px; font-weight: 400; color: %(text)s; }
row .subtitle { font-size: 11.5px; color: %(dim)s; opacity: 1; }
row.mono-subtitle .subtitle { font-family: %(mono)s; font-size: 10.5px; }
row.error .title { color: #ffffff; font-weight: 600; }
row.expander > box > list > row { background-color: transparent; }
row > box.header { min-height: 44px; }
.dim-label, .dimmed { color: %(dim)s; opacity: 1; }
.caption { font-size: 11.5px; }
.heading { font-weight: 600; }
.numeric { font-family: %(mono)s; font-size: 11.5px; font-feature-settings: "tnum"; }

switch {
  min-width: 0;
  min-height: 0;
  padding: 2px;
  background-color: transparent;
  background-image: none;
  border: 1px solid %(faint)s;
  box-shadow: none;
}
switch > slider {
  min-width: 13px;
  min-height: 9px;
  margin: 0;
  background-color: %(faint)s;
  background-image: none;
  border: none;
  box-shadow: none;
}
switch > image { -gtk-icon-size: 9px; min-width: 0; min-height: 0; margin: 0; padding: 0; opacity: 0; }
switch:hover { border-color: %(dim)s; }
switch:checked { background-color: rgba(240, 240, 240, 0.14); border-color: %(accent)s; }
switch:checked > slider { background-color: %(accent)s; }
switch:disabled { opacity: 0.45; }

entry, spinbutton, searchbar entry, text.search, row.entry text {
  background-color: rgba(0, 0, 0, 0.45);
  background-image: none;
  border: 1px solid %(line_lo)s;
  box-shadow: none;
  color: %(text)s;
  caret-color: %(accent)s;
  outline-offset: 2px;
}
entry:focus-within, spinbutton:focus-within { border-color: %(focus)s; }
entry > text > placeholder { color: %(faint)s; }
spinbutton { min-height: 26px; }
spinbutton > text {
  font-family: %(mono)s;
  font-size: 11.5px;
  font-feature-settings: "tnum";
  background: none;
  border: none;
  min-width: 46px;
}
spinbutton > button, row.spin spinbutton > button {
  min-width: 22px;
  min-height: 22px;
  padding: 0;
  margin: 1px;
  border: none;
  background-color: transparent;
  color: %(dim)s;
}
spinbutton > button:hover { background-color: %(raise_)s; color: %(text)s; }
row.spin spinbutton { background-color: transparent; border: none; }
row.spin spinbutton > button { border: 1px solid %(line_lo)s; background-color: %(raise_)s; margin-left: 5px; }
row.entry { background-color: transparent; }
row.entry text { border: none; background: none; }

dropdown > button, row.combo dropdown > button { padding: 4px 9px; }
row.combo dropdown > button { background: none; border-color: transparent; color: %(text)s; }
checkbutton > check, checkbutton > radio {
  min-width: 13px;
  min-height: 13px;
  background-color: transparent;
  background-image: none;
  border: 1px solid %(faint)s;
  box-shadow: none;
  color: %(night)s;
}
checkbutton > check:checked, checkbutton > radio:checked { background-color: %(accent)s; border-color: %(accent)s; }

scale > trough { min-height: 3px; background-color: %(line_lo)s; border: none; }
scale > trough > highlight { background-color: %(dim)s; min-height: 3px; }
scale > trough > slider {
  min-width: 11px;
  min-height: 11px;
  margin: -4px;
  background-color: %(accent)s;
  background-image: none;
  border: none;
  box-shadow: none;
}

progressbar > trough { min-height: 2px; background-color: %(line_lo)s; border: none; }
progressbar > trough > progress { min-height: 2px; background-color: %(accent)s; background-image: none; border: none; }
progressbar > text { font-family: %(mono)s; font-size: 10.5px; color: %(faint)s; }

scrollbar { background-color: transparent; border: none; }
scrollbar > range > trough { background-color: transparent; }
scrollbar > range > trough > slider {
  min-width: 5px;
  min-height: 5px;
  margin: 2px;
  background-color: %(line_lo)s;
  border: none;
}
scrollbar > range > trough > slider:hover { background-color: %(line)s; }
undershoot.top, undershoot.bottom, overshoot.top, overshoot.bottom { background: none; box-shadow: none; }

separator { background-color: %(line_lo)s; min-height: 1px; min-width: 1px; }

avatar, avatar > image, avatar > label { border-radius: 0; }
avatar { border: 1px solid %(line)s; background-color: %(raise_)s; background-image: none; color: %(dim)s; }

/* ── logs ───────────────────────────────────────────────── */

textview { font-family: %(mono)s; font-size: 12px; background-color: transparent; color: #d4d4d4; }
textview > text { background-color: transparent; color: #d4d4d4; }
.log-tools { padding: 8px 10px; border-bottom: 1px solid %(line_lo)s; }

/* ── floating things ────────────────────────────────────── */

popover > contents, popover.menu > contents {
  padding: 5px;
  background-color: rgba(10, 10, 10, 0.96);
  border: 1px solid %(line)s;
  box-shadow: 0 14px 40px rgba(0, 0, 0, 0.6);
  color: %(dim)s;
}
popover > arrow { background-color: rgba(10, 10, 10, 0.96); border: 1px solid %(line)s; }
popover modelbutton, popover listview > row, popover list > row {
  padding: 6px 10px;
  min-height: 0;
  color: %(dim)s;
  font-size: 12.5px;
}
popover modelbutton:hover, popover listview > row:hover, popover list > row:hover,
popover listview > row:selected {
  background-color: %(raise_)s;
  color: %(text)s;
}

toast {
  background-color: rgba(10, 10, 10, 0.96);
  border: 1px solid %(line)s;
  box-shadow: 0 14px 40px rgba(0, 0, 0, 0.6);
  color: %(text)s;
  font-size: 12.5px;
  margin-bottom: 14px;
}
toast label, toast .heading { font-weight: 400; }
toast button { border: none; background: none; }

tooltip, tooltip.background {
  background-color: rgba(10, 10, 10, 0.96);
  border: 1px solid %(line)s;
  box-shadow: none;
  color: %(dim)s;
  font-size: 12px;
  padding: 4px 8px;
}

dialog.alert sheet, dialog sheet, window.dialog, window.messagedialog, .dialog-contents {
  background-color: %(surface)s;
  border: 1px solid %(line)s;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.62);
  color: %(text)s;
}
dialog.alert .heading, .alert .title-2, .title-2 { font-size: 15px; font-weight: 600; color: #ffffff; }
dialog.alert .body { font-size: 13px; color: %(dim)s; }
dialog.alert .response-area { border-top: 1px solid %(line_lo)s; padding: 10px; border-spacing: 6px; }
dialog.alert .response-area > button { border: 1px solid %(line)s; margin: 0; }
dialog.alert .response-area > button.suggested { background-color: rgba(240, 240, 240, 0.14); border-color: rgba(240, 240, 240, 0.4); color: %(accent)s; }
dialog.alert .response-area > button.destructive { background-color: transparent; border-color: %(text)s; color: %(text)s; }
dimming { background-color: rgba(0, 0, 0, 0.7); }

headerbar {
  min-height: 30px;
  background-color: %(chrome)s;
  background-image: none;
  border-bottom: 1px solid %(line_lo)s;
  box-shadow: none;
  color: %(text)s;
}
headerbar .title, headerbar windowtitle .title {
  font-family: %(mono)s;
  font-size: 11.5px;
  font-weight: 400;
  letter-spacing: 0.02em;
  color: %(accent)s;
}
headerbar windowcontrols > button > image { background: none; }
headerbar button { border-color: transparent; background: none; color: %(dim)s; }
headerbar button:hover { background-color: %(raise_)s; color: %(text)s; }

banner > revealer > widget { background-color: %(raise_)s; border-bottom: 1px solid %(line)s; color: %(text)s; }
"""


_LAUNCHER_CSS = """
.launcher-sidebar { background-color: %(chrome)s; border-right: 1px solid %(line_lo)s; }
.launcher-sidebar .navigation-sidebar { padding: 12px 10px; background: none; }
.launcher-sidebar .navigation-sidebar row { margin-bottom: 4px; min-height: 40px; border: 1px solid transparent; }
.launcher-sidebar .navigation-sidebar row:selected { background-color: %(raise_)s; border-color: %(line)s; }
.launcher-brand { font-family: %(mono)s; font-size: 15px; font-weight: 600; letter-spacing: 1px; }
.launcher-section-title { font-family: %(mono)s; font-size: 11px; letter-spacing: 1px; color: %(dim)s; }
.launcher-header { border-bottom: 1px solid %(line_lo)s; }
.launcher-header windowtitle .subtitle { font-family: %(mono)s; font-size: 10px; color: %(dim)s; }
.play-dashboard { padding: 28px; }
.play-title { font-size: 34px; font-weight: 600; letter-spacing: -1px; color: %(text)s; }
.play-hero { background-color: alpha(%(surface)s, 0.94); border: 1px solid %(line)s; }
.play-hero-head { padding: 24px 22px 18px; }
.play-badge { font-family: %(mono)s; font-size: 10.5px; color: %(accent)s; padding: 5px 8px; border: 1px solid %(line)s; }
.play-facts { background-color: alpha(%(surface)s, 0.94); border: 1px solid %(line_lo)s; }
.play-fact { padding: 13px 16px; }
.play-fact + .play-fact { border-top: 1px solid %(line_lo)s; }
.play-fact-title { font-family: %(mono)s; font-size: 10px; letter-spacing: 0.4px; color: %(dim)s; }
.play-fact-value { font-family: %(mono)s; font-size: 11px; color: %(text)s; }
.play-quick-action { padding: 13px 16px; background-color: alpha(%(surface)s, 0.94); border-color: %(line_lo)s; }
.play-quick-action label { font-size: 12px; }
.play-quick-action:hover { border-color: %(accent)s; }
.play-hero actionbar { background: none; }
.play-hero actionbar > revealer > box { padding: 14px 18px; border-top: 1px solid %(line_lo)s; background: none; box-shadow: none; }
.play-hero actionbar button { min-height: 32px; min-width: 0; padding-left: 16px; padding-right: 16px; }
.play-hero actionbar .dim-label { font-family: %(mono)s; font-size: 10px; }
.play-footer { color: %(dim)s; font-size: 11px; }
window.launcher-custom .setup-wizard { background-image: none; }
window.launcher-custom .setup-wizard .setup-step,
window.launcher-custom .setup-wizard .setup-note,
window.launcher-custom .setup-wizard .setup-number { border-radius: 0; }
window.launcher-custom .setup-wizard .setup-progress { min-height: 2px; }
"""

_GRID_CSS = """
.play-hero { border-top: 2px solid #9cc3ff; }
button.suggested-action { background-color: #9cc3ff; border-color: #9cc3ff; color: #0c1829; font-weight: 600; }
button.suggested-action:hover { background-color: #b7d4ff; border-color: #b7d4ff; color: #0c1829; }
.launcher-sidebar .navigation-sidebar row:selected { background-color: rgba(156, 195, 255, 0.10); border-color: #344458; }
.launcher-sidebar .navigation-sidebar row:selected label,
.launcher-sidebar .navigation-sidebar row:selected image { color: #b7d4ff; }
.dot.on { background-color: #a6c8ff; border-color: #a6c8ff; box-shadow: none; }
.play-hero-head image { color: #a6c8ff; }
"""


def _stylesheet(appearance="monochrome"):
    palette = {
        "ui": UI_FONT, "mono": MONO_FONT, "night": NIGHT, "chrome": CHROME, "surface": SURFACE,
        "raise_": RAISE, "line": LINE, "line_lo": LINE_LO, "text": TEXT, "dim": DIM, "faint": FAINT,
        "accent": ACCENT, "accent2": ACCENT2, "warn": WARN, "focus": FOCUS_LINE,
    }
    colors = dict(_NAMED_COLORS)
    if appearance == "grid":
        palette.update(night="#10141b", chrome="#121820", surface="#18212c",
                       raise_="#202b38", line="#344458", line_lo="#263343",
                       text="#edf2f8", dim="#acb9ca", faint="#8493a7",
                       accent="#a6c8ff", accent2="#c1d8fa", warn="#b0c3de", focus="#7199ce")
        for name in ("window_bg_color",):
            colors[name] = palette["night"]
        for name in ("view_bg_color", "headerbar_bg_color", "headerbar_backdrop_color",
                     "sidebar_bg_color", "sidebar_backdrop_color", "secondary_sidebar_bg_color", "popover_bg_color"):
            colors[name] = palette["chrome"]
        for name in ("window_fg_color", "view_fg_color", "headerbar_fg_color", "sidebar_fg_color",
                     "secondary_sidebar_fg_color", "popover_fg_color", "dialog_fg_color", "card_fg_color"):
            colors[name] = palette["text"]
        colors.update(accent_color=palette["accent"], accent_bg_color="#9cc3ff", accent_fg_color="#0c1829",
                      dialog_bg_color=palette["surface"], card_bg_color="rgba(24, 33, 44, 0.94)",
                      card_shade_color=palette["line_lo"], sidebar_border_color=palette["line_lo"])
    names = "".join(f"@define-color {name} {value};\n" for name, value in colors.items())
    css = names + _CSS % palette + _LAUNCHER_CSS % palette
    if appearance == "grid":
        css += _GRID_CSS
    # libadwaita 1.6+ styles with CSS variables (GTK 4.16 parses them); older
    # ones use the named colors above and would warn about this block.
    if (Gtk.get_major_version(), Gtk.get_minor_version()) >= (4, 16):
        css += ":root {\n" + "".join(
            f"  --{name.replace('_', '-')}: {value};\n" for name, value in colors.items()) + "}\n"
    return css


def register_fonts():
    """Make the fonts in assets/fonts known to Pango, without installing them."""
    fontmap = None
    try:
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import PangoCairo
        fontmap = PangoCairo.FontMap.get_default()
    except (ValueError, ImportError):
        pass
    fontconfig = None
    for file in sorted(FONT_DIR.glob("*.ttf")):
        added = False
        if fontmap is not None and hasattr(fontmap, "add_font_file"):  # Pango 1.56
            try:
                added = bool(fontmap.add_font_file(str(file)))
            except GLib.Error:
                added = False
        if not added:
            # Older Pango: the application fonts of fontconfig's current
            # configuration, before the first text is laid out.
            try:
                fontconfig = fontconfig or ctypes.CDLL("libfontconfig.so.1")
                fontconfig.FcConfigAppFontAddFile(None, str(file).encode())
            except OSError:
                return  # the system's sans and monospace stand in


_provider = None
_provider_display = None
_native_scheme = None
_fonts_registered = False


def install(appearance="monochrome"):
    """Replace our provider, or remove it completely for native GNOME."""
    global _provider, _provider_display, _native_scheme, _fonts_registered
    manager = Adw.StyleManager.get_default()
    if _native_scheme is None:
        _native_scheme = manager.get_color_scheme()
    if _provider is not None:
        Gtk.StyleContext.remove_provider_for_display(_provider_display, _provider)
        _provider = _provider_display = None
    if appearance == "gnome":
        manager.set_color_scheme(_native_scheme)
        return
    if not _fonts_registered:
        register_fonts()
        _fonts_registered = True
    manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    provider = Gtk.CssProvider()
    css = _stylesheet(appearance)
    if hasattr(provider, "load_from_string"):  # GTK 4.12
        provider.load_from_string(css)
    else:
        provider.load_from_data(css.encode())
    _provider_display = Gdk.Display.get_default()
    Gtk.StyleContext.add_provider_for_display(
        _provider_display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    _provider = provider


class GridBackdrop(Gtk.Widget):
    """A static logical-pixel grid. Redraws only when GTK paints/resizes it."""

    def __init__(self):
        super().__init__(hexpand=True, vexpand=True, can_target=False)
        self._background = Gdk.RGBA()
        self._background.parse("#10141b")
        self._line = Gdk.RGBA()
        self._line.parse("rgba(128, 158, 197, 0.09)")

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        rect = Graphene.Rect()
        snapshot.append_color(self._background, rect.init(0, 0, width, height))
        for x in range(0, width, 32):
            snapshot.append_color(self._line, rect.init(x, 0, 1, height))
        for y in range(0, height, 32):
            snapshot.append_color(self._line, rect.init(0, y, width, 1))


class AppearanceLayer(Gtk.Box):
    """Keep images and asynchronously loaded avatars monochrome too."""

    def __init__(self, child):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.append(child)
        self.monochrome = False
        self._matrix = Graphene.Matrix().init_from_float([
            .2126, .2126, .2126, 0, .7152, .7152, .7152, 0,
            .0722, .0722, .0722, 0, 0, 0, 0, 1])
        self._offset = Graphene.Vec4().init(0, 0, 0, 0)

    def set_appearance(self, appearance):
        self.monochrome = appearance == "monochrome"
        self.queue_draw()

    def do_snapshot(self, snapshot):
        if self.monochrome:
            snapshot.push_color_matrix(self._matrix, self._offset)
        Gtk.Box.do_snapshot(self, snapshot)
        if self.monochrome:
            snapshot.pop()


# ------------------------------------------------------------------ backdrop

class Backdrop(Gtk.Picture):
    """The line field behind the windows, after the site's topology
    wallpaper: points wander along a smooth flow field and leave faint
    marks that add up to lines where their paths agree. It draws itself in
    during the first seconds and then holds still, so an idle launcher costs
    nothing. Without it (an old GTK) the desktop is simply black."""

    WIDTH, HEIGHT = 1280, 800
    POINTS = 520
    TICKS = 190        # at 40 ms: about eight seconds of drawing in
    STEPS = 3          # moves of a point per tick
    MARK = 15          # what one visit adds to a pixel
    CEILING = 112      # where a line stops getting brighter (the site's grey)

    def __init__(self):
        super().__init__(can_shrink=True, hexpand=True, vexpand=True)
        self.set_can_target(False)
        if hasattr(Gtk.ContentFit, "COVER"):
            self.set_content_fit(Gtk.ContentFit.COVER)
        self._format = getattr(Gdk.MemoryFormat, "G8", None)  # GTK 4.12
        self._ticks = 0
        self._timer = 0
        if self._format is None:
            return
        self._pixels = bytearray(self.WIDTH * self.HEIGHT)
        rng = random.Random()
        self._rng = rng
        # A smooth field: random values on a coarse lattice, eased between.
        self._cell = 150.0
        self._columns = int(self.WIDTH / self._cell) + 3
        self._rows = int(self.HEIGHT / self._cell) + 3
        self._lattice = [rng.random() for _ in range(self._columns * self._rows)]
        self._points = [self._spawn() for _ in range(self.POINTS)]
        settings = Gtk.Settings.get_default()
        self._animate = bool(settings is None or settings.get_property("gtk-enable-animations"))
        self.connect("map", self._start)
        self.connect("unmap", self._pause)

    def _spawn(self):
        rng = self._rng
        return [rng.uniform(0, self.WIDTH), rng.uniform(0, self.HEIGHT), rng.randint(60, 260)]

    def _angle(self, x, y):
        gx, gy = x / self._cell, y / self._cell
        ix, iy = int(gx), int(gy)
        fx, fy = gx - ix, gy - iy
        fx = fx * fx * (3 - 2 * fx)
        fy = fy * fy * (3 - 2 * fy)
        lattice, columns = self._lattice, self._columns
        at = iy * columns + ix
        top = lattice[at] + (lattice[at + 1] - lattice[at]) * fx
        bottom = lattice[at + columns] + (lattice[at + columns + 1] - lattice[at + columns]) * fx
        return (top + (bottom - top) * fy) * math.tau * 2.0

    def _start(self, *_args):
        if self._format is not None and not self._timer and self._ticks < self.TICKS:
            self._timer = GLib.timeout_add(40, self._tick)

    def _pause(self, *_args):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _tick(self):
        width, height = self.WIDTH, self.HEIGHT
        pixels, mark, ceiling = self._pixels, self.MARK, self.CEILING
        angle, cos, sin = self._angle, math.cos, math.sin
        rounds = self.STEPS if self._animate else self.STEPS * 8
        for point in self._points:
            x, y, life = point
            for _ in range(rounds):
                a = angle(x, y)
                x += cos(a) * 1.15
                y += sin(a) * 1.15
                life -= 1
                if life <= 0 or not (0 <= x < width and 0 <= y < height):
                    x, y, life = self._spawn()
                    continue
                at = int(y) * width + int(x)
                value = pixels[at] + mark
                pixels[at] = value if value < ceiling else ceiling
            point[0], point[1], point[2] = x, y, life
        self._ticks += 1 if self._animate else 8
        done = self._ticks >= self.TICKS
        if self._animate or done:
            self.set_paintable(Gdk.MemoryTexture.new(
                width, height, self._format, GLib.Bytes.new(bytes(pixels)), width))
        if done:
            self._timer = 0
            self._points = []
            return False
        return True


# ------------------------------------------------------------------- widgets

def dot(state=None):
    """A small square that is filled, grey or hollow; `set_dot` changes it."""
    widget = Gtk.Box(css_classes=["dot"], valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
    widget.set_size_request(7, 7)
    set_dot(widget, state)
    return widget


def set_dot(widget, state):
    """state: "on" (filled, bright), "busy" (filled, grey), "missing" (hollow,
    bright edge) or None (hollow)."""
    for name in ("on", "busy", "missing"):
        if name == state:
            widget.add_css_class(name)
        else:
            widget.remove_css_class(name)


CONTENT_WIDTH = 720   # the content window, where the launcher window allows it
COLUMN_WIDTH = 690    # settings rows inside it (their margins included)


class Strut(Gtk.Widget):
    """Nothing to see: a natural width for its container, so a window of
    the desktop grows to a comfortable size and no further, while it may
    still shrink with the launcher window."""

    def __init__(self, width):
        super().__init__()
        self._width = width

    def do_measure(self, orientation, _for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 0, self._width, -1, -1
        return 0, 0, -1, -1


def fit_columns(widget):
    """libadwaita narrows preference pages to a centred column that starts
    shrinking early; here they fill the content window."""
    if isinstance(widget, Adw.Clamp):
        widget.set_maximum_size(COLUMN_WIDTH)
        widget.set_tightening_threshold(COLUMN_WIDTH)
    child = widget.get_first_child()
    while child:
        fit_columns(child)
        child = child.get_next_sibling()


class Win(Gtk.Box):
    """A window of the desktop: a small title bar in mono above a body."""

    def __init__(self, title, child=None, padded=True, natural_width=0):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["win"])
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.bar = Gtk.Box(css_classes=["win-bar"])
        self.title = Gtk.Label(label=title, xalign=0, hexpand=True, css_classes=["win-title"],
                               ellipsize=Pango.EllipsizeMode.END)
        self.bar.append(self.title)
        self.note = Gtk.Label(css_classes=["win-note"], visible=False)
        self.bar.append(self.note)
        self.append(self.bar)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                            css_classes=["win-body", "padded"] if padded else ["win-body"])
        self.body.set_vexpand(True)
        self.append(self.body)
        if child is not None:
            self.body.append(child)
        if natural_width:
            self.append(Strut(natural_width))
            self.set_halign(Gtk.Align.START)

    def set_title(self, text):
        self.title.set_label(text)

    def set_note(self, text):
        self.note.set_label(text or "")
        self.note.set_visible(bool(text))


class Fact(Gtk.Box):
    """One line of the play window: a dot, what it is about, and its state
    on the right in mono."""

    def __init__(self, name, dotted=True):
        super().__init__(spacing=9, css_classes=["fact"])
        self.dot = dot()
        self.dot.set_visible(dotted)
        self.append(self.dot)
        self.append(Gtk.Label(label=name, xalign=0, hexpand=True, css_classes=["fact-name"]))
        self.note = Gtk.Label(xalign=1, css_classes=["fact-note"], ellipsize=Pango.EllipsizeMode.START)
        self.append(self.note)

    def set(self, state, note):
        set_dot(self.dot, state)
        self.note.set_label(note)


class LinkList(Gtk.Box):
    """The menu window's list: a name on the left, a small fact on the right."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.rows = {}
        self.notes = {}

    def add_section(self, text):
        self.append(Gtk.Label(label=text, xalign=0, css_classes=["sect"]))

    def add(self, name, title, action, note=""):
        line = Gtk.Box(spacing=9)
        line.append(Gtk.Label(label=title, xalign=0, hexpand=True, css_classes=["link-title"]))
        note_label = Gtk.Label(label=note, xalign=1, css_classes=["link-note"],
                               ellipsize=Pango.EllipsizeMode.END)
        line.append(note_label)
        button = Gtk.Button(child=line, css_classes=["link"])
        button.connect("clicked", lambda *_args: action())
        self.append(button)
        self.rows[name] = button
        self.notes[name] = note_label
        return button

    def set_current(self, name):
        for key, button in self.rows.items():
            if key == name:
                button.add_css_class("current")
            else:
                button.remove_css_class("current")

    def set_note(self, name, text):
        if name in self.notes:
            self.notes[name].set_label(text or "")


class Console(Gtk.Box):
    """What the launcher found, as the unit lines of a boot console. Every
    line is a real check; nothing here is for show."""

    STATUS = {"ok": "[  OK  ]", "wait": "[ WAIT ]", "failed": "[FAILED]"}

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["console"], spacing=3)
        self.lines = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.append(self.lines)
        self.prompt = Gtk.Label(xalign=0, css_classes=["prompt"], wrap=True)
        self.append(self.prompt)
        self._shown = None

    def set_lines(self, lines, prompt):
        """lines: (status, text) with status "ok", "wait", "failed" or None
        for a plain line that continues the one above."""
        if (lines, prompt) == self._shown:
            return
        self._shown = (list(lines), prompt)
        child = self.lines.get_first_child()
        while child:
            following = child.get_next_sibling()
            self.lines.remove(child)
            child = following
        for status, text in lines:
            row = Gtk.Box(spacing=9, css_classes=[] if status else ["plain"])
            mark = Gtk.Label(label=self.STATUS.get(status, " " * 8), xalign=0, yalign=0, valign=Gtk.Align.START,
                             css_classes=["st", status] if status else ["st"])
            row.append(mark)
            row.append(Gtk.Label(label=text, xalign=0, hexpand=True, wrap=True, selectable=True,
                                 css_classes=["msg"]))
            self.lines.append(row)
        self.prompt.set_label(f"{prompt} ▋" if prompt else "")


def tabs(stack):
    """A row of small toggles for the pages of `stack`, in place of
    libadwaita's view switcher."""
    box = Gtk.Box(css_classes=["tabs"])
    buttons = {}
    pages = stack.get_pages()
    first = None
    for index in range(pages.get_n_items()):
        page = pages.get_item(index)
        name = page.get_name()
        button = Gtk.ToggleButton(label=(page.get_title() or name).lower(), css_classes=["tab"])
        button.set_visible(page.get_visible())
        page.connect("notify::visible", lambda p, _pspec, b=button: b.set_visible(p.get_visible()))
        if first is None:
            first = button
        else:
            button.set_group(first)
        button.connect("toggled", lambda b, n=name: b.get_active() and stack.set_visible_child_name(n))
        box.append(button)
        buttons[name] = button

    def follow(*_args):
        button = buttons.get(stack.get_visible_child_name())
        if button is not None and not button.get_active():
            button.set_active(True)

    stack.connect("notify::visible-child-name", follow)
    follow()
    # In line with the rows below, whatever the width.
    return Adw.Clamp(child=box, maximum_size=COLUMN_WIDTH, tightening_threshold=COLUMN_WIDTH)
