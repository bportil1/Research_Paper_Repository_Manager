"""Application entry point.

During the first refactor commit, the existing application remains available
through ``legacy_app`` so behavior is preserved while code is migrated module by
module. New work should target the focused modules in this package.
"""
from backend.legacy_app import app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)
