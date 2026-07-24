# -*- coding: utf-8 -*-
"""
CRONOS SaaS — Inicio con tunel publico
Arranca Flask en puerto 5000 + tunel Cloudflare publico
Actualiza APP_URL en .env automaticamente
"""
import os, sys, re, time, subprocess, threading
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE    = Path(__file__).resolve().parent
CF      = BASE.parent / "cloudflared.exe"   # cloudflared.exe esta en music/
ENV     = BASE / ".env"
PORT    = 5000

CYAN  = "\033[96m"; VERDE = "\033[92m"; ROJO = "\033[91m"
BOLD  = "\033[1m";  RESET = "\033[0m";  AMARILLO = "\033[93m"


def actualizar_env(url: str):
    content = ENV.read_text(encoding="utf-8")
    content = re.sub(r'APP_URL=.*', f'APP_URL={url}', content)
    ENV.write_text(content, encoding="utf-8")


def main():
    print(f"\n{CYAN}{BOLD}  CRONOS SaaS — Iniciando servidor publico{RESET}\n")

    if not CF.exists():
        print(f"{ROJO}  ERROR: No se encontro cloudflared.exe en {CF}{RESET}")
        sys.exit(1)

    # 1. Inicializar BD
    print("  Verificando base de datos...")
    r = subprocess.run([sys.executable, str(BASE / "init_db.py")],
                       capture_output=True, text=True, cwd=str(BASE))
    if r.returncode == 0:
        print(f"  {VERDE}BD lista{RESET}")
    else:
        print(f"  {AMARILLO}BD warning: {r.stderr[:200]}{RESET}")

    # 2. Arrancar Flask
    print(f"\n  Iniciando Flask en puerto {PORT}...")
    flask_proc = subprocess.Popen(
        [sys.executable, str(BASE / "run.py")],
        cwd=str(BASE),
        env={**os.environ, "PORT": str(PORT), "FLASK_ENV": "production"},
        stdout=open(BASE / "saas_out.log", "w"),
        stderr=open(BASE / "saas_err.log", "w"),
    )
    time.sleep(3)
    if flask_proc.poll() is not None:
        print(f"{ROJO}  ERROR: Flask no arranco. Ver saas_err.log{RESET}")
        sys.exit(1)
    print(f"  {VERDE}Flask corriendo (PID {flask_proc.pid}){RESET}")

    # 3. Arrancar tunel Cloudflare
    print("\n  Creando tunel Cloudflare (10-20 segundos)...")
    cf_proc = subprocess.Popen(
        [str(CF), "tunnel", "--url", f"http://localhost:{PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        bufsize=1,
    )

    url_publica = None
    for line in cf_proc.stdout:
        line = line.strip()
        match = re.search(r'https://[\w\-]+\.trycloudflare\.com', line)
        if not match:
            match = re.search(r'https://[\w\-]+\.cfargotunnel\.com', line)
        if match:
            url_publica = match.group(0)
            break

    if not url_publica:
        print(f"{ROJO}  No se obtuvo URL publica. Revisa internet.{RESET}")
        flask_proc.terminate()
        sys.exit(1)

    # 4. Actualizar .env y mostrar URL
    actualizar_env(url_publica)
    print(f"\n{VERDE}{BOLD}  ============================================")
    print(f"   CRONOS SaaS LIVE:")
    print(f"   {url_publica}")
    print(f"  ============================================{RESET}")
    print(f"\n  Comparte este link. Los pagos con PayPal ya funcionan.")
    print(f"  Panel admin: {url_publica}/admin")
    print(f"  Pagos:       {url_publica}/pagar")
    print(f"\n  {ROJO}Ctrl+C para detener{RESET}\n")

    try:
        cf_proc.wait()
    except KeyboardInterrupt:
        print(f"\n{CYAN}  Deteniendo...{RESET}")
        cf_proc.terminate()
        flask_proc.terminate()
        actualizar_env("")
        print("  Servidor detenido.\n")


if __name__ == "__main__":
    main()
