"""
pdf_generator.py
Generacion de PDFs: boletas de venta, recibos de pago de
membresia, y contratos de matricula personalizados.

Usa reportlab (agregado a requirements.txt). Todas las funciones
devuelven bytes listos para servir como StreamingResponse/FileResponse.
"""

import io
from datetime import datetime

from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

COLOR_PRIMARIO = colors.HexColor("#5B4FE5")

_styles = getSampleStyleSheet()
_estilo_titulo = ParagraphStyle("TituloGym", parent=_styles["Heading1"], textColor=COLOR_PRIMARIO, spaceAfter=4)
_estilo_subtitulo = ParagraphStyle("Subtitulo", parent=_styles["Normal"], textColor=colors.grey, fontSize=9)
_estilo_normal = _styles["Normal"]
_estilo_seccion = ParagraphStyle("Seccion", parent=_styles["Heading3"], textColor=COLOR_PRIMARIO, spaceBefore=10, spaceAfter=4)
_estilo_total = ParagraphStyle("Total", parent=_styles["Heading2"], alignment=TA_RIGHT, textColor=COLOR_PRIMARIO)
_estilo_clausula = ParagraphStyle("Clausula", parent=_styles["Normal"], spaceAfter=8, alignment=4)  # justify


def _encabezado_gimnasio(config, subtitulo_doc: str):
    elementos = [
        Paragraph(config.nombre_gimnasio or "Mi Gimnasio", _estilo_titulo),
        Paragraph(f"{config.direccion or ''} {'· ' + config.telefono if config.telefono else ''}", _estilo_subtitulo),
        Spacer(1, 6),
        HRFlowable(width="100%", color=COLOR_PRIMARIO, thickness=1.2),
        Spacer(1, 10),
        Paragraph(subtitulo_doc, _estilo_seccion),
    ]
    return elementos


