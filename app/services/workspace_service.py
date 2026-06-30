# -*- coding: utf-8 -*-
"""
Gestiona el workspace en disco de cada usuario.

Estructura por slot:
  BOTS_DIR/users/{user_id}/{bot_slug}_s{slot}/
      config.json         ← config del canal
      auto_config.json    ← config de automatización
      yt_account.txt      ← email YouTube
      yt_canal.txt        ← nombre canal
      fb_page.txt         ← URL Facebook
      chrome_profile/     ← sesión YouTube (Chrome aislado)
      fb_profile/         ← sesión Facebook (Chrome aislado)
      output/             ← videos/imágenes generados
"""
import json
from pathlib import Path
from flask import current_app

BOT_SLUGS = ['horoscopo', 'motivacion', 'noticias', 'cristiano']


def _users_root() -> Path:
    return Path(current_app.config['BOTS_DIR']) / 'users'


def user_workspace(user_id: int, bot_slug: str, slot: int = 1) -> Path:
    folder = f'{bot_slug}_s{slot}' if slot > 1 else bot_slug
    return _users_root() / str(user_id) / folder


def create_user_workspaces(user_id: int, max_slots: int = 1):
    """Crea carpetas de workspace para todos los bots al registrarse un usuario."""
    root = _users_root()
    for slug in BOT_SLUGS:
        for slot in range(1, max_slots + 1):
            ws = user_workspace(user_id, slug, slot)
            (ws / 'output').mkdir(parents=True, exist_ok=True)
            (ws / 'chrome_profile').mkdir(parents=True, exist_ok=True)
            (ws / 'fb_profile').mkdir(parents=True, exist_ok=True)


def write_user_config(user_id: int, bot_slug: str, config: dict, auto: dict,
                      yt_email: str = '', yt_canal: str = '', fb_url: str = '',
                      slot: int = 1):
    """Escribe los archivos de config del usuario en su workspace."""
    ws = user_workspace(user_id, bot_slug, slot)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    (ws / 'auto_config.json').write_text(json.dumps(auto, ensure_ascii=False, indent=2), encoding='utf-8')
    if yt_email:
        (ws / 'yt_account.txt').write_text(yt_email, encoding='utf-8')
    if yt_canal:
        (ws / 'yt_canal.txt').write_text(yt_canal, encoding='utf-8')
    if fb_url:
        (ws / 'fb_page.txt').write_text(fb_url, encoding='utf-8')
    return ws


def session_active(user_id: int, bot_slug: str, slot: int = 1) -> bool:
    """True si el Chrome de YouTube ya tiene sesión guardada."""
    cookies = user_workspace(user_id, bot_slug, slot) / 'chrome_profile' / 'Default' / 'Cookies'
    return cookies.exists() and cookies.stat().st_size > 50000


def fb_session_active(user_id: int, bot_slug: str, slot: int = 1) -> bool:
    """True si el Chrome de Facebook ya tiene sesión guardada."""
    cookies = user_workspace(user_id, bot_slug, slot) / 'fb_profile' / 'Default' / 'Cookies'
    return cookies.exists() and cookies.stat().st_size > 50000


def get_stats(user_id: int, bot_slug: str, slot: int = 1) -> dict:
    """Estadísticas de output del usuario para un bot+slot."""
    from datetime import date
    ws = user_workspace(user_id, bot_slug, slot)
    output_dir = ws / 'output'
    hoy = date.today().strftime('%Y-%m-%d')
    videos = list(output_dir.rglob('*.mp4')) if output_dir.exists() else []
    total_bytes = sum(f.stat().st_size for f in output_dir.rglob('*') if f.is_file()) if output_dir.exists() else 0
    return {
        'videos_hoy': len([v for v in videos if hoy in v.name]),
        'total_videos': len(videos),
        'size_mb': round(total_bytes / (1024 * 1024), 1),
    }


def get_all_slots_stats(user_id: int, bot_slug: str, max_slots: int = 4) -> list:
    """Stats de todos los slots de un usuario para un bot."""
    result = []
    for slot in range(1, max_slots + 1):
        ws = user_workspace(user_id, bot_slug, slot)
        result.append({
            'slot': slot,
            'exists': ws.exists(),
            'yt_session': session_active(user_id, bot_slug, slot),
            'fb_session': fb_session_active(user_id, bot_slug, slot),
            **get_stats(user_id, bot_slug, slot),
        })
    return result


def storage_used_mb(user_id: int) -> float:
    """Espacio total usado por el usuario en todos sus bots y slots."""
    root = _users_root() / str(user_id)
    if not root.exists():
        return 0.0
    total = sum(f.stat().st_size for f in root.rglob('*') if f.is_file())
    return round(total / (1024 * 1024), 1)
