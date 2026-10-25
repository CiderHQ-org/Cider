"""Mods and resource patching system for Quadra.

Allows custom fonts, classic sound presets (OOF, old movement), cursor presets,
and user-defined file overlays onto RobloxPlayer.app/Contents/Resources/content.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from . import core

log = logging.getLogger("quadra.mods")

MODS_DIR = core.DATA_DIR / "modifications"
MODS_BACKUP_DIR = core.DATA_DIR / "mods_backup"
BUILTIN_MODS_DIR = Path(__file__).resolve().parent / "assets" / "mods"


def get_content_dir() -> Path:
    return core.APP_BUNDLE / "Contents" / "Resources" / "content"


def ensure_mods_dir() -> Path:
    MODS_DIR.mkdir(parents=True, exist_ok=True)
    readme = MODS_DIR / "README.txt"
    if not readme.exists():
        readme.write_text(
            "Place custom files here to override Roblox content.\n"
            "For example: textures/Cursors/KeyboardMouse/ArrowCursor.png\n"
            "or sounds/ouch.ogg\n",
            encoding="utf-8",
        )
    return MODS_DIR


def _backup_if_needed(target: Path, rel_key: str):
    """Back up an original Roblox asset before overwriting it."""
    if not target.exists():
        return
    backup_path = MODS_BACKUP_DIR / rel_key
    if not backup_path.exists():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(target, backup_path)
            log.debug("Backed up original asset %s -> %s", target, backup_path)
        except OSError as e:
            log.warning("Failed to back up %s: %s", target, e)


def restore_all_mods(content_dir: Path | None = None):
    """Restore all modified files from the backup directory back to content/."""
    if content_dir is None:
        content_dir = get_content_dir()
    if not content_dir.is_dir() or not MODS_BACKUP_DIR.is_dir():
        return

    for backup_file in MODS_BACKUP_DIR.rglob("*"):
        if backup_file.is_file():
            rel = backup_file.relative_to(MODS_BACKUP_DIR)
            target = content_dir / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, target)
                log.debug("Restored original %s", rel)
            except OSError as e:
                log.warning("Could not restore %s: %s", rel, e)

    # Clean up custom font copies if left behind
    for ext in ("ttf", "otf"):
        custom_font = content_dir / "fonts" / f"CustomFont.{ext}"
        if custom_font.exists():
            try:
                custom_font.unlink()
            except OSError:
                pass

    # Remove backup directory now that everything has been restored cleanly
    shutil.rmtree(MODS_BACKUP_DIR, ignore_errors=True)


def apply_mods(settings: dict[str, Any], content_dir: Path | None = None):
    """Applies user selected mod presets and custom folder overrides."""
    if content_dir is None:
        content_dir = get_content_dir()
    if not content_dir.is_dir():
        log.info("Roblox content directory not found, skipping mods application.")
        return

    # First revert any previously backed up files to get a clean slate
    restore_all_mods(content_dir)

    # 1. Death sound
    death_sound = settings.get("mod_death_sound", "default")
    custom_death = settings.get("mod_custom_death_sound", "")
    target_ouch = content_dir / "sounds" / "ouch.ogg"

    if death_sound == "classic_oof":
        stock_oof = content_dir / "sounds" / "oof.ogg"
        if stock_oof.exists() and target_ouch.exists():
            _backup_if_needed(target_ouch, "sounds/ouch.ogg")
            try:
                shutil.copy2(stock_oof, target_ouch)
                log.info("Applied classic OOF death sound.")
            except OSError as e:
                log.warning("Failed to copy oof.ogg: %s", e)
    elif death_sound == "custom" and custom_death and Path(custom_death).is_file():
        _backup_if_needed(target_ouch, "sounds/ouch.ogg")
        try:
            shutil.copy2(custom_death, target_ouch)
            log.info("Applied custom death sound from %s", custom_death)
        except OSError as e:
            log.warning("Failed to copy custom death sound: %s", e)

    # 2. Old character movement sounds
    if settings.get("mod_old_character_sounds", False):
        sound_map = {
            "sounds/action_footsteps_plastic.mp3": BUILTIN_MODS_DIR / "sounds" / "OldWalk.mp3",
            "sounds/action_jump.mp3": BUILTIN_MODS_DIR / "sounds" / "OldJump.mp3",
            "sounds/action_get_up.mp3": BUILTIN_MODS_DIR / "sounds" / "OldGetUp.mp3",
            "sounds/action_falling.mp3": BUILTIN_MODS_DIR / "sounds" / "Empty.mp3",
            "sounds/action_jump_land.mp3": BUILTIN_MODS_DIR / "sounds" / "Empty.mp3",
            "sounds/action_swim.mp3": BUILTIN_MODS_DIR / "sounds" / "Empty.mp3",
            "sounds/impact_water.mp3": BUILTIN_MODS_DIR / "sounds" / "Empty.mp3",
        }
        for rel_path, src_file in sound_map.items():
            if src_file.exists():
                dst_file = content_dir / rel_path
                _backup_if_needed(dst_file, rel_path)
                try:
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)
                except OSError as e:
                    log.warning("Failed to apply %s: %s", rel_path, e)
        log.info("Applied classic character sounds.")

    # 3. Cursor presets
    cursor_type = settings.get("mod_cursor_type", "default")
    cursor_dir = content_dir / "textures" / "Cursors" / "KeyboardMouse"

    if cursor_type in ("2006", "2013", "purple_cross", "dot"):
        preset_dir = BUILTIN_MODS_DIR / "cursors" / cursor_type
        if preset_dir.is_dir():
            for src_cursor in preset_dir.glob("*.png"):
                rel_cursor = f"textures/Cursors/KeyboardMouse/{src_cursor.name}"
                dst_cursor = cursor_dir / src_cursor.name
                _backup_if_needed(dst_cursor, rel_cursor)
                try:
                    dst_cursor.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_cursor, dst_cursor)
                except OSError as e:
                    log.warning("Failed to copy cursor %s: %s", src_cursor.name, e)
            log.info("Applied cursor preset: %s", cursor_type)
    elif cursor_type == "custom":
        custom_cur = settings.get("mod_custom_cursor", "")
        if custom_cur:
            p = Path(custom_cur)
            if p.is_file() and p.suffix.lower() == ".png":
                # Single PNG replaces ArrowCursor.png and ArrowFarCursor.png
                for name in ("ArrowCursor.png", "ArrowFarCursor.png"):
                    rel_cursor = f"textures/Cursors/KeyboardMouse/{name}"
                    dst_cursor = cursor_dir / name
                    _backup_if_needed(dst_cursor, rel_cursor)
                    try:
                        shutil.copy2(p, dst_cursor)
                    except OSError as e:
                        log.warning("Failed to copy custom cursor: %s", e)
                log.info("Applied single custom cursor: %s", p)
            elif p.is_dir():
                for src_cursor in p.glob("*.png"):
                    rel_cursor = f"textures/Cursors/KeyboardMouse/{src_cursor.name}"
                    dst_cursor = cursor_dir / src_cursor.name
                    _backup_if_needed(dst_cursor, rel_cursor)
                    try:
                        shutil.copy2(src_cursor, dst_cursor)
                    except OSError as e:
                        log.warning("Failed to copy custom cursor %s: %s", src_cursor.name, e)
                log.info("Applied custom cursor folder: %s", p)

    # 4. Custom font
    font_path_str = settings.get("mod_custom_font", "")
    if font_path_str:
        font_path = Path(font_path_str)
        if font_path.is_file() and font_path.suffix.lower() in (".ttf", ".otf"):
            ext = font_path.suffix.lower()[1:]
            dest_font_name = f"CustomFont.{ext}"
            dest_font = content_dir / "fonts" / dest_font_name
            try:
                dest_font.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(font_path, dest_font)
            except OSError as e:
                log.warning("Failed to copy custom font %s: %s", font_path, e)

            asset_uri = f"rbxasset://fonts/{dest_font_name}"
            families_dir = content_dir / "fonts" / "families"
            if families_dir.is_dir():
                for json_file in families_dir.glob("*.json"):
                    rel_json = f"fonts/families/{json_file.name}"
                    _backup_if_needed(json_file, rel_json)
                    try:
                        data = json.loads(json_file.read_text(encoding="utf-8"))
                        if isinstance(data, dict) and "faces" in data and isinstance(data["faces"], list):
                            for face in data["faces"]:
                                if isinstance(face, dict):
                                    face["assetId"] = asset_uri
                            json_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
                    except Exception as e:
                        log.warning("Failed to patch font family %s: %s", json_file.name, e)
                log.info("Applied custom font %s across all font families.", font_path.name)

    # 5. User custom modifications folder (overlay)
    if settings.get("enable_custom_mods", True) and MODS_DIR.is_dir():
        for root, _dirs, files in os.walk(MODS_DIR):
            for file_name in files:
                if file_name in ("README.txt", ".DS_Store"):
                    continue
                src_file = Path(root) / file_name
                rel_path = src_file.relative_to(MODS_DIR)

                # Check for delete marker (e.g. filename_Delete.png)
                stem = src_file.stem
                if stem.endswith("_Delete"):
                    orig_stem = stem[:-7]
                    target_name = orig_stem + src_file.suffix
                    dst_file = content_dir / rel_path.parent / target_name
                    if dst_file.exists():
                        rel_key = str(rel_path.parent / target_name)
                        _backup_if_needed(dst_file, rel_key)
                        try:
                            dst_file.unlink()
                            log.info("Removed asset via _Delete marker: %s", rel_key)
                        except OSError as e:
                            log.warning("Failed to delete %s: %s", dst_file, e)
                    continue

                dst_file = content_dir / rel_path
                rel_key = str(rel_path)
                _backup_if_needed(dst_file, rel_key)
                try:
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)
                    log.debug("Applied custom mod file: %s", rel_key)
                except OSError as e:
                    log.warning("Failed to copy mod file %s: %s", src_file, e)
        log.info("Applied user modifications folder.")
