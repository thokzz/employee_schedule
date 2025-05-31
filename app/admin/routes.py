from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.admin import bp
from app.models import User, Section, Unit, UserRole, db
from functools import wraps

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.can_admin():
            flash('Administrator access required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/')
@login_required
@admin_required
def admin_dashboard():
    stats = {
        'total_users': User.query.count(),
        'active_users': User.query.filter_by(is_active=True).count(),
        'total_sections': Section.query.count(),
        'total_units': Unit.query.count()
    }
    return render_template('admin/dashboard.html', stats=stats)

@bp.route('/users')
@login_required
@admin_required
def manage_users():
    users = User.query.all()
    sections = Section.query.all()
    units = Unit.query.all()
    return render_template('admin/users.html', users=users, sections=sections, units=units)

@bp.route('/users/create', methods=['POST'])
@login_required
@admin_required
def create_user():
    user = User(
        username=request.form['username'],
        email=request.form['email'],
        first_name=request.form['first_name'],
        last_name=request.form['last_name'],
        role=UserRole(request.form['role']),
        section_id=request.form.get('section_id') or None,
        unit_id=request.form.get('unit_id') or None
    )
    user.set_password(request.form['password'])
    
    db.session.add(user)
    db.session.commit()
    
    flash(f'User {user.username} created successfully!', 'success')
    return redirect(url_for('admin.manage_users'))

@bp.route('/sections')
@login_required
@admin_required
def manage_sections():
    sections = Section.query.all()
    return render_template('admin/sections.html', sections=sections)

@bp.route('/sections/create', methods=['POST'])
@login_required
@admin_required
def create_section():
    section = Section(
        name=request.form['name'],
        description=request.form.get('description', '')
    )
    db.session.add(section)
    db.session.commit()
    
    flash(f'Section "{section.name}" created successfully!', 'success')
    return redirect(url_for('admin.manage_sections'))

@bp.route('/units/create', methods=['POST'])
@login_required
@admin_required
def create_unit():
    unit = Unit(
        name=request.form['name'],
        description=request.form.get('description', ''),
        section_id=request.form['section_id']
    )
    db.session.add(unit)
    db.session.commit()
    
    flash(f'Unit "{unit.name}" created successfully!', 'success')
    return redirect(url_for('admin.manage_units'))
