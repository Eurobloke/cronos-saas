# -*- coding: utf-8 -*-
"""Genera comprobantes PDF descargables."""
import io
from datetime import datetime, timezone

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def generate_invoice_pdf(payment, user) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            rightMargin=72, leftMargin=72,
                            topMargin=72, bottomMargin=72)
    styles = getSampleStyleSheet()
    story = []

    # Encabezado
    story.append(Paragraph('<b>CRONOS AI</b>', styles['Title']))
    story.append(Paragraph('Plataforma de Generación de Contenido con IA', styles['Normal']))
    story.append(Spacer(1, 0.3 * inch))

    story.append(Paragraph(f'<b>COMPROBANTE DE PAGO</b>', styles['Heading2']))
    story.append(Spacer(1, 0.1 * inch))

    fecha_str = (payment.completed_at or payment.created_at).strftime('%d/%m/%Y %H:%M')
    info = [
        ['Número de factura:', payment.invoice_number or 'N/A'],
        ['Fecha:', fecha_str],
        ['Cliente:', user.username],
        ['Email:', user.email],
        ['Estado:', 'PAGADO' if payment.status == 'completed' else payment.status.upper()],
    ]
    t = Table(info, colWidths=[2.2 * inch, 3.5 * inch])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.lightgrey]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.3 * inch))

    # Detalle
    story.append(Paragraph('<b>Detalle</b>', styles['Heading3']))
    detalle = [
        ['Descripción', 'Créditos', 'Subtotal', 'Descuento', 'Total'],
        [
            payment.description or 'Compra de créditos',
            str(payment.credits_granted),
            f'${payment.amount + payment.discount_amount:.2f} USD',
            f'-${payment.discount_amount:.2f} USD',
            f'${payment.amount:.2f} USD',
        ],
    ]
    td = Table(detalle, colWidths=[2.5 * inch, 1 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch])
    td.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e293b')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(td)
    story.append(Spacer(1, 0.5 * inch))

    # Método de pago
    story.append(Paragraph(f'Método de pago: <b>PayPal</b>', styles['Normal']))
    if payment.paypal_capture_id:
        story.append(Paragraph(f'ID de transacción: {payment.paypal_capture_id}', styles['Normal']))

    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph('Gracias por usar Cronos AI.', styles['Normal']))

    doc.build(story)
    return buffer.getvalue()
