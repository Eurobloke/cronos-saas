# -*- coding: utf-8 -*-
from flask import render_template, request, redirect, session, current_app, jsonify
from . import public_bp
from app.services.paypal_service import paypal

# ─── Catálogo de productos públicos (sin login) ───────────────────────────────
PRODUCTOS = {
    'servicio-mensual': {
        'name': 'Servicio Canal YouTube — Gestionado por IA',
        'emoji': '📹',
        'price': 150.0,
        'recurrente': True,
        'badge': 'MÁS POPULAR',
        'badge_color': '#22c55e',
        'desc': 'Nosotros gestionamos tu canal de YouTube completamente con IA. Videos diarios automáticos, narración en voz humana, miniaturas y publicación — sin que toques nada.',
        'features': [
            'Videos diarios publicados en tu canal',
            'Narración en español con voz natural',
            'Miniaturas profesionales generadas con IA',
            'Publicación automática en YouTube',
            'Reporte semanal de crecimiento',
            'Soporte directo por WhatsApp',
        ],
        'wa_msg': 'Hola, quiero contratar el servicio gestionado de canal YouTube por $150/mes',
        'nicho': ['Horóscopo', 'Motivación', 'Cristiano', 'Noticias', 'Vehículos', 'Otro'],
    },
    'horoscopo': {
        'name': 'Horóscopo Bot — Código Fuente',
        'emoji': '♈',
        'price': 1200.0,
        'recurrente': False,
        'badge': None,
        'desc': 'Bot completo para canal de horóscopo. Genera los 12 signos zodiacales con narración, imágenes hermosas y publica en YouTube todos los días automáticamente.',
        'features': [
            '12 signos zodiacales generados diariamente',
            'Narración con voz natural (40+ voces)',
            'Imágenes generadas con IA por signo',
            'Publicación automática en YouTube',
            'Código fuente 100% tuyo, sin mensualidad',
            'Soporte por WhatsApp 30 días',
        ],
        'wa_msg': 'Hola, quiero comprar el Horóscopo Bot por $1,200',
    },
    'motivacion': {
        'name': 'Motivación Bot — Código Fuente',
        'emoji': '💪',
        'price': 1000.0,
        'recurrente': False,
        'badge': None,
        'desc': 'Bot de videos motivacionales con frases impactantes, música de fondo y voz inspiradora. Publica automáticamente en YouTube y Facebook.',
        'features': [
            'Frases motivacionales generadas con IA',
            'Voz inspiradora humanizada',
            'Música de fondo automática',
            'Publica en YouTube y Facebook',
            'Código fuente 100% tuyo',
            'Soporte por WhatsApp 30 días',
        ],
        'wa_msg': 'Hola, quiero comprar el Motivación Bot por $1,000',
    },
    'cristiano': {
        'name': 'Bot Cristiano — Código Fuente',
        'emoji': '✝️',
        'price': 1200.0,
        'recurrente': False,
        'badge': None,
        'desc': 'Contenido de fe cristiana automatizado: versículos, reflexiones y devocionales diarios con narración, imágenes y publicación en YouTube.',
        'features': [
            'Versículos y devocionales diarios',
            'Narración inspiracional con IA',
            'Imágenes de fe generadas con IA',
            'Publicación automática YouTube',
            'Código fuente 100% tuyo',
            'Soporte por WhatsApp 30 días',
        ],
        'wa_msg': 'Hola, quiero comprar el Bot Cristiano por $1,200',
    },
    'noticias': {
        'name': 'Noticias RD Bot — Código Fuente',
        'emoji': '📰',
        'price': 1500.0,
        'recurrente': False,
        'badge': None,
        'desc': 'Bot de noticias dominicanas. Scraping automático, miniaturas estilo CNN y publicación en YouTube, listo para monetizar.',
        'features': [
            'Scraping automático de noticias RD',
            'Narración tipo locutor profesional',
            'Miniaturas estilo noticiario',
            'Publicación automática YouTube',
            'Código fuente 100% tuyo',
            'Soporte por WhatsApp 30 días',
        ],
        'wa_msg': 'Hola, quiero comprar el Noticias RD Bot por $1,500',
    },
    'music-video': {
        'name': 'Music Video Bot — Código Fuente',
        'emoji': '🎵',
        'price': 1800.0,
        'recurrente': False,
        'badge': None,
        'desc': 'Bot para artistas independientes. Analiza tu canción y genera videos con letras animadas, efectos visuales y publicación automática.',
        'features': [
            'Videos con letras animadas sincronizadas',
            'Efectos visuales con IA',
            'Compatible con cualquier género musical',
            'Publicación automática YouTube',
            'Código fuente 100% tuyo',
            'Soporte por WhatsApp 30 días',
        ],
        'wa_msg': 'Hola, quiero comprar el Music Video Bot por $1,800',
    },
    'vehiculos': {
        'name': 'Vehículos Bot — Código Fuente',
        'emoji': '🚗',
        'price': 1400.0,
        'recurrente': False,
        'badge': None,
        'desc': 'Bot para venta de vehículos. Genera videos de anuncios automáticamente con narración, especificaciones y publica en YouTube y Facebook.',
        'features': [
            'Videos de anuncios de vehículos automáticos',
            'Narración de especificaciones con IA',
            'Publicación en YouTube y Facebook',
            'Múltiples vehículos en cola',
            'Código fuente 100% tuyo',
            'Soporte por WhatsApp 30 días',
        ],
        'wa_msg': 'Hola, quiero comprar el Vehículos Bot por $1,400',
    },
    'distrokid': {
        'name': 'DistroKid Bot — Código Fuente',
        'emoji': '💿',
        'price': 2000.0,
        'recurrente': False,
        'badge': None,
        'desc': 'Bot para distribución musical automatizada con DistroKid. Gestiona tus lanzamientos y distribución a plataformas de forma automática.',
        'features': [
            'Automatización de distribución musical',
            'Integración con DistroKid',
            'Gestión de lanzamientos en cola',
            'Publicación en plataformas de streaming',
            'Código fuente 100% tuyo',
            'Soporte por WhatsApp 30 días',
        ],
        'wa_msg': 'Hola, quiero comprar el DistroKid Bot por $2,000',
    },
    'avatar': {
        'name': 'Avatar Livestream Bot — Código Fuente',
        'emoji': '🤖',
        'price': 2500.0,
        'recurrente': False,
        'badge': 'NUEVO',
        'badge_color': '#f59e0b',
        'desc': 'Transmite en vivo 24/7 con un avatar IA que interactúa con tu audiencia. Perfecto para monetizar por YouTube Live.',
        'features': [
            'Stream en vivo 24/7 automatizado',
            'Avatar IA que responde a comentarios',
            'Compatible con YouTube Live',
            'Sin necesidad de estar presente',
            'Código fuente 100% tuyo',
            'Soporte por WhatsApp 30 días',
        ],
        'wa_msg': 'Hola, quiero comprar el Avatar Livestream Bot por $2,500',
    },
    'codigo-fuente': {
        'name': 'Sistema Completo Cronos AI — Código Fuente',
        'emoji': '🤖',
        'price': 3800.0,
        'recurrente': False,
        'badge': 'OFERTA ÚNICA',
        'badge_color': '#6366f1',
        'desc': 'Panel SaaS multi-usuario + 8 bots completos de automatización. Sistema listo para vender como servicio o usar para tu propio negocio.',
        'features': [
            'Panel web SaaS multi-usuario completo',
            '8 bots de contenido incluidos',
            'PayPal + dLocal Go integrados',
            'Base de datos PostgreSQL',
            'Despliegue listo en Railway',
            'Código fuente 100% tuyo + licencia comercial',
            'Soporte por WhatsApp 30 días',
        ],
        'wa_msg': 'Hola, quiero comprar el Sistema Completo Cronos AI por $3,800',
    },
}


