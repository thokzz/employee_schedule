# app/backup/__init__.py
from flask import Blueprint

bp = Blueprint('backup', __name__)

from app.backup import routes