from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.admin import bp
from app.models import User, Section, Unit, UserRole, db
from functools import wraps
from datetime import datetime, date

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

# ==================== USER MANAGEMENT ====================

@bp.route('/users')
@login_required
@admin_required
def manage_users():
    users = User.query.all()
    sections = Section.query.all()
    units = Unit.query.all()
    return render_template('admin/users.html', users=users, sections=sections, units=units)

@bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    if request.method == 'GET':
        sections = Section.query.all()
        units = Unit.query.all()
        return render_template('admin/create_user.html', sections=sections, units=units)
    
    try:
        user = User(
            username=request.form['username'],
            email=request.form['email'],
            first_name=request.form['first_name'],
            last_name=request.form['last_name'],
            role=UserRole(request.form['role']),
            section_id=request.form.get('section_id') or None,
            unit_id=request.form.get('unit_id') or None,
            # NEW: Handle additional employment fields
            personnel_number=request.form.get('personnel_number') or None,
            typecode=request.form.get('typecode') or None,
            id_number=request.form.get('id_number') or None,
            job_title=request.form.get('job_title') or None,
            rank=request.form.get('rank') or None
        )
        
        # Handle hiring date
        hiring_date_str = request.form.get('hiring_date')
        if hiring_date_str:
            user.hiring_date = datetime.strptime(hiring_date_str, '%Y-%m-%d').date()
        
        user.set_password(request.form['password'])
        
        db.session.add(user)
        db.session.commit()
        
        flash(f'User {user.username} created successfully!', 'success')
        return redirect(url_for('admin.manage_users'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating user: {str(e)}', 'danger')
        return redirect(url_for('admin.create_user'))

@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if request.method == 'GET':
        sections = Section.query.all()
        units = Unit.query.all()
        return render_template('admin/edit_user.html', user=user, sections=sections, units=units)
    
    try:
        user.first_name = request.form['first_name']
        user.last_name = request.form['last_name']
        user.email = request.form['email']
        user.role = UserRole(request.form['role'])
        user.section_id = request.form.get('section_id') or None
        user.unit_id = request.form.get('unit_id') or None
        
        # NEW: Handle additional employment fields
        user.personnel_number = request.form.get('personnel_number') or None
        user.typecode = request.form.get('typecode') or None
        user.id_number = request.form.get('id_number') or None
        user.job_title = request.form.get('job_title') or None
        user.rank = request.form.get('rank') or None
        
        # Handle hiring date
        hiring_date_str = request.form.get('hiring_date')
        if hiring_date_str:
            user.hiring_date = datetime.strptime(hiring_date_str, '%Y-%m-%d').date()
        else:
            user.hiring_date = None
        
        # Update password only if provided
        if request.form.get('password'):
            user.set_password(request.form['password'])
        
        db.session.commit()
        flash(f'User {user.username} updated successfully!', 'success')
        return redirect(url_for('admin.manage_users'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating user: {str(e)}', 'danger')
        return redirect(url_for('admin.edit_user', user_id=user_id))

@bp.route('/users/<int:user_id>/toggle-status')
@login_required
@admin_required
def toggle_user_status(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    
    status = 'activated' if user.is_active else 'deactivated'
    flash(f'User {user.username} has been {status}.', 'success')
    return redirect(url_for('admin.manage_users'))

@bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    
    # Prevent deleting the current admin user
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin.manage_users'))
    
    try:
        username = user.username
        db.session.delete(user)
        db.session.commit()
        flash(f'User {username} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'danger')
    
    return redirect(url_for('admin.manage_users'))

# ==================== SECTION MANAGEMENT ====================

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
    try:
        section = Section(
            name=request.form['name'],
            description=request.form.get('description', '')
        )
        db.session.add(section)
        db.session.commit()
        
        flash(f'Section "{section.name}" created successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating section: {str(e)}', 'danger')
    
    return redirect(url_for('admin.manage_sections'))

@bp.route('/sections/<int:section_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_section(section_id):
    section = Section.query.get_or_404(section_id)
    
    if request.method == 'GET':
        # Get users in this section and users not assigned to any section
        section_users = User.query.filter_by(section_id=section_id).all()
        unassigned_users = User.query.filter_by(section_id=None).all()
        other_users = User.query.filter(User.section_id != section_id, User.section_id != None).all()
        
        return render_template('admin/edit_section.html', 
                             section=section, 
                             section_users=section_users,
                             unassigned_users=unassigned_users,
                             other_users=other_users)
    
    try:
        section.name = request.form['name']
        section.description = request.form.get('description', '')
        db.session.commit()
        
        flash(f'Section "{section.name}" updated successfully!', 'success')
        return redirect(url_for('admin.manage_sections'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating section: {str(e)}', 'danger')
        return redirect(url_for('admin.edit_section', section_id=section_id))

@bp.route('/sections/<int:section_id>/add-user', methods=['POST'])
@login_required
@admin_required
def add_user_to_section(section_id):
    section = Section.query.get_or_404(section_id)
    user_id = request.form.get('user_id')
    
    if user_id:
        user = User.query.get(user_id)
        if user:
            user.section_id = section_id
            # Reset unit if moving between sections
            if user.unit and user.unit.section_id != section_id:
                user.unit_id = None
            db.session.commit()
            flash(f'User {user.full_name} added to section {section.name}!', 'success')
        else:
            flash('User not found.', 'danger')
    else:
        flash('Please select a user.', 'warning')
    
    return redirect(url_for('admin.edit_section', section_id=section_id))

@bp.route('/sections/<int:section_id>/remove-user/<int:user_id>')
@login_required
@admin_required
def remove_user_from_section(section_id, user_id):
    user = User.query.get_or_404(user_id)
    user.section_id = None
    user.unit_id = None  # Also remove from unit
    db.session.commit()
    
    flash(f'User {user.full_name} removed from section!', 'success')
    return redirect(url_for('admin.edit_section', section_id=section_id))

@bp.route('/sections/<int:section_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_section(section_id):
    section = Section.query.get_or_404(section_id)
    
    # Check if section has users or units
    if section.users.count() > 0:
        flash(f'Cannot delete section "{section.name}" - it has {section.users.count()} users assigned.', 'danger')
        return redirect(url_for('admin.manage_sections'))
    
    if section.units.count() > 0:
        flash(f'Cannot delete section "{section.name}" - it has {section.units.count()} units.', 'danger')
        return redirect(url_for('admin.manage_sections'))
    
    try:
        section_name = section.name
        db.session.delete(section)
        db.session.commit()
        flash(f'Section "{section_name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting section: {str(e)}', 'danger')
    
    return redirect(url_for('admin.manage_sections'))

# ==================== UNIT MANAGEMENT ====================

@bp.route('/units')
@login_required
@admin_required
def manage_units():
    units = Unit.query.all()
    sections = Section.query.all()
    return render_template('admin/units.html', units=units, sections=sections)

@bp.route('/units/create', methods=['POST'])
@login_required
@admin_required
def create_unit():
    try:
        unit = Unit(
            name=request.form['name'],
            description=request.form.get('description', ''),
            section_id=request.form['section_id']
        )
        db.session.add(unit)
        db.session.commit()
        
        flash(f'Unit "{unit.name}" created successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating unit: {str(e)}', 'danger')
    
    return redirect(url_for('admin.manage_units'))

@bp.route('/units/<int:unit_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_unit(unit_id):
    unit = Unit.query.get_or_404(unit_id)
    
    if request.method == 'GET':
        sections = Section.query.all()
        # Get users in this unit and users in the same section but not in any unit
        unit_users = User.query.filter_by(unit_id=unit_id).all()
        section_users_no_unit = User.query.filter_by(section_id=unit.section_id, unit_id=None).all()
        
        return render_template('admin/edit_unit.html', 
                             unit=unit, 
                             sections=sections,
                             unit_users=unit_users,
                             section_users_no_unit=section_users_no_unit)
    
    try:
        unit.name = request.form['name']
        unit.description = request.form.get('description', '')
        unit.section_id = request.form['section_id']
        db.session.commit()
        
        flash(f'Unit "{unit.name}" updated successfully!', 'success')
        return redirect(url_for('admin.manage_units'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating unit: {str(e)}', 'danger')
        return redirect(url_for('admin.edit_unit', unit_id=unit_id))

@bp.route('/units/<int:unit_id>/add-user', methods=['POST'])
@login_required
@admin_required
def add_user_to_unit(unit_id):
    unit = Unit.query.get_or_404(unit_id)
    user_id = request.form.get('user_id')
    
    if user_id:
        user = User.query.get(user_id)
        if user:
            # Ensure user is in the same section as the unit
            if user.section_id != unit.section_id:
                user.section_id = unit.section_id
            user.unit_id = unit_id
            db.session.commit()
            flash(f'User {user.full_name} added to unit {unit.name}!', 'success')
        else:
            flash('User not found.', 'danger')
    else:
        flash('Please select a user.', 'warning')
    
    return redirect(url_for('admin.edit_unit', unit_id=unit_id))

@bp.route('/units/<int:unit_id>/remove-user/<int:user_id>')
@login_required
@admin_required
def remove_user_from_unit(unit_id, user_id):
    user = User.query.get_or_404(user_id)
    user.unit_id = None
    db.session.commit()
    
    flash(f'User {user.full_name} removed from unit!', 'success')
    return redirect(url_for('admin.edit_unit', unit_id=unit_id))

@bp.route('/units/<int:unit_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_unit(unit_id):
    unit = Unit.query.get_or_404(unit_id)
    
    # Check if unit has users
    if unit.users.count() > 0:
        flash(f'Cannot delete unit "{unit.name}" - it has {unit.users.count()} users assigned.', 'danger')
        return redirect(url_for('admin.manage_units'))
    
    try:
        unit_name = unit.name
        db.session.delete(unit)
        db.session.commit()
        flash(f'Unit "{unit_name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting unit: {str(e)}', 'danger')
    
    return redirect(url_for('admin.manage_units'))

# ==================== SETTINGS ROUTES ====================

@bp.route('/settings/email')
@login_required
@admin_required
def email_settings():
    """Email configuration settings"""
    return render_template('admin/email_settings.html')

@bp.route('/settings/email', methods=['POST'])
@login_required
@admin_required
def update_email_settings():
    """Update email configuration"""
    flash('Email settings updated successfully!', 'success')
    return redirect(url_for('admin.email_settings'))

@bp.route('/settings/2fa')
@login_required
@admin_required
def two_factor_settings():
    """Two-factor authentication settings"""
    return render_template('admin/2fa_settings.html')

@bp.route('/settings/2fa', methods=['POST'])
@login_required
@admin_required
def update_2fa_settings():
    """Update 2FA settings"""
    flash('2FA settings updated successfully!', 'success')
    return redirect(url_for('admin.two_factor_settings'))

@bp.route('/reports/usage')
@login_required
@admin_required
def usage_reports():
    """System usage reports"""
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    total_sections = Section.query.count()
    total_units = Unit.query.count()
    
    stats = {
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': total_users - active_users,
        'total_sections': total_sections,
        'total_units': total_units,
        'users_per_section': round(total_users / max(total_sections, 1), 2),
        'users_per_unit': round(total_users / max(total_units, 1), 2)
    }
    
    return render_template('admin/usage_reports.html', stats=stats)

@bp.route('/export/data')
@login_required
@admin_required
def export_data():
    """Export system data"""
    flash('Data export feature coming soon!', 'info')
    return redirect(url_for('admin.admin_dashboard'))