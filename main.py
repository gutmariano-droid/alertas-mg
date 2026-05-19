"""
=============================================================
 AGENTE DE ALERTAS DE PRECIO — COCOS MG v2
 Tickers: AMD, TSM, AAPL, AMZN, TGSU2
 Notificaciones: Telegram
 Deploy: Railway / Replit
 Actualizado: 13/05/2026
=============================================================

PRECIOS BASE HOY 13/05/2026:
  AMD   → US$448-464  | Máx 52s: $469  | Target BofA: $500
  TSM   → US$403      | Máx 52s: $420  | Target consenso: $463
  AAPL  → US$299      | Máx 52s: $300  | Target consenso: $305
  AMZN  → US$243-268  | Máx ATH: $278  | Próx earnings: 30 jul
  TGSU2 → ARS 9.025   | Target 6M: ARS 15.500

LÓGICA DE NIVELES:
  - COMPRA: zona de soporte / corrección saludable (~8-10% bajo precio actual)
  - VENTA: target de analistas o resistencia técnica
  - STOP: nivel de ruptura de estructura bajista (~12-15% bajo precio actual)
  - RECOMPRA: si el precio cae al stop y rebota, señal de re-entrada

=============================================================

SETUP (5 minutos):
1. @BotFather en Telegram → /newbot → copiá el TOKEN
2. Mandá un msg a tu bot → abrí https://api.telegram.org/bot<TOKEN>/getUpdates
   → copiá el número en "chat":{"id": XXXXXXX}
3. Pegá TOKEN y CHAT_ID abajo
4. Subí a Replit → Run / Railway → Deploy

ANTI-SLEEP EN REPLIT (gratis):
  → uptimerobot.com → Add Monitor → HTTP(s) → URL de tu Repl → cada 5 min
=============================================================
"""

import yfinance as yf
import requests
import time
from datetime import datetime, time as dtime
import pytz
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# =============================================================
# ★ CONFIGURACIÓN — COMPLETÁ ESTOS DOS DATOS
# =============================================================
TELEGRAM_TOKEN   = "8638008808:AAHAiH4H1Wp38uvX5NYCS_PXtJkwiEssPO0"      # De @BotFather
TELEGRAM_CHAT_ID = "8972636454"    # Tu chat ID personal

# Intervalo de chequeo (segundos). 300 = cada 5 minutos
INTERVALO_SEGUNDOS = 300

# Zona horaria Argentina
TZ_ARG = pytz.timezone("America/Argentina/Buenos_Aires")

# =============================================================
# NIVELES — basados en precios reales del 13/05/2026
# =============================================================
#
#  compra    → entrá acá (zona de soporte o corrección saludable)
#  venta     → tomá ganancias acá (target analistas / resistencia)
#  stop      → salí con pérdida limitada si cae a este precio
#  recompra  → si tocó el stop y rebota, re-entrá acá (confirmación)
#
ALERTAS = {
    "AMD": {
        "nombre":   "AMD — Advanced Micro Devices",
        "compra":   415.0,   # -8% del precio actual ~$448
        "venta":    500.0,   # Target BofA actualizado hoy
        "stop":     385.0,   # -14% — ruptura de soporte clave
        "recompra": 400.0,   # Rebote desde zona de stop
        "nota":     "Earnings 4 ago | +114% YTD | BofA mantiene Buy",
    },
    "TSM": {
        "nombre":   "TSM — Taiwan Semiconductor",
        "compra":   375.0,   # -7% del actual $403, zona soporte
        "venta":    463.0,   # Target consenso 12M
        "stop":     350.0,   # -13% — bajo soporte estructural
        "recompra": 360.0,   # Re-entrada desde zona de stop
        "nota":     "Earnings 16 jul | Máx 52s: $420 | Compra fuerte 17/17",
    },
    "AAPL": {
        "nombre":   "AAPL — Apple",
        "compra":   280.0,   # -6.5% del actual $299, zona pre-WWDC
        "venta":    320.0,   # Target alto analistas (WWDC 8 jun)
        "stop":     260.0,   # -13% — bajo soporte técnico fuerte
        "recompra": 270.0,   # Re-entrada post-corrección
        "nota":     "WWDC 8 jun | Siri 2.0 + iPhone plegable | Máx 52s: $300",
    },
    "AMZN": {
        "nombre":   "AMZN — Amazon",
        "compra":   235.0,   # -3% del actual $243, entrada gradual
        "venta":    290.0,   # Target post-earnings julio
        "stop":     215.0,   # -11.5% — bajo soporte clave
        "recompra": 225.0,   # Re-entrada desde zona de stop
        "nota":     "Earnings 30 jul | AWS creciendo | ATH $278",
    },
    "TGSU2.BA": {
        "nombre":   "TGSU2 — Transp. Gas del Sur",
        "compra":   8200.0,  # ARS — -9% del actual ARS 9.025
        "venta":    12000.0, # ARS — camino al target 6M de ARS 15.500
        "stop":     7500.0,  # ARS — -17% — ruptura de soporte
        "recompra": 7800.0,  # ARS — re-entrada desde zona de stop
        "nota":     "Target 6M: ARS 15.500 (+71%) | Gas global en alza",
    },
}

