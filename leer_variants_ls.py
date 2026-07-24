# -*- coding: utf-8 -*-
"""
Lee todos los productos/variantes de Lemon Squeezy y muestra sus IDs.
Usar para copiar los Variant IDs al .env despues de crear productos manualmente.
"""
import os, re, json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import requests

LS_KEY      = os.environ.get("LEMONSQUEEZY_API_KEY", "")
LS_STORE_ID = os.environ.get("LEMONSQUEEZY_STORE_ID", "422101")

HEADERS = {
    "Authorization": f"Bearer {LS_KEY}",
    "Accept":        "application/vnd.api+json",
}
BASE = "https://api.lemonsqueezy.com/v1"

# Mapeo de palabras clave del nombre del producto → variable .env
KEYWORD_MAP = {
    "50 cr":        "LS_VARIANT_PACK_50",
    "150 cr":       "LS_VARIANT_PACK_150",
    "500 cr":       "LS_VARIANT_PACK_500",
    "hor":          "LS_VARIANT_HOROSCOPO",
    "motiv":        "LS_VARIANT_MOTIVACION",
    "cristi":       "LS_VARIANT_CRISTIANO",
    "notici":       "LS_VARIANT_NOTICIAS",
    "music":        "LS_VARIANT_MUSIC_VIDEO",
    "vehic":        "LS_VARIANT_VEHICULOS",
    "distro":       "LS_VARIANT_DISTROKID",
    "avatar":       "LS_VARIANT_AVATAR",
    "fuente":       "LS_VARIANT_CODIGO_FUENTE",
    "codigo":       "LS_VARIANT_CODIGO_FUENTE",
}

def actualizar_env(env_var, valor):
    env_path = Path(__file__).parent / ".env"
    texto = env_path.read_text(encoding="utf-8")
    patron = rf"({re.escape(env_var)}=)(.*)"
    texto2 = re.sub(patron, rf"\g<1>{valor}", texto)
    env_path.write_text(texto2, encoding="utf-8")

def main():
    print("=" * 60)
    print("Leyendo productos de Lemon Squeezy...")
    print("=" * 60)

    # Obtener productos
    r = requests.get(f"{BASE}/products?filter[store_id]={LS_STORE_ID}&include=variants",
                     headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()

    productos = data.get("data", [])
    variantes = {v["id"]: v for v in data.get("included", []) if v["type"] == "variants"}

    print(f"\nProductos encontrados: {len(productos)}\n")

    mapeados = {}
    sin_mapear = []

    for prod in productos:
        nombre  = prod["attributes"]["name"]
        prod_id = prod["id"]
        precio  = prod["attributes"].get("price", 0)

        # Obtener variantes de este producto
        var_ids = [r2["id"] for r2 in prod.get("relationships", {}).get("variants", {}).get("data", [])]

        print(f"  Producto: {nombre}")
        print(f"    Product ID: {prod_id}")

        for vid in var_ids:
            v = variantes.get(vid)
            if v:
                vp = v["attributes"].get("price", 0)
                print(f"    Variant ID: {vid}  (${vp/100:.2f})")

        # Intentar mapear automáticamente
        nombre_lower = nombre.lower()
        env_var = None
        for kw, var in KEYWORD_MAP.items():
            if kw in nombre_lower:
                env_var = var
                break

        if env_var and var_ids:
            mapeados[env_var] = var_ids[0]
            print(f"    Mapeado → {env_var}")
        else:
            sin_mapear.append((nombre, var_ids))
            print(f"    SIN MAPEAR — asigna manualmente")

        print()

    # Guardar en .env
    if mapeados:
        print("=" * 60)
        print("Guardando en .env...")
        for env_var, var_id in mapeados.items():
            actualizar_env(env_var, var_id)
            print(f"  {env_var} = {var_id}")
        print("\n.env actualizado!")

    if sin_mapear:
        print("\nProductos sin mapear automaticamente:")
        for nombre, vids in sin_mapear:
            print(f"  '{nombre}' → Variant IDs: {vids}")
        print("Agrega manualmente estas lineas al .env")

    print("\n" + "=" * 60)
    print("PRODUCTOS QUE FALTAN CREAR en app.lemonsqueezy.com/products:")
    print("=" * 60)
    productos_necesarios = [
        ("Pack 50 Créditos Cronos",          "$4.99",    "LS_VARIANT_PACK_50"),
        ("Pack 150 Créditos Cronos",         "$12.99",   "LS_VARIANT_PACK_150"),
        ("Pack 500 Créditos Cronos",         "$34.99",   "LS_VARIANT_PACK_500"),
        ("Bot Horóscopo Diario — Licencia",  "$1,200",   "LS_VARIANT_HOROSCOPO"),
        ("Bot Motivación — Licencia",        "$1,000",   "LS_VARIANT_MOTIVACION"),
        ("Bot Cristiano — Licencia",         "$1,200",   "LS_VARIANT_CRISTIANO"),
        ("Bot Noticias RD — Licencia",       "$1,500",   "LS_VARIANT_NOTICIAS"),
        ("Bot Music Video — Licencia",       "$1,800",   "LS_VARIANT_MUSIC_VIDEO"),
        ("Bot Vehículos — Licencia",         "$1,400",   "LS_VARIANT_VEHICULOS"),
        ("Bot DistroKid — Licencia",         "$2,000",   "LS_VARIANT_DISTROKID"),
        ("Bot Avatar Livestream — Licencia", "$2,500",   "LS_VARIANT_AVATAR"),
        ("Código Fuente Completo Cronos",    "$3,800",   "LS_VARIANT_CODIGO_FUENTE"),
    ]
    ya_mapeados = set(mapeados.keys())
    for nombre, precio, env_var in productos_necesarios:
        estado = "✓ LISTO" if env_var in ya_mapeados else "✗ FALTA"
        print(f"  {estado}  {nombre:45} {precio:>8}  → {env_var}")

if __name__ == "__main__":
    main()
