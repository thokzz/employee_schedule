from flask import Blueprint

bp = Blueprint('work_extension', __name__, url_prefix='/work-extension')

from app.work_extension import routes
