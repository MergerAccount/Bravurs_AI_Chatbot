import os
from flask import Flask
from app.routes import routes, frontend
import app.logging_config

def create_app():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    templates_path = os.path.join(base_dir, "..", "static", "templates")
    static_path = os.path.join(base_dir, "..", "static")

    app = Flask(
        __name__,
        template_folder=templates_path,
        static_folder=static_path
    )

    app.register_blueprint(routes)
    app.register_blueprint(frontend)
    return app
