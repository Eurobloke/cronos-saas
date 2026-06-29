# -*- coding: utf-8 -*-
"""
Scheduler automático de bots.
Corre en segundo plano y dispara los pipelines según la configuración
guardada en auto_config.json de cada bot.
"""
import json
import logging
from datetime import datetime, date
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger('cronos.scheduler')

# Rutas de cada bot (absolutas, Windows)
BOTS_CONFIG = {
    'horoscopo': {
        'dir': Path(r'C:\Users\franc\music\horoscopo_bot'),
        'service_slug': 'horoscopo_completo',
        'credit_cost': 20,
        'default_params': {'signos': 'todos', 'subir_youtube': True},
    },
    'motivacion': {
        'dir': Path(r'C:\Users\franc\music\motivacion_bot'),
        'service_slug': 'motivacion_completo',
        'credit_cost': 15,
        'default_params': {'categoria': 'exito'},
    },
    'noticias_rd': {
        'dir': Path(r'C:\Users\franc\music\noticias_rd_bot'),
        'service_slug': 'noticias_rd_completo',
        'credit_cost': 10,
        'default_params': {},
    },
    'cristiano': {
        'dir': Path(r'C:\Users\franc\music\cristiano_bot'),
        'service_slug': 'cristiano_completo',
        'credit_cost': 15,
        'default_params': {},
    },
}

# Mapa día español → número APScheduler (lun=0…dom=6)
DIA_MAP = {'lun': 0, 'mar': 1, 'mie': 2, 'jue': 3, 'vie': 4, 'sab': 5, 'dom': 6}


def _load_auto_cfg(bot_dir: Path) -> dict:
    p = bot_dir / 'auto_config.json'
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _today_key() -> str:
    return date.today().strftime('%Y-%m-%d')


def _already_ran_today(bot_dir: Path) -> bool:
    """Evita doble ejecución: revisa si hay un archivo .ran para hoy."""
    ran_file = bot_dir / f'.ran_{_today_key()}'
    return ran_file.exists()


def _mark_ran_today(bot_dir: Path):
    ran_file = bot_dir / f'.ran_{_today_key()}'
    ran_file.write_text('ok', encoding='utf-8')


def _check_and_run(app, bot_key: str):
    """Verifica si el bot debe correr ahora y lo lanza."""
    cfg_info = BOTS_CONFIG.get(bot_key)
    if not cfg_info:
        return

    bot_dir = cfg_info['dir']
    auto_cfg = _load_auto_cfg(bot_dir)

    if not auto_cfg.get('activo', False):
        return

    # Verificar día de la semana
    hoy_num = datetime.now().weekday()  # 0=lun, 6=dom
    dias_activos = [DIA_MAP.get(d, -1) for d in auto_cfg.get('dias', list(DIA_MAP.keys()))]
    if hoy_num not in dias_activos:
        return

    # Verificar hora de inicio
    hora_cfg = auto_cfg.get('hora_inicio', '07:00')
    ahora = datetime.now()
    hora_h, hora_m = map(int, hora_cfg.split(':'))
    if ahora.hour < hora_h or (ahora.hour == hora_h and ahora.minute < hora_m):
        return  # Todavía no es la hora

    # Evitar doble ejecución en el día
    if _already_ran_today(bot_dir):
        return

    log.info(f'[Scheduler] Disparando bot: {bot_key}')
    _mark_ran_today(bot_dir)

    with app.app_context():
        _launch_bot_scheduled(app, bot_key, cfg_info, auto_cfg)


def _launch_bot_scheduled(app, bot_key: str, cfg_info: dict, auto_cfg: dict):
    """Crea el Job en BD y lanza el runner usando el admin (usuario ID=1)."""
    from app.extensions import db
    from app.models.job import Job
    from app.models.service import Service
    from app.models.user import User
    from app.services import credit_service

    # Usar usuario administrador (ID=1) para jobs automáticos del sistema
    admin = User.query.get(1)
    if not admin:
        log.warning(f'[Scheduler] No hay usuario admin para lanzar {bot_key}')
        return

    service = Service.query.filter_by(slug=cfg_info['service_slug']).first()
    if not service:
        log.warning(f'[Scheduler] Servicio {cfg_info["service_slug"]} no configurado')
        return

    cost = cfg_info['credit_cost']
    if admin.credits < cost:
        log.warning(f'[Scheduler] Créditos insuficientes para {bot_key}: {admin.credits}/{cost}')
        return

    params = {**cfg_info['default_params']}
    params['fecha'] = _today_key()
    params['_auto'] = True  # marca que fue automático

    # Facebook URL si está configurada
    fb_file = cfg_info['dir'] / 'fb_page.txt'
    if fb_file.exists():
        params['fb_url'] = fb_file.read_text(encoding='utf-8').strip()

    job = Job(user_id=admin.id, service_id=service.id, credits_used=cost)
    job.set_params(params)
    db.session.add(job)
    db.session.flush()

    ok = credit_service.consume_credits(admin, cost,
                                        f'Auto: {bot_key}', reference=f'job:{job.id}')
    if not ok:
        db.session.rollback()
        log.error(f'[Scheduler] Error descontando créditos para {bot_key}')
        return

    db.session.commit()

    # Lanzar el runner correcto
    if bot_key == 'horoscopo':
        from app.services.bots.horoscopo_runner import run_pipeline_async
        run_pipeline_async(app, job.id, params)
    else:
        from app.services.bot_runner import run_job_async
        run_job_async(app, job.id)

    log.info(f'[Scheduler] Job #{job.id} lanzado para {bot_key}')


_scheduler = None


def start_scheduler(app):
    """Inicia el scheduler de fondo. Llamar una sola vez al arrancar Flask."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone='America/Santo_Domingo')

    # Revisar cada bot cada 15 minutos
    for bot_key in BOTS_CONFIG:
        _scheduler.add_job(
            func=_check_and_run,
            trigger=CronTrigger(minute='*/15'),
            args=[app, bot_key],
            id=f'check_{bot_key}',
            replace_existing=True,
            misfire_grace_time=300,
        )

    _scheduler.start()
    log.info('[Scheduler] Iniciado — revisa bots cada 15 minutos')


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
