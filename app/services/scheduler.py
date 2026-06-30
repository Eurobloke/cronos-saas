# -*- coding: utf-8 -*-
"""
Scheduler automático — lee config de BD (UserBotConfig por slot) y lanza runners.
Revisa cada 15 minutos qué bots/slots deben correr según su horario configurado.
Si un usuario tiene N slots activos, los lanza en secuencia con un delay entre cada uno
para distribuir la carga.
"""
import logging
import time
import threading
from datetime import datetime, date
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger('cronos.scheduler')

DIA_MAP = {'lun': 0, 'mar': 1, 'mie': 2, 'jue': 3, 'vie': 4, 'sab': 5, 'dom': 6}

BOTS_INFO = {
    'horoscopo': {'service_slug': 'horoscopo_completo',   'credit_cost': 20},
    'motivacion': {'service_slug': 'motivacion_completo', 'credit_cost': 15},
    'noticias':  {'service_slug': 'noticias_rd_completo', 'credit_cost': 10},
    'cristiano': {'service_slug': 'cristiano_completo',   'credit_cost': 15},
}

# Delay entre slots del mismo usuario (segundos) para no saturar recursos
SLOT_DELAY_SECONDS = 300  # 5 minutos entre slots


def _ran_key(user_id: int, bot_slug: str, slot: int) -> Path:
    key = date.today().strftime('%Y-%m-%d')
    return Path(f'C:/Users/franc/music/users/{user_id}/{bot_slug}_s{slot}/.ran_{key}')


def _already_ran(user_id: int, bot_slug: str, slot: int) -> bool:
    # Slot 1 usa carpeta sin sufijo (backward compat)
    if slot == 1:
        p1 = Path(f'C:/Users/franc/music/users/{user_id}/{bot_slug}/.ran_{date.today().strftime("%Y-%m-%d")}')
        if p1.exists():
            return True
    return _ran_key(user_id, bot_slug, slot).exists()


def _mark_ran(user_id: int, bot_slug: str, slot: int):
    p = _ran_key(user_id, bot_slug, slot)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('ok')


def _check_all_users(app, bot_slug: str):
    """Revisa todos los slots de todos los usuarios para este bot."""
    with app.app_context():
        from app.models.user_bot_config import UserBotConfig
        # Agrupar por usuario
        all_cfgs = UserBotConfig.query.filter_by(bot_slug=bot_slug).order_by(
            UserBotConfig.user_id, UserBotConfig.slot
        ).all()

        # Agrupar slots por usuario
        by_user = {}
        for cfg in all_cfgs:
            by_user.setdefault(cfg.user_id, []).append(cfg)

        for user_id, cfgs in by_user.items():
            # Filtrar solo los slots activos que deben correr ahora
            to_run = [c for c in cfgs if _should_run(c)]
            if not to_run:
                continue

            n = len(to_run)
            log.info(f'[Scheduler] {bot_slug} user={user_id}: {n} slot(s) activos para correr')

            # Lanzar en un thread separado con delay entre slots
            thread = threading.Thread(
                target=_run_slots_staggered,
                args=(app, to_run, n),
                daemon=True
            )
            thread.start()


def _should_run(cfg) -> bool:
    auto = cfg.get_auto()
    if not auto.get('activo', False):
        return False
    hoy_num = datetime.now().weekday()
    dias = [DIA_MAP.get(d, -1) for d in auto.get('dias', list(DIA_MAP.keys()))]
    if hoy_num not in dias:
        return False
    hora_cfg = auto.get('hora_inicio', '07:00')
    ahora = datetime.now()
    h, m = map(int, hora_cfg.split(':'))
    if ahora.hour < h or (ahora.hour == h and ahora.minute < m):
        return False
    return not _already_ran(cfg.user_id, cfg.bot_slug, cfg.slot)


