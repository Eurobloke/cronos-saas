# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from app.extensions import db


class Service(db.Model):
    __tablename__ = 'services'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50), default='general')
    credit_cost = db.Column(db.Integer, default=1)
    price_usd = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True)
    bot_script = db.Column(db.String(200))   # ruta relativa al script dentro de BOTS_DIR
    icon = db.Column(db.String(50), default='⚙️')
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    jobs = db.relationship('Job', backref='service', lazy='dynamic')

    def __repr__(self):
        return f'<Service {self.slug}>'


# Servicios por defecto que se cargan al inicializar la BD
DEFAULT_SERVICES = [
    {'name': 'Generación de Guiones',       'slug': 'gen_guion',      'credit_cost': 5,  'category': 'contenido',   'icon': '📝', 'bot_script': 'horoscopo_bot/1_generar_textos.py'},
    {'name': 'Generación de Títulos',        'slug': 'gen_titulo',     'credit_cost': 1,  'category': 'contenido',   'icon': '🏷️', 'bot_script': None},
    {'name': 'Generación de Descripciones',  'slug': 'gen_descripcion','credit_cost': 1,  'category': 'contenido',   'icon': '📄', 'bot_script': None},
    {'name': 'Generación de Etiquetas',      'slug': 'gen_etiquetas',  'credit_cost': 1,  'category': 'contenido',   'icon': '🔖', 'bot_script': None},
    {'name': 'Generación de Miniaturas',     'slug': 'gen_miniatura',  'credit_cost': 3,  'category': 'diseño',      'icon': '🖼️', 'bot_script': 'noticias_rd_bot/thumbnail.py'},
    {'name': 'Generación de Imágenes',       'slug': 'gen_imagen',     'credit_cost': 4,  'category': 'diseño',      'icon': '🎨', 'bot_script': 'horoscopo_bot/2_generar_imagenes.py'},
    {'name': 'Generación de Música',         'slug': 'gen_musica',     'credit_cost': 10, 'category': 'audio',       'icon': '🎵', 'bot_script': 'proyecto_album_videos/suno_bot/suno_bot.py'},
    {'name': 'Narración con IA',             'slug': 'gen_narracion',  'credit_cost': 5,  'category': 'audio',       'icon': '🎙️', 'bot_script': 'horoscopo_bot/3_generar_audio.py'},
    {'name': 'Generación de Subtítulos',     'slug': 'gen_subtitulos', 'credit_cost': 2,  'category': 'audio',       'icon': '💬', 'bot_script': 'horoscopo_bot/4_generar_subtitulos.py'},
    {'name': 'Edición Automática',           'slug': 'edicion_auto',   'credit_cost': 8,  'category': 'video',       'icon': '✂️', 'bot_script': 'horoscopo_bot/5_ensamblar_videos.py'},
    {'name': 'Video Completo',               'slug': 'video_completo', 'credit_cost': 20, 'category': 'video',       'icon': '🎬', 'bot_script': 'horoscopo_bot/MENU.py'},
    {'name': 'Horoscopo Completo (12 signos)','slug': 'horoscopo_completo','credit_cost': 20,'category': 'horoscopo',  'icon': '♈', 'bot_script': 'horoscopo_bot/MENU.py'},
    {'name': 'Motivacion Completo',          'slug': 'motivacion_completo','credit_cost': 15,'category': 'motivacion', 'icon': '💪', 'bot_script': 'motivacion_bot/MENU.py'},
    {'name': 'Noticias RD Completo',         'slug': 'noticias_rd_completo','credit_cost':10,'category': 'noticias',   'icon': '📰', 'bot_script': 'noticias_rd_bot/MENU.py'},
    {'name': 'Exportación',                  'slug': 'exportacion',    'credit_cost': 2,  'category': 'video',       'icon': '📦', 'bot_script': None},
    {'name': 'Publicación en YouTube',       'slug': 'pub_youtube',    'credit_cost': 5,  'category': 'publicacion', 'icon': '▶️', 'bot_script': 'horoscopo_bot/7_subir_youtube.py'},
    {'name': 'Publicación en Facebook',      'slug': 'pub_facebook',   'credit_cost': 3,  'category': 'publicacion', 'icon': '👍', 'bot_script': 'motivacion_bot/3_publicar_facebook.py'},
]
