# -*- coding: utf-8 -*-
"""
Crea todos los productos de Cronos en Lemon Squeezy y guarda los Variant IDs en .env
Ejecutar UNA sola vez: python setup_lemonsqueezy.py
"""
import os, sys, json, time, re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

try:
    import requests
except ImportError:
    print("Instalando requests...")
    os.system("pip install requests -q")
    import requests

LS_KEY      = os.environ.get("LEMONSQUEEZY_API_KEY", "")
LS_STORE_ID = os.environ.get("LEMONSQUEEZY_STORE_ID", "")

if not LS_KEY:
    print("ERROR: LEMONSQUEEZY_API_KEY no configurada en .env")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {LS_KEY}",
    "Accept":        "application/vnd.api+json",
    "Content-Type":  "application/vnd.api+json",
}

BASE = "https://api.lemonsqueezy.com/v1"

# ─── Paso 1: obtener Store ID si no está configurado ──────────────────────────
def get_store_id():
    global LS_STORE_ID
    if LS_STORE_ID:
        return LS_STORE_ID
    print("Consultando Store ID...")
    r = requests.get(f"{BASE}/stores", headers=HEADERS, timeout=20)
    r.raise_for_status()
    stores = r.json().get("data", [])
    if not stores:
        print("ERROR: No hay tiendas en esta cuenta LS")
        sys.exit(1)
    store = stores[0]
    LS_STORE_ID = store["id"]
    nombre = store["attributes"]["name"]
    print(f"  Store encontrado: {nombre} (ID={LS_STORE_ID})")
    return LS_STORE_ID

# ─── Productos a crear ────────────────────────────────────────────────────────
# formato: (env_var, nombre_producto, descripcion, precio_usd_centavos)
PRODUCTOS = [
    # Paquetes de créditos (pagos únicos)
    ("LS_VARIANT_PACK_50",
     "Pack 50 Créditos Cronos",
     "50 créditos para usar en cualquier bot de Cronos AI",
     499),
    ("LS_VARIANT_PACK_150",
     "Pack 150 Créditos Cronos",
     "150 créditos para usar en cualquier bot de Cronos AI — ahorro del 13%",
     1299),
    ("LS_VARIANT_PACK_500",
     "Pack 500 Créditos Cronos",
     "500 créditos para usar en cualquier bot de Cronos AI — mejor valor",
     3499),

    # Bots individuales
    ("LS_VARIANT_HOROSCOPO",
     "Bot Horóscopo Diario — Licencia",
     "Bot que genera 12 videos de horóscopo diarios y los publica en YouTube automáticamente",
     120000),
    ("LS_VARIANT_MOTIVACION",
     "Bot Motivación — Licencia",
     "Bot de videos motivacionales para Facebook y YouTube con IA y voz humana",
     100000),
    ("LS_VARIANT_CRISTIANO",
     "Bot Cristiano — Licencia",
     "Bot de contenido cristiano: fotos, shorts y videos largos para FB y YouTube",
     120000),
    ("LS_VARIANT_NOTICIAS",
     "Bot Noticias RD — Licencia",
     "Bot de noticias dominicanas: scraping RSS, video PIL+TTS, miniatura CNN-style",
     150000),
    ("LS_VARIANT_MUSIC_VIDEO",
     "Bot Music Video — Licencia",
     "Crea videos musicales con letra sincronizada al beat y los publica en YouTube",
     180000),
    ("LS_VARIANT_VEHICULOS",
     "Bot Vehículos — Licencia",
     "Bot de reels de vehículos para Facebook: genera videos PIL con especificaciones",
     140000),
    ("LS_VARIANT_DISTROKID",
     "Bot DistroKid — Licencia",
     "Sube álbumes WAV a DistroKid automáticamente con portadas generadas por IA",
     200000),
    ("LS_VARIANT_AVATAR",
     "Bot Avatar Livestream — Licencia",
     "Avatar animado con lip-sync para livestream + respuesta automática al chat",
     250000),

    # Código fuente
    ("LS_VARIANT_CODIGO_FUENTE",
     "Código Fuente Completo Cronos",
     "Todos los bots + dashboard Cronos — código fuente completo con soporte 6 meses",
     380000),
]

