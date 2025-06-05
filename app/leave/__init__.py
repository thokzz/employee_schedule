# Create new file: app/leave/__init__.py

from flask import Blueprint

bp = Blueprint('leave', __name__)

from app.leave import routes
