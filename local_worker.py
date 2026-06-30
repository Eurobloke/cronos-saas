# -*- coding: utf-8 -*-
"""
Worker local — corre en tu PC y procesa los trabajos de Railway.
Conecta a la misma base de datos PostgreSQL que Railway.

Uso: python local_worker.py
"""
import sys, os, time, logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('worker')

POLL_INTERVAL = 15  # segundos entre revisiones


def main():
    from app import create_app
    app = create_app()

    log.info('=' * 50)
    log.info('Worker local Cronos iniciado')
    log.info(f'Base de datos: {app.config["SQLALCHEMY_DATABASE_URI"][:50]}...')
    log.info('Revisando trabajos cada 15 segundos...')
    log.info('=' * 50)

    with app.app_context():
        while True:
            try:
                _procesar_pendientes(app)
            except KeyboardInterrupt:
                log.info('Worker detenido.')
                break
            except Exception as e:
                log.error(f'Error en ciclo: {e}')
            time.sleep(POLL_INTERVAL)


def _procesar_pendientes(app):
    from app.extensions import db
    from app.models.job import Job

    # Buscar trabajos pendientes (queued)
    pendientes = Job.query.filter_by(status='queued').order_by(Job.created_at.asc()).limit(3).all()

    if not pendientes:
        return

    for job in pendientes:
        service_slug = job.service.slug if job.service else ''
        log.info(f'Procesando Job #{job.id} — {service_slug}')

        # Marcar como recogido para que Railway no lo muestre como pendiente
        job.status = 'running'
        db.session.commit()

        try:
            _ejecutar_job(app, job.id, service_slug, job.get_params())
        except Exception as e:
            job.status = 'failed'
            job.error_message = str(e)
            db.session.commit()
            log.error(f'Job #{job.id} falló: {e}')


def _ejecutar_job(app, job_id, service_slug, params):
    if 'horoscopo' in service_slug:
        from app.services.bots.horoscopo_runner import run_pipeline_async
        run_pipeline_async(app, job_id, params)
    elif 'motivacion' in service_slug:
        from app.services.bots.motivacion_runner import run_pipeline_async
        run_pipeline_async(app, job_id, params)
    elif 'noticias' in service_slug:
        from app.services.bots.noticias_runner import run_pipeline_async
        run_pipeline_async(app, job_id, params)
    elif 'cristiano' in service_slug:
        from app.services.bots.cristiano_runner import run_pipeline_async
        run_pipeline_async(app, job_id, params)
    else:
        from app.services.bot_runner import run_job_async
        run_job_async(app, job_id)

    log.info(f'Job #{job_id} lanzado en hilo de fondo')


if __name__ == '__main__':
    main()
