#!/usr/bin/env python3
import os
from app import create_app
from app.models import db, User, Section, Unit, Shift, UserRole
from flask_migrate import upgrade
from sqlalchemy.exc import IntegrityError

app = create_app(os.getenv('FLASK_CONFIG') or 'default')

@app.shell_context_processor
def make_shell_context():
    return {'db': db, 'User': User, 'Section': Section, 'Unit': Unit, 'Shift': Shift}

@app.cli.command()
def deploy():
    db.create_all()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
