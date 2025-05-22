# import os
# from flask import Flask
# from app.routes import routes, frontend
# import app.logging_config
#
# def create_app():
#     base_dir = os.path.abspath(os.path.dirname(__file__))
#     templates_path = os.path.join(base_dir, "..", "static", "templates")
#     static_path = os.path.join(base_dir, "..", "static")
#
#     app = Flask(
#         __name__,
#         template_folder=templates_path,
#         static_folder=static_path
#     )
#
#     app.register_blueprint(routes)
#     app.register_blueprint(frontend)
#     return app


# -------------------- v2 ------------------
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

    # ✅ Fixed CORS handling: use * or list depending on the env variable
    raw_origins = os.environ.get("ALLOWED_ORIGINS", "*")
    if raw_origins.strip() == "*":
        CORS(app)  # allow all
        print("✅ CORS: All origins allowed")
    else:
        origin_list = [o.strip() for o in raw_origins.split(",")]
        CORS(app, resources={r"/api/v1/*": {"origins": origin_list}})
        print("✅ CORS origins:", origin_list)

    app.register_blueprint(routes)
    app.register_blueprint(frontend)
    return app