def _run_slots_staggered(app, cfgs, total_slots):
    """Lanza cada slot con un delay proporcional al total de slots activos."""
    delay = SLOT_DELAY_SECONDS if total_slots > 1 else 0
    for i, cfg in enumerate(cfgs):
        if i > 0 and delay > 0:
            log.info(f'[Scheduler] Esperando {delay}s antes del slot {cfg.slot}...')
            time.sleep(delay)
        auto = cfg.get_auto()
        try:
            _launch(app, cfg, auto)
        except Exception as e:
            log.error(f'[Scheduler] Error lanzando slot {cfg.slot} user={cfg.user_id}: {e}')


def _launch(app, cfg, auto_cfg):
    with app.app_context():
        from app.extensions import db
        from app.models.job import Job
        from app.models.service import Service
        from app.models.user import User
        from app.services import credit_service
        from app.services import workspace_service as ws_svc

        user = db.session.get(User, cfg.user_id)
        if not user or not user.is_active:
            return

        info = BOTS_INFO.get(cfg.bot_slug)
        if not info:
            return

        service = Service.query.filter_by(slug=info['service_slug']).first()
        if not service:
            log.warning(f'[Scheduler] Servicio {info["service_slug"]} no existe')
            return

        cost = info['credit_cost']
        if not user.is_admin() and user.credits < cost:
            log.warning(f'[Scheduler] user={user.id} sin créditos para {cfg.bot_slug} slot={cfg.slot}')
            return

        slot = cfg.slot
        canal_cfg = cfg.get_config()
        workspace = str(ws_svc.user_workspace(user.id, cfg.bot_slug, slot))

        ws_svc.write_user_config(user.id, cfg.bot_slug, canal_cfg, auto_cfg,
                                 yt_email=cfg.yt_email or '',
                                 yt_canal=cfg.yt_canal or '',
                                 fb_url=cfg.fb_url or '',
                                 slot=slot)

        params = {
            'fecha': date.today().strftime('%Y-%m-%d'),
            'user_id': user.id,
            'user_workspace': workspace,
            'bot_slug': cfg.bot_slug,
            'slot': slot,
            '_auto': True,
            'subir_youtube':     bool(cfg.yt_email),
            'yt_shorts':         True,
            'publicar_facebook': bool(cfg.fb_url),
            'fb_reels':          True,
            'fb_fotos':          False,
        }
        if cfg.fb_url:
            params['fb_url'] = cfg.fb_url

        nombre_job = f'Auto: {cfg.bot_slug}' + (f' (Cuenta {slot})' if slot > 1 else '')
        job = Job(user_id=user.id, service_id=service.id, credits_used=cost)
        job.set_params(params)
        db.session.add(job)
        db.session.flush()

        ok = credit_service.consume_credits(user, cost, nombre_job, reference=f'job:{job.id}')
        if not ok:
            db.session.rollback()
            return

        db.session.commit()
        _mark_ran(user.id, cfg.bot_slug, slot)

        if cfg.bot_slug == 'horoscopo':
            from app.services.bots.horoscopo_runner import run_pipeline_async
        elif cfg.bot_slug == 'motivacion':
            from app.services.bots.motivacion_runner import run_pipeline_async
        elif cfg.bot_slug == 'noticias':
            from app.services.bots.noticias_runner import run_pipeline_async
        elif cfg.bot_slug == 'cristiano':
            from app.services.bots.cristiano_runner import run_pipeline_async
        else:
            return

        run_pipeline_async(app, job.id, params)
        log.info(f'[Scheduler] Job #{job.id} lanzado: {cfg.bot_slug} slot={slot} user={user.id}')


_scheduler = None


def start_scheduler(app):
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone='America/Santo_Domingo')

    for bot_slug in BOTS_INFO:
        _scheduler.add_job(
            func=_check_all_users,
            trigger=CronTrigger(minute='*/15'),
            args=[app, bot_slug],
            id=f'check_{bot_slug}',
            replace_existing=True,
            misfire_grace_time=300,
        )

    _scheduler.start()
    log.info('[Scheduler] Iniciado — multi-slot, revisa todos los bots cada 15 minutos')


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
