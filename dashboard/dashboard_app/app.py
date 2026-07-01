from __future__ import annotations

import threading

from flask import Flask, jsonify, render_template

from . import state as app_state
from .config import DASHBOARD_PORT
from .poller import poll
from .state import snapshot


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/api")
    def api():
        return jsonify(snapshot())

    @app.route("/")
    def home():
        return render_template("dashboard.html")

    return app


def start_polling():
    if app_state.polling_started:
        return
    app_state.polling_started = True
    threading.Thread(target=poll, daemon=True).start()


def run():
    app = create_app()
    start_polling()
    app.run(host="0.0.0.0", port=DASHBOARD_PORT)
