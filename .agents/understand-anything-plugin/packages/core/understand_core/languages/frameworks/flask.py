"""Port of ``frameworks/flask.ts``."""

from __future__ import annotations

from ..types import FrameworkConfig

flask_config = FrameworkConfig(
    id="flask",
    displayName="Flask",
    languages=["python"],
    detectionKeywords=["flask", "flask-restful", "flask-sqlalchemy", "flask-marshmallow", "flask-wtf"],
    manifestFiles=["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"],
    promptSnippetPath="skills/understand-framework/prompts/flask.md",
    entryPoints=["app.py", "run.py", "wsgi.py"],
    layerHints={
        "blueprints": "api",
        "views": "api",
        "models": "data",
        "forms": "ui",
        "templates": "ui",
        "extensions": "config",
    },
)
