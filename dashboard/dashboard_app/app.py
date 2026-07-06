from __future__ import annotations

import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, send_from_directory

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
        react_index = Path(app.static_folder) / "react" / "index.html"
        if react_index.exists():
            return send_from_directory(react_index.parent, react_index.name)
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
