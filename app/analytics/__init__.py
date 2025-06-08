# Create new file: app/analytics/__init__.py

from flask import Blueprint

bp = Blueprint('analytics', __name__)

from app.analytics import routes
