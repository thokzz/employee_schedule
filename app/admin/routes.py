from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.admin import bp
from app.models import AppSettings, User, Section, Unit, UserRole, db, EmailSettings, EmployeeType, ScheduleFormat

# NEW IMPORTS for 4-level hierarchy
try:
    from app.models import Department, Division
except ImportError:
    # Fallback if not migrated yet
    Department = None
    Division = None

# At the top of your app/admin/routes.py, replace the import line with:
try:
    from app.utils.email_debug import EmailDebug
except ImportError:
    # Create a placeholder EmailDebug class
    class EmailDebug:
        @staticmethod
        def check_email_configuration():
            return {'status': 'ERROR', 'issues': ['Email debug not available'], 'warnings': []}
        
        @staticmethod
        def test_smtp_connection():
            return {'success': False, 'message': 'Email debug not available'}
        
        @staticmethod
        def get_email_statistics():
            return {'error': 'Email debug not available'}
        
        @staticmethod
        def send_debug_test_email(to_email):
            return {'success': False, 'message': 'Email debug not available'}
        
        @staticmethod
        def debug_leave_notification(leave_id):
            return {'success': False, 'message': 'Email debug not available'}

from functools import wraps
from datetime import datetime, date
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.can_admin():
            flash('Administrator access required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.can_edit_schedule():  # Managers and Admins can edit schedule
            flash('Manager or Administrator access required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/')
@login_required
@admin_required
def admin_dashboard():
    # UPDATED: Include 4-level hierarchy stats
    stats = {
        'total_users': User.query.count(),
        'active_users': User.query.filter_by(is_active=True).count(),
        'total_sections': Section.query.count(),
        'total_units': Unit.query.count()
    }
    
    # Add 4-level hierarchy stats if tables exist
    if Department is not None:
        stats['total_departments'] = Department.query.count()
    else:
        stats['total_departments'] = 0
        
    if Division is not None:
        stats['total_divisions'] = Division.query.count()
    else:
        stats['total_divisions'] = 0
    
    return render_template('admin/dashboard.html', stats=stats)

# ==================== DEPARTMENT MANAGEMENT (NEW) ====================

@bp.route('/departments')
@login_required
@admin_required
def manage_departments():
    if Department is None:
        flash('4-level hierarchy not available. Please run migration first.', 'warning')
        return redirect(url_for('admin.admin_dashboard'))
    
    departments = Department.query.all()
    return render_template('admin/departments.html', departments=departments)

@bp.route('/departments/create', methods=['POST'])
@login_required
@admin_required
def create_department():
    if Department is None:
        flash('4-level hierarchy not available. Please run migration first.', 'warning')
        return redirect(url_for('admin.admin_dashboard'))
    
    try:
        department = Department(
            name=request.form['name'],
            description=request.form.get('description', '')
        )
        db.session.add(department)
        db.session.commit()
        
        flash(f'Department "{department.name}" created successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating department: {str(e)}', 'danger')
    
    return redirect(url_for('admin.manage_departments'))

@bp.route('/departments/<int:department_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_department(department_id):
    """Edit a department"""
    department = Department.query.get_or_404(department_id)
    
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            
            if not name:
                flash('Department name is required.', 'error')
                return render_template('admin/edit_department.html', department=department)
            
            # Check if name is taken by another department
            existing = Department.query.filter(
                Department.name == name,
                Department.id != department_id
            ).first()
            
            if existing:
                flash(f'Department name "{name}" is already taken.', 'error')
                return render_template('admin/edit_department.html', department=department)
            
            # Update department
            department.name = name
            department.description = description if description else None
            
            db.session.commit()
            flash(f'Department "{name}" updated successfully.', 'success')
            return redirect(url_for('admin.manage_departments'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating department: {str(e)}', 'error')
    
    # GET request - get additional data for the template
    dept_users = User.query.filter_by(department_id=department_id).all() if hasattr(User, 'department_id') else []
    unassigned_users = User.query.filter_by(department_id=None).all() if hasattr(User, 'department_id') else []
    other_users = User.query.filter(User.department_id != department_id, User.department_id != None).all() if hasattr(User, 'department_id') else []
    
    return render_template('admin/edit_department.html', 
                         department=department,
                         dept_users=dept_users,
                         unassigned_users=unassigned_users,
                         other_users=other_users)

@bp.route('/departments/<int:department_id>/add-user', methods=['POST'])
@login_required
@admin_required
def add_user_to_department(department_id):
    if Department is None:
        flash('4-level hierarchy not available.', 'warning')
        return redirect(url_for('admin.admin_dashboard'))
    
    department = Department.query.get_or_404(department_id)
    user_id = request.form.get('user_id')
    
    if user_id:
        user = User.query.get(user_id)
        if user:
            user.department_id = department_id
            # Reset lower level assignments when moving between departments
            if hasattr(user, 'division_id') and user.division_id and hasattr(user, 'division'):
                if user.division and user.division.department_id != department_id:
                    user.division_id = None
                    user.section_id = None
                    user.unit_id = None
            db.session.commit()
            flash(f'User {user.full_name} added to department {department.name}!', 'success')
        else:
            flash('User not found.', 'danger')
    else:
        flash('Please select a user.', 'warning')
    
    return redirect(url_for('admin.edit_department', department_id=department_id))

@bp.route('/departments/<int:department_id>/remove-user/<int:user_id>')
@login_required
@admin_required
def remove_user_from_department(department_id, user_id):
    user = User.query.get_or_404(user_id)
    department = Department.query.get_or_404(department_id)
    
    user_name = user.full_name
    department_name = department.name
    
    # Remove from all levels
    user.department_id = None
    if hasattr(user, 'division_id'):
        user.division_id = None
    user.section_id = None
    user.unit_id = None
    
    # Reset all approver status
    if hasattr(user, 'is_department_approver'):
        user.is_department_approver = False
    if hasattr(user, 'is_division_approver'):
        user.is_division_approver = False
    user.is_section_approver = False
    user.is_unit_approver = False
    
    db.session.commit()
    
    flash(f'User {user_name} removed from department {department_name} and all approver status reset.', 'success')
    return redirect(url_for('admin.edit_department', department_id=department_id))

@bp.route('/departments/<int:department_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_department(department_id):
    """Delete a department"""
    try:
        department = Department.query.get_or_404(department_id)
        
        # Check if department has users
        user_count = department.users.count()
        if user_count > 0:
            flash(f'Cannot delete department "{department.name}". It has {user_count} users assigned.', 'error')
            return redirect(url_for('admin.manage_departments'))
        
        # Check if department has divisions
        division_count = department.divisions.count()
        if division_count > 0:
            flash(f'Cannot delete department "{department.name}". It has {division_count} divisions.', 'error')
            return redirect(url_for('admin.manage_departments'))
        
        name = department.name
        db.session.delete(department)
        db.session.commit()
        
        flash(f'Department "{name}" deleted successfully.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting department: {str(e)}', 'error')
    
    return redirect(url_for('admin.manage_departments'))

# ==================== DIVISION MANAGEMENT (NEW) ====================

@bp.route('/divisions')
@login_required
@admin_required
def manage_divisions():
    if Division is None or Department is None:
        flash('4-level hierarchy not available. Please run migration first.', 'warning')
        return redirect(url_for('admin.admin_dashboard'))
    
    divisions = Division.query.all()
    departments = Department.query.all()
    return render_template('admin/divisions.html', divisions=divisions, departments=departments)

@bp.route('/divisions/create', methods=['POST'])
@login_required
@admin_required
def create_division():
    """Create a new division"""
    try:
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        department_id = request.form.get('department_id')
        
        if not name:
            flash('Division name is required.', 'error')
            return redirect(url_for('admin.manage_divisions'))
        
        if not department_id:
            flash('Department selection is required.', 'error')
            return redirect(url_for('admin.manage_divisions'))
        
        # Verify department exists
        department = Department.query.get(department_id)
        if not department:
            flash('Selected department does not exist.', 'error')
            return redirect(url_for('admin.manage_divisions'))
        
        # Check if division already exists in this department
        existing = Division.query.filter_by(
            name=name, 
            department_id=department_id
        ).first()
        
        if existing:
            flash(f'Division "{name}" already exists in department "{department.name}".', 'error')
            return redirect(url_for('admin.manage_divisions'))
        
        # Create new division
        division = Division(
            name=name,
            description=description if description else None,
            department_id=department_id
        )
        
        db.session.add(division)
        db.session.commit()
        
        flash(f'Division "{name}" created successfully in "{department.name}".', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating division: {str(e)}', 'error')
    
    return redirect(url_for('admin.manage_divisions'))

@bp.route('/divisions/<int:division_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_division(division_id):
    """Edit a division"""
    division = Division.query.get_or_404(division_id)
    departments = Department.query.order_by(Department.name).all()
    
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            department_id = request.form.get('department_id')
            
            if not name:
                flash('Division name is required.', 'error')
                return render_template('admin/edit_division.html', 
                                     division=division, departments=departments)
            
            if not department_id:
                flash('Department selection is required.', 'error')
                return render_template('admin/edit_division.html', 
                                     division=division, departments=departments)
            
            # Check if name is taken by another division in the same department
            existing = Division.query.filter(
                Division.name == name,
                Division.department_id == department_id,
                Division.id != division_id
            ).first()
            
            if existing:
                department = Department.query.get(department_id)
                flash(f'Division name "{name}" is already taken in department "{department.name}".', 'error')
                return render_template('admin/edit_division.html', 
                                     division=division, departments=departments)
            
            # Update division
            division.name = name
            division.description = description if description else None
            division.department_id = department_id
            
            db.session.commit()
            flash(f'Division "{name}" updated successfully.', 'success')
            return redirect(url_for('admin.manage_divisions'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating division: {str(e)}', 'error')
    
    # GET request - get additional data for the template
    division_users = User.query.filter_by(division_id=division_id).all() if hasattr(User, 'division_id') else []
    dept_users_no_division = User.query.filter_by(department_id=division.department_id, division_id=None).all() if hasattr(User, 'division_id') else []
    
    return render_template('admin/edit_division.html', 
                         division=division, 
                         departments=departments,
                         division_users=division_users,
                         dept_users_no_division=dept_users_no_division)

@bp.route('/divisions/<int:division_id>/add-user', methods=['POST'])
@login_required
@admin_required
def add_user_to_division(division_id):
    division = Division.query.get_or_404(division_id)
    user_id = request.form.get('user_id')
    
    if user_id:
        user = User.query.get(user_id)
        if user:
            # Ensure user is in the same department as the division
            if hasattr(user, 'department_id') and user.department_id != division.department_id:
                user.department_id = division.department_id
            user.division_id = division_id
            # Reset lower level if moving between divisions
            if user.section and hasattr(user.section, 'division_id') and user.section.division_id != division_id:
                user.section_id = None
                user.unit_id = None
            db.session.commit()
            flash(f'User {user.full_name} added to division {division.name}!', 'success')
        else:
            flash('User not found.', 'danger')
    else:
        flash('Please select a user.', 'warning')
    
    return redirect(url_for('admin.edit_division', division_id=division_id))

@bp.route('/divisions/<int:division_id>/remove-user/<int:user_id>')
@login_required
@admin_required
def remove_user_from_division(division_id, user_id):
    user = User.query.get_or_404(user_id)
    division = Division.query.get_or_404(division_id)
    
    user_name = user.full_name
    division_name = division.name
    
    # Remove from division and lower levels
    user.division_id = None
    user.section_id = None
    user.unit_id = None
    
    # Reset division-level approver status
    if hasattr(user, 'is_division_approver'):
        user.is_division_approver = False
    user.is_section_approver = False
    user.is_unit_approver = False
    
    db.session.commit()
    
    flash(f'User {user_name} removed from division {division_name} and relevant approver status reset.', 'success')
    return redirect(url_for('admin.edit_division', division_id=division_id))

@bp.route('/divisions/<int:division_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_division(division_id):
    """Delete a division"""
    try:
        division = Division.query.get_or_404(division_id)
        
        # Check if division has users
        user_count = division.users.count()
        if user_count > 0:
            flash(f'Cannot delete division "{division.name}". It has {user_count} users assigned.', 'error')
            return redirect(url_for('admin.manage_divisions'))
        
        # Check if division has sections
        section_count = division.sections.count()
        if section_count > 0:
            flash(f'Cannot delete division "{division.name}". It has {section_count} sections.', 'error')
            return redirect(url_for('admin.manage_divisions'))
        
        name = division.name
        db.session.delete(division)
        db.session.commit()
        
        flash(f'Division "{name}" deleted successfully.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting division: {str(e)}', 'error')
    
    return redirect(url_for('admin.manage_divisions'))

# API Routes for AJAX filtering
@bp.route('/api/divisions/by-department/<int:department_id>')
@login_required
def get_divisions_by_department(department_id):
    """Get divisions for a specific department (AJAX endpoint)"""
    try:
        divisions = Division.query.filter_by(department_id=department_id).order_by(Division.name).all()
        return jsonify([{
            'id': div.id,
            'name': div.name,
            'description': div.description
        } for div in divisions])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/api/sections/by-division/<int:division_id>')
@login_required
def get_sections_by_division(division_id):
    """Get sections for a specific division (AJAX endpoint)"""
    try:
        sections = Section.query.filter_by(division_id=division_id).order_by(Section.name).all()
        return jsonify([{
            'id': sect.id,
            'name': sect.name,
            'description': sect.description
        } for sect in sections])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/api/units/by-section/<int:section_id>')
@login_required
def get_units_by_section(section_id):
    """Get units for a specific section (AJAX endpoint)"""
    try:
        units = Unit.query.filter_by(section_id=section_id).order_by(Unit.name).all()
        return jsonify([{
            'id': unit.id,
            'name': unit.name,
            'description': unit.description
        } for unit in units])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== USER MANAGEMENT ====================

@bp.route('/users')
@login_required
@admin_required
def manage_users():
    users = User.query.all()
    sections = Section.query.all()
    units = Unit.query.all()
    
    # Add 4-level hierarchy if available
    departments = Department.query.all() if Department else []
    divisions = Division.query.all() if Division else []
    
    return render_template('admin/users.html', 
                         users=users, 
                         sections=sections, 
                         units=units,
                         departments=departments,
                         divisions=divisions)

@bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    """Create a new user with 4-level hierarchy support"""
    if request.method == 'POST':
        try:
            # Get basic user info
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '').strip()
            role = request.form.get('role', 'employee')
            
            # Validate required fields
            if not all([first_name, last_name, username, email, password]):
                flash('All required fields must be filled.', 'error')
                return redirect(url_for('admin.create_user'))
            
            # Check if username or email already exists
            existing_user = User.query.filter(
                (User.username == username) | (User.email == email)
            ).first()
            
            if existing_user:
                flash('Username or email already exists.', 'error')
                return redirect(url_for('admin.create_user'))
            
            # Get 4-level hierarchy assignments
            department_id = request.form.get('department_id') or None
            division_id = request.form.get('division_id') or None
            section_id = request.form.get('section_id') or None
            unit_id = request.form.get('unit_id') or None
            
            # Get approver permissions
            is_department_approver = 'is_department_approver' in request.form
            is_division_approver = 'is_division_approver' in request.form
            is_section_approver = 'is_section_approver' in request.form
            is_unit_approver = 'is_unit_approver' in request.form
            
            # Validate approver permissions against assignments
            validation_errors = []
            if is_department_approver and not department_id:
                validation_errors.append('Department approver requires department assignment')
            if is_division_approver and not division_id:
                validation_errors.append('Division approver requires division assignment')
            if is_section_approver and not section_id:
                validation_errors.append('Section approver requires section assignment')
            if is_unit_approver and not unit_id:
                validation_errors.append('Unit approver requires unit assignment')
            
            if validation_errors:
                for error in validation_errors:
                    flash(error, 'error')
                return redirect(url_for('admin.create_user'))
            
            # Create user with all fields
            user = User(
                first_name=first_name,
                last_name=last_name,
                username=username,
                email=email,
                role=UserRole(role),
                section_id=section_id,
                unit_id=unit_id,
                is_section_approver=is_section_approver,
                is_unit_approver=is_unit_approver
            )
            
            # Add 4-level hierarchy fields if available
            if hasattr(user, 'department_id'):
                user.department_id = department_id
            if hasattr(user, 'division_id'):
                user.division_id = division_id
            if hasattr(user, 'is_department_approver'):
                user.is_department_approver = is_department_approver
            if hasattr(user, 'is_division_approver'):
                user.is_division_approver = is_division_approver
            
            # Set password
            user.set_password(password)
            
            # Add employment info
            user.personnel_number = request.form.get('personnel_number') or None
            user.div_department = request.form.get('div_department') or None
            user.id_number = request.form.get('id_number') or None
            user.job_title = request.form.get('job_title') or None
            user.rank = request.form.get('rank') or None
            user.contact_number = request.form.get('contact_number') or None
            
            # Handle employee type enum
            employee_type_value = request.form.get('employee_type')
            if employee_type_value:
                try:
                    user.employee_type = EmployeeType(employee_type_value)
                except ValueError:
                    user.employee_type = None
            
            # Handle schedule format enum
            schedule_format_value = request.form.get('schedule_format')
            if schedule_format_value:
                try:
                    user.schedule_format = ScheduleFormat(schedule_format_value)
                except ValueError:
                    user.schedule_format = None
            
            # Handle hiring date
            hiring_date_str = request.form.get('hiring_date')
            if hiring_date_str:
                user.hiring_date = datetime.strptime(hiring_date_str, '%Y-%m-%d').date()
            
            db.session.add(user)
            db.session.commit()
            
            flash(f'User {user.username} created successfully!', 'success')
            return redirect(url_for('admin.manage_users'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating user: {str(e)}', 'error')
            return redirect(url_for('admin.create_user'))
    
    # GET request - get data for form dropdowns
    departments = Department.query.order_by(Department.name).all() if Department else []
    divisions = Division.query.join(Department).order_by(Department.name, Division.name).all() if Division else []
    sections = Section.query.order_by(Section.name).all()
    units = Unit.query.join(Section).order_by(Section.name, Unit.name).all()
    
    return render_template('admin/create_user.html',
                         departments=departments,
                         divisions=divisions,
                         sections=sections,
                         units=units)

@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if request.method == 'GET':
        sections = Section.query.all()
        units = Unit.query.all()
        departments = Department.query.all() if Department else []
        divisions = Division.query.all() if Division else []
        
        return render_template('admin/edit_user.html', 
                             user=user, 
                             sections=sections, 
                             units=units,
                             departments=departments,
                             divisions=divisions)
    
    try:
        user.first_name = request.form['first_name']
        user.last_name = request.form['last_name']
        user.email = request.form['email']
        user.role = UserRole(request.form['role'])
        user.section_id = request.form.get('section_id') or None
        user.unit_id = request.form.get('unit_id') or None
        
        # Add 4-level hierarchy fields if available
        if Department and hasattr(user, 'department_id'):
            user.department_id = request.form.get('department_id') or None
        if Division and hasattr(user, 'division_id'):
            user.division_id = request.form.get('division_id') or None
        
        # Employment fields
        user.personnel_number = request.form.get('personnel_number') or None
        user.div_department = request.form.get('div_department') or None
        user.typecode = request.form.get('typecode') or None
        user.id_number = request.form.get('id_number') or None
        user.job_title = request.form.get('job_title') or None
        user.rank = request.form.get('rank') or None
        user.contact_number = request.form.get('contact_number') or None
        
        # Approver fields
        user.is_section_approver = bool(request.form.get('is_section_approver'))
        user.is_unit_approver = bool(request.form.get('is_unit_approver'))
        
        # Add 4-level approver fields if available
        if hasattr(user, 'is_department_approver'):
            user.is_department_approver = bool(request.form.get('is_department_approver'))
        if hasattr(user, 'is_division_approver'):
            user.is_division_approver = bool(request.form.get('is_division_approver'))
        
        # Handle employee type enum
        employee_type_value = request.form.get('employee_type')
        if employee_type_value:
            try:
                user.employee_type = EmployeeType(employee_type_value)
            except ValueError:
                user.employee_type = None
        else:
            user.employee_type = None
        
        # Handle schedule format enum
        schedule_format_value = request.form.get('schedule_format')
        if schedule_format_value:
            try:
                user.schedule_format = ScheduleFormat(schedule_format_value)
            except ValueError:
                user.schedule_format = None
        else:
            user.schedule_format = None
        
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
        current_app.logger.error(f"User update error: {str(e)}")
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
        
        # Clean up uploaded files - UPDATED PATHS
        import os
        if user.avatar and user.avatar != 'default_avatar.png':
            try:
                # Use static/uploads instead of instance_path
                avatar_path = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars', user.avatar)
                if os.path.exists(avatar_path):
                    os.remove(avatar_path)
            except:
                pass
        
        if user.signature:
            try:
                # Use static/uploads instead of instance_path
                signature_path = os.path.join(current_app.root_path, 'static', 'uploads', 'signatures', user.signature)
                if os.path.exists(signature_path):
                    os.remove(signature_path)
            except:
                pass
        
        db.session.delete(user)
        db.session.commit()
        flash(f'User {username} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'danger')
        current_app.logger.error(f"User deletion error: {str(e)}")
    
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
    """Remove user from section and reset approver status"""
    user = User.query.get_or_404(user_id)
    section = Section.query.get_or_404(section_id)
    
    # Store original info for flash message
    user_name = user.full_name
    section_name = section.name
    
    # Remove from section and unit
    user.section_id = None
    user.unit_id = None
    
    # Reset approver status when removing from section
    user.is_section_approver = False
    user.is_unit_approver = False
    
    db.session.commit()
    
    flash(f'User {user_name} removed from section {section_name} and approver status reset.', 'success')
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
    """Remove user from unit and reset unit approver status"""
    user = User.query.get_or_404(user_id)
    unit = Unit.query.get_or_404(unit_id)
    
    # Store original info for flash message
    user_name = user.full_name
    unit_name = unit.name
    
    # Remove from unit only (keep section assignment)
    user.unit_id = None
    
    # Reset unit approver status when removing from unit
    user.is_unit_approver = False
    # Keep is_section_approver since they're still in the section
    
    db.session.commit()
    
    flash(f'User {user_name} removed from unit {unit_name} and unit approver status reset.', 'success')
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
    settings = EmailSettings.get_settings()
    return render_template('admin/email_settings.html', settings=settings)

@bp.route('/settings/email', methods=['POST'])
@login_required
@admin_required
def update_email_settings():
    """Update email configuration"""
    try:
        settings = EmailSettings.get_settings()
        
        # Update basic SMTP settings
        settings.mail_server = request.form.get('mail_server', '').strip() or None
        settings.mail_port = int(request.form.get('mail_port', 587))
        settings.mail_use_tls = request.form.get('mail_use_tls', 'false').lower() == 'true'
        settings.mail_username = request.form.get('mail_username', '').strip() or None
        settings.mail_default_sender = request.form.get('mail_default_sender', '').strip() or None
        
        # Only update password if provided
        if request.form.get('mail_password'):
            settings.mail_password = request.form.get('mail_password')
        
        # Update notification settings
        settings.notify_schedule_changes = 'notify_schedule_changes' in request.form
        settings.notify_new_users = 'notify_new_users' in request.form
        settings.notify_leave_requests = 'notify_leave_requests' in request.form
        
        db.session.commit()
        flash('Email settings updated successfully!', 'success')
        
    except ValueError as e:
        flash('Invalid port number. Please enter a valid number.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating email settings: {str(e)}', 'danger')
    
    return redirect(url_for('admin.email_settings'))

@bp.route('/settings/email/test', methods=['POST'])
@login_required
@admin_required
def test_email_settings():
    """Test email configuration by sending a test email"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False, 
                'message': 'No data received. Please try again.'
            })
        
        # Get settings from form data
        mail_server = data.get('mail_server', '').strip()
        mail_port = data.get('mail_port')
        mail_use_tls = data.get('mail_use_tls', True)
        mail_username = data.get('mail_username', '').strip()
        mail_password = data.get('mail_password', '').strip()
        mail_default_sender = data.get('mail_default_sender', '').strip()
        test_email_recipient = data.get('test_email_recipient', '').strip()
        
        # If no password provided, try to get from saved settings
        if not mail_password:
            settings = EmailSettings.get_settings()
            if settings.mail_password:
                mail_password = settings.mail_password
            else:
                return jsonify({
                    'success': False, 
                    'message': 'Password is required. Please enter your SMTP password or save settings first.'
                })
        
        # Validate required fields
        missing_fields = []
        if not mail_server:
            missing_fields.append('Mail Server')
        if not mail_username:
            missing_fields.append('Username')
        if not mail_port:
            missing_fields.append('Port')
        if not mail_password:
            missing_fields.append('Password')
        if not test_email_recipient:
            missing_fields.append('Test Email Recipient')
            
        if missing_fields:
            return jsonify({
                'success': False, 
                'message': f'Missing required fields: {", ".join(missing_fields)}'
            })
        
        # Validate port number
        try:
            mail_port = int(mail_port)
            if mail_port < 1 or mail_port > 65535:
                raise ValueError("Port out of range")
        except (ValueError, TypeError):
            return jsonify({
                'success': False, 
                'message': 'Invalid port number. Please enter a valid port (1-65535).'
            })
        
        # Validate email format for test recipient
        # Validate email format for test recipient
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, test_email_recipient):
            return jsonify({
                'success': False, 
                'message': 'Invalid email format for test recipient.'
            })
        
        # Create test email
        sender_email = mail_default_sender or mail_username
        
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = test_email_recipient
        msg['Subject'] = 'Employee Scheduling System - Test Email'
        
        body = f"""
This is a test email from the Employee Scheduling System.

If you received this email, your SMTP configuration is working correctly!

Configuration tested:
- SMTP Server: {mail_server}
- Port: {mail_port}
- TLS: {'Enabled' if mail_use_tls else 'Disabled'}
- Username: {mail_username}
- Sender: {sender_email}
- Test sent to: {test_email_recipient}

Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Best regards,
Employee Scheduling System
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Connect to server and send email
        try:
            if mail_use_tls:
                server = smtplib.SMTP(mail_server, mail_port)
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP(mail_server, mail_port)
                server.ehlo()
            
            server.login(mail_username, mail_password)
            
            text = msg.as_string()
            server.sendmail(sender_email, test_email_recipient, text)
            server.quit()
            
            return jsonify({
                'success': True, 
                'message': f'Test email sent successfully to {test_email_recipient}!'
            })
            
        except smtplib.SMTPAuthenticationError as e:
            return jsonify({
                'success': False, 
                'message': 'Authentication failed. Please check your username and password. For Gmail, use an App Password instead of your regular password.'
            })
        except smtplib.SMTPConnectError as e:
            return jsonify({
                'success': False, 
                'message': f'Could not connect to SMTP server {mail_server}:{mail_port}. Please check server address and port.'
            })
        except smtplib.SMTPRecipientsRefused as e:
            return jsonify({
                'success': False, 
                'message': f'Recipient email address was refused: {test_email_recipient}'
            })
        except smtplib.SMTPSenderRefused as e:
            return jsonify({
                'success': False, 
                'message': f'Sender email address was refused: {sender_email}'
            })
        except Exception as e:
            return jsonify({
                'success': False, 
                'message': f'Connection error: {str(e)}. Please check your server settings.'
            })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Error testing email settings: {str(e)}'
        })



@bp.route('/employees/export')
@login_required
def export_employee_database():
    """Export employee database as CSV"""
    # Check permissions
    if not (current_user.can_approve_leaves() or current_user.can_edit_schedule()):
        flash('Access denied. You need approver or manager privileges.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    import io
    import csv
    from flask import make_response
    from datetime import date
    
    # Get employees based on access level
    if current_user.can_admin():
        employees = User.query.filter_by(is_active=True).order_by(User.last_name, User.first_name).all()
        filename_prefix = "all_employees"
    else:
        approvable_employees = current_user.get_approvable_employees()
        employee_ids = [emp.id for emp in approvable_employees]
        employees = User.query.filter(User.id.in_(employee_ids), User.is_active == True)\
                              .order_by(User.last_name, User.first_name).all()
        
        if current_user.section:
            filename_prefix = f"{current_user.section.name}_employees"
        elif current_user.unit:
            filename_prefix = f"{current_user.unit.name}_employees"
        else:
            filename_prefix = "team_employees"
    
    # Create CSV output
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'Last Name', 'First Name', 'Date Hired', 'Section', 'Unit', 
        'Job Title', 'Rank', 'Employee Type', 'ID Number', 'Years of Service',
        'Contact Number', 'Email Address', 'Personnel Number', 'Division/Department'
    ])
    
    # Write employee data
    for emp in employees:
        # Calculate years of service
        years_service = emp.years_of_service if emp.years_of_service is not None else 'N/A'
        
        writer.writerow([
            emp.last_name,
            emp.first_name,
            emp.hiring_date.strftime('%Y-%m-%d') if emp.hiring_date else '',
            emp.section.name if emp.section else '',
            emp.unit.name if emp.unit else '',
            emp.job_title or '',
            emp.rank or '',
            emp.employee_type.value.replace('_', ' ').title() if emp.employee_type else '',
            emp.id_number or '',
            years_service,
            emp.contact_number or '',
            emp.email,
            emp.personnel_number or '',
            emp.div_department or ''
        ])
    
    # Create response
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename={filename_prefix}_{date.today().strftime("%Y%m%d")}.csv'
    
    return response

@bp.route('/employees/import', methods=['GET', 'POST'])
@login_required
@admin_required
def import_employee_database():
    """Import employee database from CSV - Admin only"""
    if request.method == 'GET':
        sections = Section.query.all()
        units = Unit.query.all()
        departments = Department.query.all() if Department else []
        divisions = Division.query.all() if Division else []
        
        return render_template('admin/import_employees.html', 
                             sections=sections, 
                             units=units,
                             departments=departments,
                             divisions=divisions)
    
    # POST request - handle file upload
    print("DEBUG: POST request received")
    print("DEBUG: request.files keys:", list(request.files.keys()))
    print("DEBUG: request.form keys:", list(request.form.keys()))
    
    try:
        # Check if file was uploaded
        if 'csv_file' not in request.files:
            print("DEBUG: 'csv_file' not found in request.files")
            flash('No file selected. Please choose a CSV file.', 'danger')
            return redirect(url_for('admin.import_employee_database'))
        
        file = request.files['csv_file']
        print("DEBUG: file object:", file)
        print("DEBUG: file.filename:", repr(file.filename))
        print("DEBUG: file.content_type:", getattr(file, 'content_type', 'No content_type'))
        
        if not file or file.filename == '' or file.filename is None:
            print("DEBUG: File is empty or filename is empty")
            flash('No file selected. Please choose a CSV file.', 'danger')
            return redirect(url_for('admin.import_employee_database'))
        
        if not file.filename.lower().endswith('.csv'):
            print("DEBUG: File is not CSV:", file.filename)
            flash('Invalid file type. Please upload a CSV file.', 'danger')
            return redirect(url_for('admin.import_employee_database'))
        
        print("DEBUG: File validation passed, proceeding with import...")
        
        # Read and process CSV
        import csv
        import io
        from datetime import datetime
        
        # Read file content
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_reader = csv.DictReader(stream)
        
        # Track import results
        imported_count = 0
        updated_count = 0
        error_count = 0
        errors = []
        
        # Get sections and units for lookup
        sections_dict = {s.name: s.id for s in Section.query.all()}
        units_dict = {u.name: u.id for u in Unit.query.all()}
        departments_dict = {d.name: d.id for d in Department.query.all()} if Department else {}
        divisions_dict = {d.name: d.id for d in Division.query.all()} if Division else {}

        for row_num, row in enumerate(csv_reader, start=2):  # Start at 2 because row 1 is header
            try:
                # Required fields
                username = row.get('Username', '').strip()
                email = row.get('Email Address', '').strip()
                first_name = row.get('First Name', '').strip()
                last_name = row.get('Last Name', '').strip()
                
                if not all([username, email, first_name, last_name]):
                    errors.append(f"Row {row_num}: Missing required fields (Username, Email, First Name, Last Name)")
                    error_count += 1
                    continue
                
                # Check if user exists
                existing_user = User.query.filter_by(email=email).first()
                if not existing_user:
                    existing_user = User.query.filter_by(username=username).first()
                
                if existing_user:
                    # Update existing user
                    user = existing_user
                    updated_count += 1
                else:
                    # Create new user
                    user = User()
                    # Set default password for new users
                    user.set_password('password123')  # They should change this on first login
                    imported_count += 1
                
                # Update user fields
                user.username = username
                user.email = email
                user.first_name = first_name
                user.last_name = last_name
                
                # Optional fields
                user.personnel_number = row.get('Personnel Number', '').strip() or None
                user.div_department = row.get('Division/Department', '').strip() or None
                user.id_number = row.get('ID Number', '').strip() or None
                user.job_title = row.get('Job Title', '').strip() or None
                user.rank = row.get('Rank', '').strip() or None
                user.contact_number = row.get('Contact Number', '').strip() or None
                
                department_name = row.get('Department', '').strip()
                if department_name and department_name in departments_dict:
                    if hasattr(user, 'department_id'):
                        user.department_id = departments_dict[department_name]
                elif department_name:
                    errors.append(f"Row {row_num}: Department '{department_name}' not found")
                
                # Handle division
                division_name = row.get('Division', '').strip()
                if division_name and division_name in divisions_dict:
                    if hasattr(user, 'division_id'):
                        user.division_id = divisions_dict[division_name]
                elif division_name:
                    errors.append(f"Row {row_num}: Division '{division_name}' not found")

                
                # Handle section
                section_name = row.get('Section', '').strip()
                if section_name and section_name in sections_dict:
                    user.section_id = sections_dict[section_name]
                elif section_name:
                    errors.append(f"Row {row_num}: Section '{section_name}' not found")
                
                # Handle unit
                unit_name = row.get('Unit', '').strip()
                if unit_name and unit_name in units_dict:
                    user.unit_id = units_dict[unit_name]
                elif unit_name:
                    errors.append(f"Row {row_num}: Unit '{unit_name}' not found")
                
                # Handle employee type
                emp_type_str = row.get('Employee Type', '').strip()
                if emp_type_str:
                    try:
                        # Convert display name back to enum value
                        emp_type_value = emp_type_str.lower().replace(' ', '_')
                        user.employee_type = EmployeeType(emp_type_value)
                    except ValueError:
                        errors.append(f"Row {row_num}: Invalid employee type '{emp_type_str}'")
                
                # Handle hiring date
                date_hired_str = row.get('Date Hired', '').strip()
                if date_hired_str:
                    try:
                        user.hiring_date = datetime.strptime(date_hired_str, '%Y-%m-%d').date()
                    except ValueError:
                        try:
                            user.hiring_date = datetime.strptime(date_hired_str, '%m/%d/%Y').date()
                        except ValueError:
                            errors.append(f"Row {row_num}: Invalid date format '{date_hired_str}' (use YYYY-MM-DD or MM/DD/YYYY)")
                
                # Set default role if new user
                if not existing_user:
                    user.role = UserRole.EMPLOYEE
                
                db.session.add(user)
                
            except Exception as e:
                error_count += 1
                errors.append(f"Row {row_num}: {str(e)}")
        
        # Commit changes
        if imported_count > 0 or updated_count > 0:
            db.session.commit()
        
        # Show results
        if imported_count > 0:
            flash(f'Successfully imported {imported_count} new employees.', 'success')
        if updated_count > 0:
            flash(f'Successfully updated {updated_count} existing employees.', 'info')
        if error_count > 0:
            flash(f'{error_count} rows had errors. Check the error details below.', 'warning')
            for error in errors[:10]:  # Show first 10 errors
                flash(error, 'danger')
            if len(errors) > 10:
                flash(f'... and {len(errors) - 10} more errors.', 'warning')
        
        if imported_count == 0 and updated_count == 0 and error_count == 0:
            flash('No valid data found in the CSV file.', 'warning')
        
    except Exception as e:
        print("DEBUG: Exception occurred:", str(e))
        db.session.rollback()
        flash(f'Error processing CSV file: {str(e)}', 'danger')
        current_app.logger.error(f"CSV import error: {str(e)}")
    
    return redirect(url_for('admin.import_employee_database'))

@bp.route('/employees/template')
@login_required
@admin_required
def download_employee_template():
    """Download CSV template for employee import"""
    import io
    import csv
    from flask import make_response
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header with departments and divisions
    writer.writerow([
        'Username', 'Email Address', 'First Name', 'Last Name', 'Date Hired',
        'Department', 'Division', 'Section', 'Unit', 'Job Title', 'Rank', 
        'Employee Type', 'ID Number', 'Contact Number', 'Personnel Number', 
        'Division/Department'
    ])
    
    # Write sample data
    writer.writerow([
        'hgspecter', 'hgspecter@email.com', 'Harvey', 'Specter', '2023-01-15',
        'Post Production', 'TMSSD', 'IT Solutions and Data Center Operations', 'IT Infrastructure', 
        'IT Specialist', 'B2', 'confidential', '001D', 
        '+639101234567', '1289000', 'TMSSD/POST'
    ])
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=employee_import_template.csv'
    
    return response

@bp.route('/api/employees/filter')
@login_required
def filter_employees():
    """API endpoint for filtering employees"""
    # Check permissions
    if not (current_user.can_approve_leaves() or current_user.can_edit_schedule()):
        return jsonify({'error': 'Access denied'}), 403
    
    # Get filter parameters
    section_id = request.args.get('section_id', type=int)
    unit_id = request.args.get('unit_id', type=int)
    employee_type = request.args.get('employee_type')
    search_term = request.args.get('search', '').strip()
    
    # Start with base query based on user's access
    if current_user.can_admin():
        query = User.query.filter_by(is_active=True)
    else:
        approvable_employees = current_user.get_approvable_employees()
        employee_ids = [emp.id for emp in approvable_employees]
        query = User.query.filter(User.id.in_(employee_ids), User.is_active == True)
    
    # Apply filters
    if section_id:
        query = query.filter_by(section_id=section_id)
    
    if unit_id:
        query = query.filter_by(unit_id=unit_id)
    
    if employee_type:
        try:
            emp_type_enum = EmployeeType(employee_type)
            query = query.filter_by(employee_type=emp_type_enum)
        except ValueError:
            pass
    
    if search_term:
        # Build search filter with safe field access
        search_filters = [
            User.first_name.ilike(f'%{search_term}%'),
            User.last_name.ilike(f'%{search_term}%'),
            User.email.ilike(f'%{search_term}%'),
        ]
        
        # Add optional fields only if they exist
        if hasattr(User, 'job_title') and User.job_title is not None:
            search_filters.append(User.job_title.ilike(f'%{search_term}%'))
        if hasattr(User, 'personnel_number') and User.personnel_number is not None:
            search_filters.append(User.personnel_number.ilike(f'%{search_term}%'))
        if hasattr(User, 'id_number') and User.id_number is not None:
            search_filters.append(User.id_number.ilike(f'%{search_term}%'))
            
        search_filter = db.or_(*search_filters)
        query = query.filter(search_filter)
    
    # Order by last name, first name
    employees = query.order_by(User.last_name, User.first_name).all()
    
    # Convert to JSON
    employee_data = []
    for emp in employees:
        employee_data.append({
            'id': emp.id,
            'last_name': emp.last_name,
            'first_name': emp.first_name,
            'full_name': emp.full_name,
            'email': emp.email,
            'hiring_date': emp.hiring_date.strftime('%Y-%m-%d') if emp.hiring_date else '',
            'section': emp.section.name if emp.section else '',
            'unit': emp.unit.name if emp.unit else '',
            'job_title': emp.job_title or '',
            'rank': emp.rank or '',
            'employee_type': emp.employee_type.value.replace('_', ' ').title() if emp.employee_type else '',
            'id_number': emp.id_number or '',
            'years_of_service': emp.years_of_service if emp.years_of_service is not None else 'N/A',
            'contact_number': getattr(emp, 'contact_number', '') or '',  # Safe access
            'personnel_number': emp.personnel_number or '',
            'div_department': emp.div_department or ''
        })
    
    return jsonify({
        'success': True,
        'employees': employee_data,
        'total_count': len(employee_data)
    })

@bp.route('/sections/<int:section_id>/export')
@login_required
@admin_required
def export_section_data(section_id):
    """Export section data including approvers and new fields"""
    section = Section.query.get_or_404(section_id)
    
    import io
    import csv
    from flask import make_response
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header with new fields
    writer.writerow([
        'Name', 'Username', 'Email', 'Role', 'Unit', 'Job Title', 
        'Personnel Number', 'Div./Department', 'Employee Type', 'Schedule Format',
        'Section Approver', 'Unit Approver', 'Contact Number', 'Signature Status'
    ])
    
    # Write section members data
    for user in section.users:
        writer.writerow([
            user.full_name,
            user.username,
            user.email,
            user.role.value,
            user.unit.name if user.unit else '',
            user.job_title or '',
            user.personnel_number or '',
            user.div_department or '',
            user.employee_type.value.replace('_', ' ').title() if user.employee_type else '',
            user.schedule_format.value.replace('_', ' ').title() if user.schedule_format else '',
            'Yes' if user.is_section_approver else 'No',
            'Yes' if user.is_unit_approver else 'No',
            user.contact_number or '',
            'Uploaded' if user.signature else 'Not uploaded'
        ])
    
    # Create response
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename={section.name}_members.csv'
    
    return response

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

@bp.route('/export/otnd')
@login_required
@manager_required
def export_otnd():
    """Export OTND data - placeholder functionality"""
    flash('OTND export feature is coming soon!', 'info')
    return redirect(url_for('admin.export_data'))

@bp.route('/settings/test-url', methods=['POST'])
@login_required
@admin_required
def test_external_url():
    """Test if external URL is accessible"""
    try:
        data = request.get_json()
        test_url = data.get('url', '').strip()
        
        if not test_url:
            return jsonify({
                'success': False,
                'message': 'No URL provided to test'
            })
        
        # Basic URL validation
        import re
        url_pattern = r'^https?://.+'
        if not re.match(url_pattern, test_url):
            return jsonify({
                'success': False,
                'message': 'Invalid URL format. Must start with http:// or https://'
            })
        
        # Try to make a simple request to test connectivity
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        session = requests.Session()
        retry_strategy = Retry(
            total=2,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        try:
            response = session.head(test_url, timeout=10, allow_redirects=True)
            if response.status_code < 400:
                return jsonify({
                    'success': True,
                    'message': f'✅ URL is accessible! Status code: {response.status_code}'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'⚠️  URL returned status code {response.status_code}. Check if this is the correct URL.'
                })
        except requests.exceptions.ConnectionError:
            return jsonify({
                'success': False,
                'message': '❌ Could not connect to the URL. Check if the server is running and accessible from this network.'
            })
        except requests.exceptions.Timeout:
            return jsonify({
                'success': False,
                'message': '⏱️  Connection timed out. The server might be slow or unreachable.'
            })
        except requests.exceptions.SSLError:
            return jsonify({
                'success': False,
                'message': '🔒 SSL certificate error. Check your HTTPS configuration.'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'❌ Error testing URL: {str(e)}'
            })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error during URL test: {str(e)}'
        })

# Helper function to get app base URL (add this as a utility function)
def get_app_base_url():
    """Get the configured base URL for the application"""
    try:
        settings = AppSettings.get_settings()
        return settings.base_url
    except:
        return 'http://localhost:5000'  # Fallback

@bp.route('/debug/email')
@login_required
@admin_required
def debug_email():
    """Email debugging page for administrators"""
    config_check = EmailDebug.check_email_configuration()
    smtp_test = EmailDebug.test_smtp_connection()
    email_stats = EmailDebug.get_email_statistics()
    
    return render_template('admin/debug_email.html', 
                         config_check=config_check,
                         smtp_test=smtp_test,
                         email_stats=email_stats)

@bp.route('/debug/email/test', methods=['POST'])
@login_required
@admin_required
def test_debug_email():
    """Send debug test email"""
    try:
        data = request.get_json()
        to_email = data.get('email', current_user.email)
        
        result = EmailDebug.send_debug_test_email(to_email)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error sending debug email: {str(e)}'
        }), 500

@bp.route('/debug/email/leave/<int:leave_id>')
@login_required
@admin_required
def debug_leave_email(leave_id):
    """Debug specific leave application email"""
    try:
        result = EmailDebug.debug_leave_notification(leave_id)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error debugging leave email: {str(e)}'
        }), 500


@bp.route('/api/email-settings')
@login_required
@admin_required
def get_email_settings():
    """API endpoint to get current email settings as JSON"""
    settings = EmailSettings.get_settings()
    return jsonify({
        'success': True,
        'settings': settings.to_dict()
    })

@bp.route('/settings/app')
@login_required
@admin_required
def app_settings():
    """Application settings configuration"""
    settings = AppSettings.get_settings()
    return render_template('admin/app_settings.html', settings=settings)

@bp.route('/settings/app', methods=['POST'])
@login_required
@admin_required
def update_app_settings():
    """Update application settings"""
    try:
        settings = AppSettings.get_settings()
        
        # Update URL settings
        settings.external_url = request.form.get('external_url', '').strip() or None
        settings.app_name = request.form.get('app_name', '').strip() or 'Employee Scheduling System'
        settings.company_name = request.form.get('company_name', '').strip() or None
        settings.app_description = request.form.get('app_description', '').strip() or None
        
        # Update email settings
        settings.email_footer_text = request.form.get('email_footer_text', '').strip() or None
        settings.company_logo_url = request.form.get('company_logo_url', '').strip() or None
        
        # Update security settings
        try:
            settings.session_timeout_minutes = int(request.form.get('session_timeout_minutes', 480))
            settings.max_login_attempts = int(request.form.get('max_login_attempts', 5))
        except (ValueError, TypeError):
            flash('Invalid number format for security settings.', 'danger')
            return redirect(url_for('admin.app_settings'))
        
        # Update feature toggles
        settings.enable_leave_requests = 'enable_leave_requests' in request.form
        settings.enable_schedule_export = 'enable_schedule_export' in request.form
        settings.enable_user_registration = 'enable_user_registration' in request.form
        
        # Validate external URL format
        if settings.external_url:
            import re
            url_pattern = r'^https?://.+'
            if not re.match(url_pattern, settings.external_url):
                flash('External URL must start with http:// or https://', 'danger')
                return redirect(url_for('admin.app_settings'))
        
        db.session.commit()
        flash('Application settings updated successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating application settings: {str(e)}', 'danger')
        current_app.logger.error(f"App settings update error: {str(e)}")
    
    return redirect(url_for('admin.app_settings'))

@bp.route('/api/app-settings')
@login_required
@admin_required
def get_app_settings():
    """API endpoint to get current app settings as JSON"""
    settings = AppSettings.get_settings()
    return jsonify({
        'success': True,
        'settings': settings.to_dict()
    })

@bp.route('/users/<int:user_id>/approver-status', methods=['POST'])
@login_required
@admin_required
def update_approver_status(user_id):
    """Update user's approver status with validation for 4-level hierarchy"""
    try:
        user = User.query.get_or_404(user_id)
        data = request.get_json()
        
        # Get all approver statuses
        is_section_approver = data.get('is_section_approver', False)
        is_unit_approver = data.get('is_unit_approver', False)
        is_department_approver = data.get('is_department_approver', False)
        is_division_approver = data.get('is_division_approver', False)
        
        # Validation for 4-level hierarchy
        if is_department_approver and hasattr(user, 'department_id') and not user.department_id:
            return jsonify({
                'success': False,
                'error': 'User must be assigned to a department before becoming a department approver'
            }), 400
        
        if is_division_approver and hasattr(user, 'division_id') and not user.division_id:
            return jsonify({
                'success': False,
                'error': 'User must be assigned to a division before becoming a division approver'
            }), 400
        
        # Existing validation
        if is_section_approver and not user.section_id:
            return jsonify({
                'success': False,
                'error': 'User must be assigned to a section before becoming a section approver'
            }), 400
        
        if is_unit_approver and not user.unit_id:
            return jsonify({
                'success': False,
                'error': 'User must be assigned to a unit before becoming a unit approver'
            }), 400
        
        # Update approver status
        user.is_section_approver = is_section_approver
        user.is_unit_approver = is_unit_approver
        
        # Update 4-level approver fields if available
        if hasattr(user, 'is_department_approver'):
            user.is_department_approver = is_department_approver
        if hasattr(user, 'is_division_approver'):
            user.is_division_approver = is_division_approver
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Approver status updated for {user.full_name}',
            'approver_scope': getattr(user, 'approver_scope', 'Unknown'),
            'can_approve_leaves': user.can_approve_leaves()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Error updating approver status: {str(e)}'
        }), 500

def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.can_edit_schedule():  # Managers and Admins can edit schedule
            flash('Manager or Administrator access required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function
    
@bp.route('/export')
@login_required
@manager_required
def export_data():
    """Export Data page for managers and administrators"""
    # Get some basic stats for the export page
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    total_sections = Section.query.count()
    total_units = Unit.query.count()
    
    # Get team members based on user's scope
    if current_user.section_id:
        team_members = User.query.filter_by(section_id=current_user.section_id, is_active=True).all()
    elif current_user.unit_id:
        team_members = User.query.filter_by(unit_id=current_user.unit_id, is_active=True).all()
    else:
        team_members = User.query.filter_by(is_active=True).all()
    
    stats = {
        'total_users': total_users,
        'active_users': active_users,
        'total_sections': total_sections,
        'total_units': total_units,
        'team_members_count': len(team_members),
        'user_scope': 'All Users' if not current_user.section_id and not current_user.unit_id else 
                     f'{current_user.section.name} Section' if current_user.section_id else 
                     f'{current_user.unit.name} Unit'
    }
    
    return render_template('admin/export_data.html', stats=stats)


@bp.route('/employees')
@login_required
def employee_database():
    """Employee database view - accessible to approvers and managers"""
    # Check if user can view employee database
    if not (current_user.can_approve_leaves() or current_user.can_edit_schedule()):
        flash('Access denied. You need approver or manager privileges.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Get employees based on user's access level
    if current_user.can_admin():
        # Administrators see all employees
        employees = User.query.filter_by(is_active=True).all()
        scope = "All Employees"
    else:
        # Get employees this user can manage/approve
        approvable_employees = current_user.get_approvable_employees()
        employee_ids = [emp.id for emp in approvable_employees]
        employees = User.query.filter(User.id.in_(employee_ids), User.is_active == True).all()
        scope = current_user.approver_scope
    
    # Get all sections and units for filter dropdowns
    sections = Section.query.all()
    units = Unit.query.all()
    
    return render_template('admin/employee_database.html', 
                         employees=employees, 
                         sections=sections, 
                         units=units,
                         scope=scope)