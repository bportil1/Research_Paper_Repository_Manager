from __future__ import annotations

from flask import Flask, send_from_directory

from reference_manager.web.routes.checkpoint_routes import bp as checkpoint_bp
from reference_manager.web.routes.config_routes import bp as config_bp
from reference_manager.web.routes.import_routes import bp as import_bp
from reference_manager.web.routes.job_routes import bp as job_bp
from reference_manager.web.routes.library_routes import bp as library_bp
from reference_manager.web.routes.metadata_routes import bp as metadata_bp
from reference_manager.web.routes.paper_routes import bp as paper_bp


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static")
    for blueprint in (
        config_bp,
        job_bp,
        library_bp,
        paper_bp,
        import_bp,
        metadata_bp,
        checkpoint_bp,
    ):
        app.register_blueprint(blueprint)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)
