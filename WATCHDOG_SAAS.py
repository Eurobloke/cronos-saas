# -*- coding: utf-8 -*-
"""
CRONOS SaaS Watchdog — Reinicia el servidor si se cae
Corre en segundo plano y vigila que Flask + Cloudflare sigan activos.
"""
import os, sys, re, time, subprocess, threading, socket
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE    = Path(__file__).resolve().parent
CF      = BASE.parent / "cloudflared.exe"
ENV     = BASE / ".env"
PORT    = 5000
CHECK_INTERVAL = 30   # segundos entre checks
FLASK_PROC  = None
CF_PROC     = None

def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def actualizar_env(url: str):
    try:
        content = ENV.read_text(encoding="utf-8")
        content = re.sub(r'APP_URL=.*', f'APP_URL={url}', content)
        ENV.write_text(content, encoding="utf-8")
    except Exception as e:
        log(f"No se pudo actualizar .env: {e}")

def flask_esta_vivo():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=3):
            return True
    except:
        return False

def arrancar_flask():
    global FLASK_PROC
    log(f"Arrancando Flask en puerto {PORT}...")
    FLASK_PROC = subprocess.Popen(
        [sys.executable, str(BASE / "run.py")],
        cwd=str(BASE),
        env={**os.environ, "PORT": str(PORT), "FLASK_ENV": "production"},
        stdout=open(BASE / "saas_out.log", "a"),
        stderr=open(BASE / "saas_err.log", "a"),
    )
    time.sleep(4)
    if flask_esta_vivo():
        log(f"Flask OK (PID {FLASK_PROC.pid})")
        return True
    log("Flask NO arranco. Ver saas_err.log")
    return False

def arrancar_tunel():
    global CF_PROC
    if not CF.exists():
        log("cloudflared.exe no encontrado")
        return
    log("Arrancando tunel Cloudflare...")
    CF_PROC = subprocess.Popen(
        [str(CF), "tunnel", "--url", f"http://localhost:{PORT}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    url_publica = None
    for line in CF_PROC.stdout:
        m = re.search(r'https://[\w\-]+\.trycloudflare\.com', line)
        if not m:
            m = re.search(r'https://[\w\-]+\.cfargotunnel\.com', line)
        if m:
            url_publica = m.group(0)
            break
    if url_publica:
        actualizar_env(url_publica)
        log(f"Tunel activo: {url_publica}")
    else:
        log("No se obtuvo URL del tunel")

def vigilar():
    global FLASK_PROC, CF_PROC
    while True:
        time.sleep(CHECK_INTERVAL)
        # Revisar Flask
        if not flask_esta_vivo() or (FLASK_PROC and FLASK_PROC.poll() is not None):
            log("ALERTA: Flask caido. Reiniciando...")
            if FLASK_PROC:
                try: FLASK_PROC.terminate()
                except: pass
            arrancar_flask()
        # Revisar tunel
        if CF_PROC and CF_PROC.poll() is not None:
            log("ALERTA: Tunel caido. Reiniciando...")
            arrancar_tunel()

def main():
    log("=== CRONOS SaaS Watchdog iniciado ===")
    # Arrancar Flask
    if not flask_esta_vivo():
        if not arrancar_flask():
            sys.exit(1)
    else:
        log(f"Flask ya esta corriendo en puerto {PORT}")
    # Arrancar tunel
    arrancar_tunel()
    # Vigilancia en hilo daemon
    t = threading.Thread(target=vigilar, daemon=True)
    t.start()
    log(f"Vigilando cada {CHECK_INTERVAL}s. Ctrl+C para detener.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log("Watchdog detenido.")
        if CF_PROC: CF_PROC.terminate()
        if FLASK_PROC: FLASK_PROC.terminate()

if __name__ == "__main__":
    main()