# ─── Crear producto + variante en LS ─────────────────────────────────────────
def crear_producto(store_id, nombre, descripcion, precio_centavos):
    payload = {
        "data": {
            "type": "products",
            "attributes": {
                "name":        nombre,
                "description": descripcion,
            },
            "relationships": {
                "store": {
                    "data": {"type": "stores", "id": str(store_id)}
                }
            }
        }
    }
    r = requests.post(f"{BASE}/products", headers=HEADERS, json=payload, timeout=20)
    if r.status_code not in (200, 201):
        print(f"  ERROR creando producto: {r.status_code} {r.text[:300]}")
        return None, None
    prod = r.json()["data"]
    prod_id = prod["id"]

    # Crear variante (precio)
    var_payload = {
        "data": {
            "type": "variants",
            "attributes": {
                "name":        "Estándar",
                "price":       precio_centavos,
                "is_subscription": False,
            },
            "relationships": {
                "product": {
                    "data": {"type": "products", "id": prod_id}
                }
            }
        }
    }
    rv = requests.post(f"{BASE}/variants", headers=HEADERS, json=var_payload, timeout=20)
    if rv.status_code not in (200, 201):
        # LS a veces crea la variante automáticamente — buscarla
        time.sleep(1)
        rvl = requests.get(f"{BASE}/variants?filter[product_id]={prod_id}", headers=HEADERS, timeout=20)
        if rvl.status_code == 200:
            vdata = rvl.json().get("data", [])
            if vdata:
                return prod_id, vdata[0]["id"]
        print(f"  ERROR creando variante: {rv.status_code} {rv.text[:300]}")
        return prod_id, None

    var_id = rv.json()["data"]["id"]
    return prod_id, var_id

# ─── Guardar variant IDs en .env ──────────────────────────────────────────────
def actualizar_env(env_var, variant_id):
    env_path = Path(__file__).parent / ".env"
    texto = env_path.read_text(encoding="utf-8")
    patron = rf"({re.escape(env_var)}=)(.*)"
    nuevo  = rf"\g<1>{variant_id}"
    texto2 = re.sub(patron, nuevo, texto)
    env_path.write_text(texto2, encoding="utf-8")

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("CRONOS — Configuración automática de Lemon Squeezy")
    print("=" * 60)

    store_id = get_store_id()

    # Guardar store ID en .env
    actualizar_env("LEMONSQUEEZY_STORE_ID", store_id)
    print(f"\nStore ID guardado: {store_id}")

    resultados = {}
    print(f"\nCreando {len(PRODUCTOS)} productos...\n")

    for env_var, nombre, desc, precio in PRODUCTOS:
        # Verificar si ya tiene ID
        env_path = Path(__file__).parent / ".env"
        texto = env_path.read_text(encoding="utf-8")
        match = re.search(rf"{re.escape(env_var)}=(.+)", texto)
        if match and match.group(1).strip() and match.group(1).strip() != "":
            existing = match.group(1).strip()
            print(f"  [YA EXISTE] {env_var} = {existing}")
            resultados[env_var] = existing
            continue

        print(f"  Creando: {nombre} (${precio/100:.2f})...")
        prod_id, var_id = crear_producto(store_id, nombre, desc, precio)

        if var_id:
            actualizar_env(env_var, var_id)
            resultados[env_var] = var_id
            print(f"    Producto ID: {prod_id} | Variant ID: {var_id} ✓")
        else:
            print(f"    ERROR — configura {env_var} manualmente")
            resultados[env_var] = "ERROR"

        time.sleep(1.5)  # Respetar rate limit de LS

    print("\n" + "=" * 60)
    print("RESUMEN DE VARIANT IDs:")
    print("=" * 60)
    for k, v in resultados.items():
        print(f"  {k} = {v}")

    errores = [k for k, v in resultados.items() if v == "ERROR"]
    if errores:
        print(f"\nATENCION: {len(errores)} productos con error — configura manualmente en .env")
    else:
        print("\nTodo configurado! Reinicia el servidor Cronos.")

if __name__ == "__main__":
    main()
