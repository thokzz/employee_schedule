from flask import render_template, redirect, url_for, request, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.main import bp
from app.models import User, Shift, Section, Unit, db, EmployeeType, ScheduleFormat
from datetime import datetime, timedelta, date
import calendar
import os
from werkzeug.utils import secure_filename
import uuid

@bp.route('/')
@bp.route('/dashboard')
@login_required
def dashboard():
    # Get current week's shifts for the user
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    
    if current_user.can_edit_schedule():
        # Managers and admins see all shifts in their section/unit
        if current_user.section_id:
            users_query = User.query.filter_by(section_id=current_user.section_id)
        elif current_user.unit_id:
            users_query = User.query.filter_by(unit_id=current_user.unit_id)
        else:
            users_query = User.query.all()
        
        shifts = Shift.query.filter(
            Shift.date.between(start_of_week, end_of_week),
            Shift.employee_id.in_([u.id for u in users_query])
        ).all()
    else:
        # Employees see only their own shifts
        shifts = current_user.shifts.filter(
            Shift.date.between(start_of_week, end_of_week)
        ).all()
    
    # Stats for dashboard
    stats = {
        'total_shifts': len(shifts),
        'scheduled_shifts': len([s for s in shifts if s.status.value == 'scheduled']),
        'leave_requests': len([s for s in shifts if 'leave' in s.status.value]),
        'rest_days': len([s for s in shifts if s.status.value == 'rest_day'])
    }
    
    return render_template('main/dashboard.html', shifts=shifts, stats=stats)

@bp.route('/profile')
@login_required
def profile():
    return render_template('main/profile.html')

def allowed_file(filename, allowed_extensions):
    """Check if file has allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def save_uploaded_file(file, upload_folder, prefix="", allowed_extensions={'png', 'jpg', 'jpeg'}):
    """Save uploaded file with secure filename"""
    try:
        if not file or not file.filename:
            return None
            
        if not allowed_file(file.filename, allowed_extensions):
            return None
            
        # Create unique filename
        filename = secure_filename(file.filename)
        name, ext = os.path.splitext(filename)
        unique_filename = f"{prefix}_{current_user.id}_{uuid.uuid4().hex[:8]}{ext}"
        
        # Ensure upload folder exists
        os.makedirs(upload_folder, exist_ok=True)
        
        # Save file
        file_path = os.path.join(upload_folder, unique_filename)
        file.save(file_path)
        
        return unique_filename
        
    except Exception as e:
        current_app.logger.error(f"Error saving file: {str(e)}")
        return None

@bp.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    try:
        current_user.first_name = request.form['first_name']
        current_user.last_name = request.form['last_name']
        current_user.email = request.form['email']
        
        # Handle avatar upload - UPDATED PATH
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename:
                # Use static/uploads instead of instance_path
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars')
                filename = save_uploaded_file(
                    file, 
                    upload_folder, 
                    prefix="avatar",
                    allowed_extensions={'png', 'jpg', 'jpeg', 'gif'}
                )
                if filename:
                    # Delete old avatar if exists
                    if current_user.avatar and current_user.avatar != 'default_avatar.png':
                        try:
                            old_path = os.path.join(upload_folder, current_user.avatar)
                            if os.path.exists(old_path):
                                os.remove(old_path)
                        except:
                            pass
                    current_user.avatar = filename
                else:
                    flash('Invalid avatar file. Please upload a valid image file.', 'warning')
        
        # Handle signature upload - UPDATED PATH
        if 'signature' in request.files:
            file = request.files['signature']
            if file and file.filename:
                # Use static/uploads instead of instance_path
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'signatures')
                filename = save_uploaded_file(
                    file, 
                    upload_folder, 
                    prefix="signature",
                    allowed_extensions={'png'}  # Only PNG for signatures
                )
                if filename:
                    # Delete old signature if exists
                    if current_user.signature:
                        try:
                            old_path = os.path.join(upload_folder, current_user.signature)
                            if os.path.exists(old_path):
                                os.remove(old_path)
                        except:
                            pass
                    current_user.signature = filename
                    flash('Digital signature uploaded successfully!', 'success')
                else:
                    flash('Invalid signature file. Please upload a PNG file only.', 'warning')
        
        db.session.commit()
        flash('Personal information updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating profile: {str(e)}', 'danger')
        current_app.logger.error(f"Profile update error: {str(e)}")
    
    return redirect(url_for('main.profile'))

@bp.route('/profile/employment', methods=['POST'])
@login_required
def update_employment_info():
    try:
        current_user.personnel_number = request.form.get('personnel_number') or None
        current_user.div_department = request.form.get('div_department') or None
        current_user.typecode = request.form.get('typecode') or None
        current_user.id_number = request.form.get('id_number') or None
        current_user.job_title = request.form.get('job_title') or None
        current_user.rank = request.form.get('rank') or None
        
        # Handle employee type enum
        employee_type_value = request.form.get('employee_type')
        if employee_type_value:
            try:
                current_user.employee_type = EmployeeType(employee_type_value)
            except ValueError:
                current_user.employee_type = None
        else:
            current_user.employee_type = None
        
        # Handle schedule format enum
        schedule_format_value = request.form.get('schedule_format')
        if schedule_format_value:
            try:
                current_user.schedule_format = ScheduleFormat(schedule_format_value)
            except ValueError:
                current_user.schedule_format = None
        else:
            current_user.schedule_format = None
        
        # Handle hiring date
        hiring_date_str = request.form.get('hiring_date')
        if hiring_date_str:
            current_user.hiring_date = datetime.strptime(hiring_date_str, '%Y-%m-%d').date()
        else:
            current_user.hiring_date = None
        
        db.session.commit()
        flash('Employment information updated successfully!', 'success')
    except ValueError as e:
        db.session.rollback()
        flash('Invalid date format. Please use YYYY-MM-DD format.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating employment information: {str(e)}', 'danger')
        current_app.logger.error(f"Employment update error: {str(e)}")
    
    return redirect(url_for('main.profile'))

@bp.route('/profile/password', methods=['POST'])
@login_required
def change_password():
    try:
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        
        # Verify current password
        if not current_user.check_password(current_password):
            flash('Current password is incorrect.', 'danger')
            return redirect(url_for('main.profile'))
        
        # Validate new password
        if len(new_password) < 6:
            flash('New password must be at least 6 characters long.', 'danger')
            return redirect(url_for('main.profile'))
        
        # Confirm password match
        if new_password != confirm_password:
            flash('New passwords do not match.', 'danger')
            return redirect(url_for('main.profile'))
        
        # Update password
        current_user.set_password(new_password)
        db.session.commit()
        
        flash('Password changed successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error changing password: {str(e)}', 'danger')
        current_app.logger.error(f"Password change error: {str(e)}")
    
    return redirect(url_for('main.profile'))

@bp.route('/signature/<filename>')
@login_required
def uploaded_signature(filename):
    """Serve uploaded signature files - UPDATED PATH"""
    from flask import send_from_directory
    # Use static/uploads instead of instance_path
    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'signatures')
    return send_from_directory(upload_folder, filename)

@bp.route('/avatar/<filename>')
@login_required
def uploaded_avatar(filename):
    """Serve uploaded avatar files - UPDATED PATH"""
    from flask import send_from_directory
    # Use static/uploads instead of instance_path
    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars')
    return send_from_directory(upload_folder, filename)