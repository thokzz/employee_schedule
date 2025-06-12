from flask import render_template, redirect, url_for, request, flash, jsonify, current_app, session
from flask_login import login_required, current_user
from functools import wraps
from app.main import bp
from app.models import User, Shift, Section, Unit, db, EmployeeType, ScheduleFormat
from app.auth.two_factor import require_2fa_verification, require_complete_2fa, TwoFactorManager
from datetime import datetime, timedelta, date
import calendar
import os
from werkzeug.utils import secure_filename
import uuid

def _is_2fa_verified():
    """Check if current user has completed 2FA verification in this session"""
    if not current_user.is_authenticated:
        return False
    
    # Check if 2FA is required for this user
    try:
        from app.models import TwoFactorSettings
        settings = TwoFactorSettings.get_settings()
        if not settings.is_2fa_required_for_user(current_user):
            return True
    except (ImportError, AttributeError):
        # 2FA not available yet
        return True
    
    # Check session verification
    if (session.get('2fa_verified') and 
        session.get('2fa_user_id') == current_user.id):
        return True
    
    # Check trusted device
    device_token = request.cookies.get('trusted_device')
    try:
        if current_user.can_skip_2fa(device_token):
            session['2fa_verified'] = True
            session['2fa_user_id'] = current_user.id
            return True
    except AttributeError:
        # Method doesn't exist yet
        pass
    
    return False

def require_2fa(f):
    """Decorator to enforce 2FA verification before accessing protected routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        
        # Check if 2FA verification is required and completed
        if not _is_2fa_verified():
            try:
                from app.models import TwoFactorSettings, TwoFactorStatus
                settings = TwoFactorSettings.get_settings()
                
                # If 2FA is required, redirect to appropriate page
                if settings.is_2fa_required_for_user(current_user):
                    user_2fa = current_user.two_factor
                    
                    if not user_2fa or user_2fa.status in [TwoFactorStatus.DISABLED, TwoFactorStatus.PENDING_SETUP]:
                        flash('You must set up two-factor authentication to continue.', 'warning')
                        return redirect(url_for('auth.setup_2fa'))
                    elif user_2fa.status == TwoFactorStatus.GRACE_PERIOD and not user_2fa.is_in_grace_period():
                        flash('Your grace period has expired. Please set up two-factor authentication.', 'error')
                        return redirect(url_for('auth.setup_2fa'))
                    else:
                        return redirect(url_for('auth.verify_2fa'))
            except (ImportError, AttributeError):
                # 2FA not available yet
                pass
        
        return f(*args, **kwargs)
    
    return decorated_function

@bp.before_request
def check_2fa_status():
    """Check 2FA status before processing requests"""
    # Skip 2FA checks for auth routes and static files
    if (request.endpoint and 
        (request.endpoint.startswith('auth.') or 
         request.endpoint.startswith('static') or
         request.endpoint in ['main.auth_status', 'main.uploaded_signature', 'main.uploaded_avatar'])):
        return
    
    # Skip for non-authenticated users
    if not current_user.is_authenticated:
        return
    
    # Check if this is a protected route
    protected_endpoints = [
        'main.dashboard', 'main.profile', 'main.update_profile', 
        'main.update_employment_info', 'main.change_password'
    ]
    
    if request.endpoint in protected_endpoints:
        # Check authentication status
        try:
            status = TwoFactorManager.get_authentication_status(current_user)
            
            if not status['fully_authenticated']:
                if status['next_action'] == 'setup_2fa':
                    flash('Two-factor authentication setup is required.', 'warning')
                    return redirect(url_for('auth.setup_2fa'))
                elif status['next_action'] == 'verify_2fa':
                    flash('Please complete two-factor authentication.', 'warning')
                    return redirect(url_for('auth.verify_2fa'))
        except (ImportError, AttributeError):
            # 2FA not available yet
            pass

@bp.route('/')
@bp.route('/dashboard')
@login_required
@require_2fa_verification  # ADD THIS LINE
def dashboard():
    # Show 2FA status if relevant
    show_2fa_reminder = False
    
    try:
        from app.models import TwoFactorSettings, TwoFactorStatus
        settings = TwoFactorSettings.get_settings()
        
        if settings.is_2fa_required_for_user(current_user):
            user_2fa = current_user.two_factor
            if (user_2fa and 
                user_2fa.status == TwoFactorStatus.GRACE_PERIOD and 
                user_2fa.is_in_grace_period() and
                not session.get('2fa_reminder_shown')):
                show_2fa_reminder = True
                session['2fa_reminder_shown'] = True
    except (ImportError, AttributeError):
        # 2FA not available yet
        pass
    
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
    
    return render_template('main/dashboard.html', 
                         shifts=shifts, 
                         stats=stats,
                         show_2fa_reminder=show_2fa_reminder)

@bp.route('/profile')
@login_required
@require_2fa_verification
def profile():
    return render_template('main/profile.html')

@bp.route('/api/auth-status')
@login_required
def auth_status():
    """API endpoint to check authentication status"""
    try:
        status = TwoFactorManager.get_authentication_status(current_user)
        return jsonify(status)
    except (ImportError, AttributeError):
        # 2FA not available yet
        return jsonify({
            'authenticated': True,
            'password_verified': True,
            '2fa_required': False,
            '2fa_verified': True,
            'fully_authenticated': True,
            'next_action': 'proceed'
        })

@bp.context_processor
def inject_auth_status():
    """Inject authentication status into all templates"""
    if current_user.is_authenticated:
        try:
            status = TwoFactorManager.get_authentication_status(current_user)
            return dict(auth_status=status)
        except (ImportError, AttributeError):
            # 2FA not available yet
            return dict(auth_status={
                'authenticated': True,
                'password_verified': True,
                '2fa_required': False,
                '2fa_verified': True,
                'fully_authenticated': True,
                'next_action': 'proceed'
            })
    return dict(auth_status=None)

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
@require_2fa_verification  # ADD THIS LINE
def update_profile():
    try:
        current_user.first_name = request.form['first_name']
        current_user.last_name = request.form['last_name']
        current_user.email = request.form['email']
        
        # NEW: Handle contact number update
        contact_number = request.form.get('contact_number', '').strip()
        current_user.contact_number = contact_number if contact_number else None
        
        # Handle avatar upload
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename:
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
        
        # Handle signature upload
        if 'signature' in request.files:
            file = request.files['signature']
            if file and file.filename:
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
@require_2fa_verification  # ADD THIS LINE
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
@require_2fa_verification  # ADD THIS LINE
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
    """Serve uploaded signature files"""
    from flask import send_from_directory
    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'signatures')
    return send_from_directory(upload_folder, filename)

@bp.route('/avatar/<filename>')
@login_required
def uploaded_avatar(filename):
    """Serve uploaded avatar files"""
    from flask import send_from_directory
    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars')
    return send_from_directory(upload_folder, filename)