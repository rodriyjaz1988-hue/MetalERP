"""Paquete de MetalERP: cada módulo es un área del sistema.

Importarlo registra todas las rutas en la app Flask (metalerp.nucleo.app).
"""
from . import (nucleo, esquema, comun, paginas, dashboard, usuarios, maquinas, materiales, productos,
               ventas, requerimientos, scheduling, ordenes, cajones, ott, mrp, novedades, lotes,
               compras, remitos, configuracion, pdfs, carga_masiva, sistema, ia, hmi, planta)
from .nucleo import app

MODULOS = [nucleo, esquema, comun, paginas, dashboard, usuarios, maquinas, materiales, productos,
           ventas, requerimientos, scheduling, ordenes, cajones, ott, mrp, novedades, lotes,
           compras, remitos, configuracion, pdfs, carga_masiva, sistema, ia, hmi, planta]