def generar_boleta_pdf(venta, cliente, config) -> bytes:
    """Boleta de una venta (productos) o de un pago (parcial o total) de membresia. Formato A5 horizontal (apaisado), pensado para compartir como comprobante corto."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A5), topMargin=1 * cm, bottomMargin=1 * cm, leftMargin=1.3 * cm, rightMargin=1.3 * cm)
    elementos = _encabezado_gimnasio(config, f"Boleta de Venta N° {venta.id:06d}")

    nombre_cliente = f"{cliente.nombre} {cliente.apellidos or ''}".strip() if cliente else "Cliente sin registrar"
    elementos.append(Paragraph(f"<b>Cliente:</b> {nombre_cliente} &nbsp;&nbsp; <b>Fecha:</b> {venta.fecha_venta.strftime('%d/%m/%Y %H:%M')} &nbsp;&nbsp; <b>Pago:</b> {venta.metodo_pago.value.capitalize()}", _estilo_normal))
    elementos.append(Spacer(1, 8))

    datos_tabla = [["Producto", "Cant.", "Precio Unit.", "Subtotal"]]
    for d in venta.detalles:
        nombre_prod = d.producto.nombre if d.producto else f"#{d.producto_id}"
        datos_tabla.append([nombre_prod, str(d.cantidad), f"{config.moneda} {d.precio_unitario:.2f}", f"{config.moneda} {d.subtotal:.2f}"])

    tabla = Table(datos_tabla, colWidths=[8 * cm, 2 * cm, 3.3 * cm, 3.3 * cm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARIO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F6FA")]),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 10))
    elementos.append(Paragraph(f"Total pagado: {config.moneda} {venta.total:.2f}", _estilo_total))
    elementos.append(Spacer(1, 10))
    elementos.append(Paragraph("Gracias por tu compra.", _estilo_subtitulo))

    doc.build(elementos)
    return buffer.getvalue()


def generar_recibo_membresia_pdf(cliente_membresia, cliente, membresia, config) -> bytes:
    """Recibo de pago (total o parcial) de una membresia."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    elementos = _encabezado_gimnasio(config, f"Recibo de Membresia N° {cliente_membresia.id:06d}")

    nombre_cliente = f"{cliente.nombre} {cliente.apellidos or ''}".strip()
    deuda = max(membresia.precio - (cliente_membresia.monto_pagado or 0.0), 0.0)

    elementos.append(Paragraph(f"<b>Cliente:</b> {nombre_cliente}", _estilo_normal))
    elementos.append(Paragraph(f"<b>Fecha de emision:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", _estilo_normal))
    elementos.append(Spacer(1, 12))

    datos_tabla = [
        ["Concepto", "Monto"],
        [membresia.nombre, f"{config.moneda} {membresia.precio:.2f}"],
        ["Monto pagado", f"{config.moneda} {(cliente_membresia.monto_pagado or 0.0):.2f}"],
        ["Saldo pendiente", f"{config.moneda} {deuda:.2f}"],
        ["Vigencia", f"{cliente_membresia.fecha_inicio.strftime('%d/%m/%Y')} - {cliente_membresia.fecha_fin.strftime('%d/%m/%Y') if cliente_membresia.fecha_fin else 'N/A'}"],
    ]
    tabla = Table(datos_tabla, colWidths=[9 * cm, 7 * cm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARIO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F6FA")]),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 24))
    if deuda > 0:
        elementos.append(Paragraph(f"<b>Saldo pendiente por cancelar: {config.moneda} {deuda:.2f}</b>", _estilo_normal))

    doc.build(elementos)
    return buffer.getvalue()


def generar_recibo_pago_planilla(pago, empleado, config) -> bytes:
    """Recibo de un pago de planilla (staff fijo o profesor de sala). Formato A5 (mitad de una hoja A4), pensado para imprimir/compartir como comprobante corto."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A5, topMargin=1.2 * cm, bottomMargin=1.2 * cm, leftMargin=1.2 * cm, rightMargin=1.2 * cm)
    elementos = _encabezado_gimnasio(config, f"Recibo de Pago N° {pago.id:06d}")

    elementos.append(Paragraph(f"<b>Trabajador:</b> {empleado.nombre_completo}", _estilo_normal))
    elementos.append(Paragraph(f"<b>Periodo:</b> {pago.mes:02d}/{pago.anio}", _estilo_normal))
    elementos.append(Paragraph(f"<b>Fecha de pago:</b> {pago.fecha_pago.strftime('%d/%m/%Y %H:%M')}", _estilo_normal))
    elementos.append(Spacer(1, 10))

    if pago.tipo == "staff":
        datos_tabla = [
            ["Concepto", "Monto"],
            ["Sueldo fijo", f"{config.moneda} {pago.monto_sueldo_fijo:.2f}"],
            ["Comision membresias (mes ant.)", f"{config.moneda} {pago.monto_comision_membresias:.2f}"],
            ["Comision productos (mes ant.)", f"{config.moneda} {pago.monto_comision_productos:.2f}"],
            ["Total pagado (este recibo)", f"{config.moneda} {pago.monto_total:.2f}"],
        ]
    else:
        datos_tabla = [
            ["Concepto", "Monto"],
            ["Clases dictadas", str(pago.cantidad_clases or 0)],
            ["Monto calculado por clases", f"{config.moneda} {pago.monto_clases:.2f}"],
            ["Total pagado (este recibo)", f"{config.moneda} {pago.monto_total:.2f}"],
        ]

    tabla = Table(datos_tabla, colWidths=[7.5 * cm, 4 * cm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARIO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F6FA")]),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 16))

    if pago.notas:
        elementos.append(Paragraph(f"<b>Notas:</b> {pago.notas}", _estilo_normal))
        elementos.append(Spacer(1, 8))

    firma_tabla = Table([["_________________________"], ["Firma de conformidad"]], colWidths=[7 * cm])
    firma_tabla.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("TOPPADDING", (0, 0), (-1, 0), 24)]))
    elementos.append(firma_tabla)

    doc.build(elementos)
    return buffer.getvalue()


def generar_contrato_pdf(cliente, cliente_membresia, membresia, config) -> bytes:
    """Contrato de matricula personalizado, con las clausulas configuradas en Configuracion."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    elementos = _encabezado_gimnasio(config, "Contrato de Matricula")

    nombre_cliente = f"{cliente.nombre} {cliente.apellidos or ''}".strip()

    elementos.append(Paragraph(
        f"Entre <b>{config.nombre_gimnasio or 'el gimnasio'}</b> y <b>{nombre_cliente}</b>"
        f"{', DNI ' + cliente.dni if cliente.dni else ''}, se celebra el presente contrato de matricula "
        f"bajo las siguientes condiciones:",
        _estilo_clausula,
    ))

    datos_tabla = [
        ["Plan", membresia.nombre],
        ["Monto", f"{config.moneda} {membresia.precio:.2f}"],
        ["Duracion", f"{membresia.duracion_dias} dias"],
        ["Inicio", cliente_membresia.fecha_inicio.strftime("%d/%m/%Y")],
        ["Vencimiento", cliente_membresia.fecha_fin.strftime("%d/%m/%Y") if cliente_membresia.fecha_fin else "N/A"],
        ["Horario de acceso", f"{membresia.hora_inicio_acceso} - {membresia.hora_fin_acceso}"],
        ["Permite congelamiento", "Si" if membresia.permite_congelamiento else "No"],
    ]
    tabla = Table(datos_tabla, colWidths=[5 * cm, 11 * cm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5F6FA")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 16))

    elementos.append(Paragraph("Clausulas", _estilo_seccion))
    clausulas_texto = config.clausulas_contrato or (
        "1. El cliente se compromete a hacer uso responsable de las instalaciones.\n"
        "2. La membresia es personal e intransferible.\n"
        "3. El gimnasio no se hace responsable por objetos de valor perdidos u olvidados.\n"
        "4. El incumplimiento de pago puede resultar en la suspension del servicio.\n"
        "5. El cliente declara estar en condiciones fisicas adecuadas para realizar actividad fisica."
    )
    for parrafo in clausulas_texto.split("\n"):
        if parrafo.strip():
            elementos.append(Paragraph(parrafo.strip(), _estilo_clausula))

    elementos.append(Spacer(1, 40))
    firma_tabla = Table([["_________________________", "_________________________"], ["Firma del Cliente", f"Firma de {config.nombre_gimnasio or 'el Gimnasio'}"]], colWidths=[8 * cm, 8 * cm])
    firma_tabla.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    elementos.append(firma_tabla)

    doc.build(elementos)
    return buffer.getvalue()
