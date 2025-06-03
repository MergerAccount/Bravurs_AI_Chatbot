import os
from flask import Flask
from flask_cors import CORS
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

    # Enable CORS for WordPress integration
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",  # In production, specify your WordPress domain
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })

    app.register_blueprint(routes)
    app.register_blueprint(frontend)

    return app