# =============================================================
# FUNCIONES CORE
# =============================================================

def send_telegram(mensaje: str):
    """Envía mensaje a Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "HTML"
        }, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[ERROR Telegram] {e}")
        return False


def get_precio(ticker: str) -> float | None:
    """Obtiene el último precio de cierre / tiempo real via yfinance."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1d", interval="1m")
        if hist.empty:
            hist = t.history(period="2d")
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[-1]), 2)
    except Exception as e:
        print(f"[ERROR precio {ticker}] {e}")
        return None


def evaluar(ticker: str, precio: float, cfg: dict) -> str | None:
    """Devuelve mensaje de alerta si el precio toca un nivel clave."""
    nombre    = cfg["nombre"]
    compra    = cfg["compra"]
    venta     = cfg["venta"]
    stop      = cfg["stop"]
    recompra  = cfg["recompra"]
    nota      = cfg.get("nota", "")
    ahora_str = datetime.now(TZ_ARG).strftime("%d/%m/%Y %H:%M")

    tol = 0.008  # 0.8% de tolerancia para evitar spam

    if precio <= compra * (1 + tol):
        upside = round((venta - precio) / precio * 100, 1)
        return (
            f"🟢 <b>ZONA DE COMPRA — {nombre}</b>\n"
            f"💰 Precio: <b>${precio:,.2f}</b>\n"
            f"📍 Nivel entrada: ${compra:,.2f}\n"
            f"🎯 Target venta: ${venta:,.2f} (+{upside}%)\n"
            f"🛑 Stop loss: ${stop:,.2f}\n"
            f"🔄 Recompra si baja a: ${recompra:,.2f}\n"
            f"📌 {nota}\n"
            f"⏰ {ahora_str}"
        )
    elif precio >= venta * (1 - tol):
        ganancia = round((precio - compra) / compra * 100, 1)
        return (
            f"🔴 <b>TOMÁ GANANCIAS — {nombre}</b>\n"
            f"💰 Precio: <b>${precio:,.2f}</b>\n"
            f"🎯 Target alcanzado: ${venta:,.2f}\n"
            f"📈 Potencial ganancia desde entrada: +{ganancia}%\n"
            f"💡 Considerá vender total o parcial\n"
            f"🔄 Re-entrada en: ${recompra:,.2f}\n"
            f"⏰ {ahora_str}"
        )
    elif precio <= stop * (1 + tol):
        perdida = round((compra - precio) / compra * 100, 1)
        return (
            f"⛔ <b>STOP LOSS — {nombre}</b>\n"
            f"💰 Precio: <b>${precio:,.2f}</b>\n"
            f"🛑 Stop tocado: ${stop:,.2f}\n"
            f"📉 Caída desde entrada estimada: -{perdida}%\n"
            f"⚠️ Revisá tu posición — considerá salir\n"
            f"🔄 Zona de recompra: ${recompra:,.2f}\n"
            f"⏰ {ahora_str}"
        )
    elif precio <= recompra * (1 + tol) and precio > stop:
        return (
            f"🔄 <b>ZONA DE RECOMPRA — {nombre}</b>\n"
            f"💰 Precio: <b>${precio:,.2f}</b>\n"
            f"📍 Rebote desde zona de stop\n"
            f"🎯 Target: ${venta:,.2f}\n"
            f"🛑 Stop loss: ${stop:,.2f}\n"
            f"⏰ {ahora_str}"
        )
    return None


