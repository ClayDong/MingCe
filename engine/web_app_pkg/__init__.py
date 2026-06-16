"""web_app_pkg - Web application package for QLib+VNPY trading platform."""

import os

from flask import Flask


def create_app():
    """Flask application factory. Creates and configures the Flask app."""
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))

    from web_app_pkg.routes import bp
    app.register_blueprint(bp)

    return app
