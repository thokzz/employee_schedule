from flask import render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app.main import bp
from app.models import User, Shift, Section, Unit, db
from datetime import datetime, timedelta, date
import calendar

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

@bp.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    try:
        current_user.first_name = request.form['first_name']
        current_user.last_name = request.form['last_name']
        current_user.email = request.form['email']
        
        # Handle avatar upload
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename:
                filename = f"avatar_{current_user.id}_{datetime.now().timestamp()}.jpg"
                file.save(f"app/static/uploads/{filename}")
                current_user.avatar = filename
        
        db.session.commit()
        flash('Personal information updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating profile: {str(e)}', 'danger')
    
    return redirect(url_for('main.profile'))

@bp.route('/profile/employment', methods=['POST'])
@login_required
def update_employment_info():
    try:
        current_user.personnel_number = request.form.get('personnel_number') or None
        current_user.typecode = request.form.get('typecode') or None
        current_user.id_number = request.form.get('id_number') or None
        current_user.job_title = request.form.get('job_title') or None
        current_user.rank = request.form.get('rank') or None
        
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
    
    return redirect(url_for('main.profile'))