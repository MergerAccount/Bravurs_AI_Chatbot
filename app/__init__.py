from flask import Flask
from flask_cors import CORS
from app.routes import routes, frontend

def create_app():
    app = Flask(__name__, template_folder='../static/templates')  # Relative to app/ directory
    CORS(app, origins=["*"])
    app.register_blueprint(routes, url_prefix='/api/v1')
    app.register_blueprint(frontend)
    return app