import os
from flask import Flask, request, jsonify
from flask import Flask
from flask import Flask, request, jsonify
from flask_cors import CORS
from app.routes import routes, frontend
import app.logging_config
from app.rate_limiter import check_ip_rate_limit

from app.rate_limiter import check_ip_rate_limit

def create_app():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    templates_path = os.path.join(base_dir, "..", "static", "templates")
    static_path = os.path.join(base_dir, "..", "static")

    app = Flask(
        __name__,
        template_folder=templates_path,
        static_folder=static_path
    )

    # register the IP rate limit before request processing for API routes
    @app.before_request
    def before_api_request():
        # only apply this to API routes
        if request.path.startswith('/api/v1/'):
            user_ip = request.remote_addr
            # still need to get the true client IP from headers like 'X-Forwarded-For':
            # user_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

            allowed_ip, ip_retry_after = check_ip_rate_limit(user_ip)
            if not allowed_ip:
                return jsonify({"error": f"Too many requests from your IP address. Please try again in {ip_retry_after} seconds."}), 429, {'Retry-After': str(ip_retry_after)}


    # register the IP rate limit before request processing for API routes
    @app.before_request
    def before_api_request():
        # only apply this to API routes
        if request.path.startswith('/api/v1/'):
            user_ip = request.remote_addr
            # still need to get the true client IP from headers like 'X-Forwarded-For':
            # user_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

            allowed_ip, ip_retry_after = check_ip_rate_limit(user_ip)
            if not allowed_ip:
                return jsonify({"error": f"Too many requests from your IP address. Please try again in {ip_retry_after} seconds."}), 429, {'Retry-After': str(ip_retry_after)}

    # Enable CORS for WordPress integration
    CORS(app, resources={
        r"/api/*": {
            "origins": ["http://bravurwp.local", "https://bravurwp.local"],
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })

    app.register_blueprint(routes)
    app.register_blueprint(frontend)
    return app