def resumen_cartera() -> str:
    """Genera resumen visual de todos los tickers."""
    ahora_str = datetime.now(TZ_ARG).strftime("%d/%m %H:%M")
    lineas = [f"📊 <b>Resumen cartera MG — {ahora_str}</b>\n"]

    for ticker, cfg in ALERTAS.items():
        precio = get_precio(ticker)
        nombre = cfg["nombre"].split("—")[0].strip()

        if precio is None:
            lineas.append(f"❓ {nombre}: sin datos")
            continue

        compra = cfg["compra"]
        venta  = cfg["venta"]
        stop   = cfg["stop"]

        # Emoji por posición en el rango compra→venta
        if precio <= stop:
            emoji = "🔴"
        elif precio <= compra:
            emoji = "🟢"
        elif precio >= venta:
            emoji = "🏁"
        else:
            pct = (precio - compra) / (venta - compra)
            emoji = "🟡" if pct < 0.4 else "🟠" if pct < 0.75 else "🔥"

        dist_venta = round((venta - precio) / precio * 100, 1)
        lineas.append(
            f"{emoji} <b>{nombre}</b>: ${precio:,.2f} "
            f"| 🎯 {dist_venta:+.1f}% al target"
        )

    lineas.append("\n🟢=Zona compra  🟡=Subiendo  🔥=Cerca target  🏁=Vendé")
    return "\n".join(lineas)


# =============================================================
# LOOP PRINCIPAL
# =============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # Silence default request logging


def start_health_server(port=8080):
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"🌐 Health server corriendo en puerto {port}")


def main():
    print("🚀 Agente MG v2 iniciando...")
    start_health_server(port=8000)

    if TELEGRAM_TOKEN == "TU_TOKEN_AQUI" or TELEGRAM_CHAT_ID == "TU_CHAT_ID_AQUI":
        print("❌ ERROR: Completá TELEGRAM_TOKEN y TELEGRAM_CHAT_ID antes de correr.")
        return

    # Mensaje de inicio
    tickers_str = " | ".join(cfg["nombre"].split("—")[0].strip() for cfg in ALERTAS.values())
    send_telegram(
        f"🤖 <b>Agente MG v2 activo</b>\n"
        f"📋 {tickers_str}\n"
        f"⏱ Chequeo cada {INTERVALO_SEGUNDOS // 60} minutos\n"
        f"Alertas: 🟢Compra | 🔴Venta | ⛔Stop | 🔄Recompra"
    )

    # Resumen inicial
    send_telegram(resumen_cartera())

    # Registro para evitar spam (no repetir misma alerta por 2 horas)
    cooldown: dict = {}
    ciclo = 0

    while True:
        ciclo += 1
        ts = datetime.now(TZ_ARG).strftime("%H:%M:%S")
        print(f"\n[{ts}] Ciclo #{ciclo}")

        for ticker, cfg in ALERTAS.items():
            precio = get_precio(ticker)
            if precio is None:
                print(f"  ⚠️  {ticker}: sin precio")
                continue

            nombre_corto = cfg["nombre"].split("—")[0].strip()
            print(f"  {nombre_corto}: ${precio:,.2f}")

            msg = evaluar(ticker, precio, cfg)
            if msg:
                ahora = datetime.now(TZ_ARG)
                ultima = cooldown.get(ticker)
                if ultima is None or (ahora - ultima).seconds > 7200:
                    if send_telegram(msg):
                        cooldown[ticker] = ahora
                        print(f"  ✅ Alerta enviada: {ticker}")

        # Resumen cada 48 ciclos (~4hs con intervalo de 5min)
        if ciclo % 48 == 0:
            send_telegram(resumen_cartera())

        time.sleep(INTERVALO_SEGUNDOS)


if __name__ == "__main__":
    main()