@public_bp.route('/nosotros')
def about():
    return render_template('public/about.html')


@public_bp.route('/precios')
def pricing():
    from app.models.plan import Plan
    plans = Plan.query.filter_by(is_active=True).order_by(Plan.sort_order).all()
    return render_template('public/pricing.html', plans=plans)


@public_bp.route('/contacto')
def contact():
    return render_template('public/contact.html')


@public_bp.route('/faq')
def faq():
    return render_template('public/faq.html')


@public_bp.route('/privacidad')
def privacy():
    return render_template('public/privacy.html')


@public_bp.route('/terminos')
def terms():
    return render_template('public/terms.html')


@public_bp.route('/reembolsos')
def refunds():
    return render_template('public/refunds.html')


@public_bp.route('/pagar')
def pagar():
    """Link de pagos público — no requiere login."""
    from app.models.plan import Plan
    plans = Plan.query.filter_by(is_active=True).order_by(Plan.sort_order).all()
    return render_template('public/pagar.html', plans=plans)


# ═══════════════════════════════════════════════════════════
# Links de pago públicos — SIN LOGIN — para compartir por WhatsApp
# ═══════════════════════════════════════════════════════════

@public_bp.route('/comprar/<slug>', methods=['GET', 'POST'])
def comprar(slug):
    """Página de compra pública para un producto específico. No requiere login."""
    producto = PRODUCTOS.get(slug)
    if not producto:
        return redirect('/pagar')

    if request.method == 'GET':
        return render_template('public/comprar.html', slug=slug, producto=producto)

    # POST: crear orden PayPal
    email = request.form.get('email', '').strip().lower()
    nombre = request.form.get('nombre', '').strip()
    notas = request.form.get('notas', '').strip()

    if not email:
        return render_template('public/comprar.html', slug=slug, producto=producto,
                               error='Por favor ingresa tu correo electrónico.')

    app_url = current_app.config['APP_URL']
    try:
        order = paypal.create_order(
            amount=producto['price'],
            description=producto['name'],
            return_url=f"{app_url}/comprar/capturar?slug={slug}",
            cancel_url=f"{app_url}/comprar/{slug}",
        )
    except Exception as e:
        current_app.logger.error(f'PayPal guest order error: {e}')
        return render_template('public/comprar.html', slug=slug, producto=producto,
                               error='Error al conectar con PayPal. Intenta de nuevo o escríbenos por WhatsApp.')

    # Guardar en sesión (fallback sin DB)
    session['guest_order'] = {
        'slug': slug,
        'name': producto['name'],
        'price': producto['price'],
        'email': email,
        'nombre': nombre,
        'notas': notas,
        'order_id': order['order_id'],
    }
    session.permanent = True
    return redirect(order['approve_url'])


