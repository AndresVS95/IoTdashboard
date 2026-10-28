#!/usr/bin/env python3
"""
app.py — Servidor Flask para el dashboard de telemonitoreo
Sirve el HTML del dashboard y expone una API REST mínima.
Incluye autenticación básica HTTP.
"""

from flask import Flask, jsonify, request, render_template, abort
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os

# ─── Configuración ────────────────────────────────────────────────────────────
DB_PATH    = os.path.join(os.path.dirname(__file__), "telemonitoreo.db")
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
DEBUG      = False

# ── Credenciales ─────────────────────────────────────────────────────────────
# Cambia estos valores antes de poner en producción
USUARIOS = {
    "medico":  generate_password_hash("tele2024"),
    "admin":   generate_password_hash("admin1234"),
}

app  = Flask(__name__)
auth = HTTPBasicAuth()


@auth.verify_password
def verify_password(username, password):
    if username in USUARIOS and check_password_hash(USUARIOS[username], password):
        return username
    return None


# ─── Utilidad BD ──────────────────────────────────────────────────────────────
def query_db(sql, params=()):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def exec_db(sql, params=()):
    con = sqlite3.connect(DB_PATH)
    con.execute(sql, params)
    con.commit()
    con.close()


# ─── Rutas ────────────────────────────────────────────────────────────────────
@app.route("/")
@auth.login_required
def index():
    return render_template("dashboard.html")


@app.route("/api/historial")
@auth.login_required
def api_historial():
    limit = request.args.get("limit", 60, type=int)
    limit = max(1, min(limit, 500))
    rows = query_db("""
        SELECT ts, bpm, temperatura_corporal, temperatura_ambiente,
               humedad_ambiente, aceleracion, alerta, estado
        FROM lecturas
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows.reverse()
    return jsonify(rows)


@app.route("/api/rangos", methods=["GET"])
@auth.login_required
def api_get_rangos():
    rows = query_db("SELECT parametro, valor_min, valor_max FROM rangos")
    resultado = {r["parametro"]: {"min": r["valor_min"], "max": r["valor_max"]} for r in rows}
    return jsonify(resultado)


@app.route("/api/rangos", methods=["POST"])
@auth.login_required
def api_set_rangos():
    data = request.get_json(force=True, silent=True)
    if not data or "parametro" not in data:
        abort(400, "Body JSON requerido con campo 'parametro'")

    parametro = data["parametro"]
    valor_min = data.get("min")
    valor_max = data.get("max")

    if valor_min is None or valor_max is None:
        abort(400, "Faltan campos 'min' y/o 'max'")

    exec_db("""
        INSERT INTO rangos (parametro, valor_min, valor_max)
        VALUES (?, ?, ?)
        ON CONFLICT(parametro) DO UPDATE SET
            valor_min = excluded.valor_min,
            valor_max = excluded.valor_max
    """, (parametro, float(valor_min), float(valor_max)))

    return jsonify({"ok": True, "parametro": parametro, "min": valor_min, "max": valor_max})


@app.route("/api/estado")
@auth.login_required
def api_estado():
    rows = query_db("""
        SELECT ts, bpm, temperatura_corporal, temperatura_ambiente,
               humedad_ambiente, aceleracion, alerta, estado
        FROM lecturas
        ORDER BY id DESC
        LIMIT 1
    """)
    return jsonify(rows[0] if rows else {})


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print(f"⚠  Base de datos no encontrada en {DB_PATH}")
        print("   Ejecuta primero worker.py para inicializarla.")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=DEBUG)