@public_bp.route('/comprar/capturar')
def comprar_capturar():
    """PayPal redirige aquí tras aprobar el pago."""
    order_id = request.args.get('token')
    slug = request.args.get('slug', '')

    if not order_id:
        return redirect('/pagar')

    guest = session.get('guest_order', {})

    try:
        result = paypal.capture_order(order_id)
        cap = result.get('capture', {})
        if result.get('order_status') != 'COMPLETED' or cap.get('status') != 'COMPLETED':
            current_app.logger.error(f'Guest capture falló: {result}')
            return redirect(f'/comprar/{slug}?error=pago_fallido')
    except Exception as e:
        current_app.logger.error(f'Guest capture error: {e}')
        return redirect(f'/comprar/{slug}?error=error_paypal')

    payer_email = cap.get('payer_email') or guest.get('email', '')
    nombre = guest.get('nombre', '')
    notas = guest.get('notas', '')
    producto_name = guest.get('name', slug)
    precio = guest.get('price', 0)

    # Notificar a Roberto por email
    try:
        from app.services.email_service import _send
        admin_email = current_app.config.get('ADMIN_EMAIL', 'franciscosamboy89@gmail.com')
        html_admin = f"""
        <h2>💰 Nueva venta recibida — Cronos AI</h2>
        <p><strong>Producto:</strong> {producto_name}</p>
        <p><strong>Precio:</strong> ${precio:.2f} USD</p>
        <p><strong>Cliente:</strong> {nombre or 'No especificado'}</p>
        <p><strong>Email cliente:</strong> {payer_email}</p>
        <p><strong>Notas:</strong> {notas or 'Ninguna'}</p>
        <p><strong>PayPal Order ID:</strong> {order_id}</p>
        <hr>
        <p>Contáctalo por WhatsApp o email para entregar el servicio.</p>
        <a href="https://wa.me/18298053488" style="background:#25d366;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">Abrir WhatsApp</a>
        """
        _send(f'💰 Nueva venta: {producto_name} — ${precio:.2f}', [admin_email], html_admin)

        # Confirmar al cliente
        html_cliente = f"""
        <h2>✅ ¡Pago recibido! — Cronos AI</h2>
        <p>Hola{' ' + nombre if nombre else ''},</p>
        <p>Recibimos tu pago por <strong>{producto_name}</strong> — <strong>${precio:.2f} USD</strong>.</p>
        <p>Nos pondremos en contacto contigo en las próximas horas para coordinar el acceso y entrega del servicio.</p>
        <p>Puedes escribirnos directamente por WhatsApp:</p>
        <a href="https://wa.me/18298053488" style="background:#25d366;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">💬 WhatsApp 829-805-3488</a>
        <br><br>
        <p style="color:#888;font-size:0.85rem;">Cronos AI · robertomartem@gmail.com</p>
        """
        _send('✅ Tu pago fue recibido — Cronos AI', [payer_email], html_cliente)
    except Exception as e:
        current_app.logger.error(f'Email notif error: {e}')

    # Guardar venta en archivo de log local (backup)
    try:
        import os, json as _json
        from datetime import datetime
        log_path = current_app.root_path.replace('app', '') + 'ventas_log.json'
        ventas = []
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8') as f:
                ventas = _json.load(f)
        ventas.append({
            'fecha': datetime.now().isoformat(),
            'producto': producto_name,
            'precio': precio,
            'email': payer_email,
            'nombre': nombre,
            'notas': notas,
            'order_id': order_id,
            'capture_id': cap.get('capture_id', ''),
        })
        with open(log_path, 'w', encoding='utf-8') as f:
            _json.dump(ventas, f, ensure_ascii=False, indent=2)
    except Exception as e:
        current_app.logger.error(f'Log venta error: {e}')

    session.pop('guest_order', None)
    return redirect(f'/comprar/gracias?producto={producto_name}&precio={precio:.2f}&email={payer_email}')


@public_bp.route('/comprar/gracias')
def comprar_gracias():
    producto = request.args.get('producto', 'tu producto')
    precio = request.args.get('precio', '0')
    email = request.args.get('email', '')
    return render_template('public/comprar_gracias.html',
                           producto=producto, precio=precio, email=email)


@public_bp.route('/links')
def links_publicos():
    """Muestra todos los links de pago — para compartir."""
    app_url = current_app.config['APP_URL']
    return render_template('public/links.html', productos=PRODUCTOS, app_url=app_url)
