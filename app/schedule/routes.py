# =============================================================================
# 1. FIXED SCHEDULE ROUTES - app/schedule/routes.py
# =============================================================================

from flask import render_template, request, jsonify, redirect, url_for, flash, make_response
from flask_login import login_required, current_user
from app.schedule import bp
from app.models import User, Shift, Section, Unit, ShiftStatus, db
from datetime import datetime, date, timedelta, time
import calendar
import csv
import io

@bp.route('/')
@bp.route('/view')
@login_required
def view_schedule():
    # Get date range from request or default to current week
    view_type = request.args.get('view', 'week')
    date_str = request.args.get('date', date.today().isoformat())
    selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    
    if view_type == 'week':
        start_date = selected_date - timedelta(days=selected_date.weekday())
        end_date = start_date + timedelta(days=6)
        dates = [start_date + timedelta(days=i) for i in range(7)]
    elif view_type == 'month':
        start_date = selected_date.replace(day=1)
        last_day = calendar.monthrange(selected_date.year, selected_date.month)[1]
        end_date = selected_date.replace(day=last_day)
        dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    else:  # day view
        start_date = end_date = selected_date
        dates = [selected_date]
    
    # Get team members based on user role and permissions
    if current_user.can_edit_schedule():
        if current_user.section_id:
            team_members = User.query.filter_by(section_id=current_user.section_id, is_active=True).all()
        elif current_user.unit_id:
            team_members = User.query.filter_by(unit_id=current_user.unit_id, is_active=True).all()
        else:
            team_members = User.query.filter_by(is_active=True).all()
    else:
        team_members = [current_user]
    
    # Get shifts for the date range and team members - ORDER BY sequence
    shifts = Shift.query.filter(
        Shift.date.between(start_date, end_date),
        Shift.employee_id.in_([tm.id for tm in team_members])
    ).order_by(Shift.employee_id, Shift.date, Shift.sequence).all()
    
    # UPDATED: Organize shifts by employee and date - SUPPORT MULTIPLE SHIFTS
    schedule_grid = {}
    for member in team_members:
        schedule_grid[member.id] = {}
        for d in dates:
            schedule_grid[member.id][d.isoformat()] = []  # Changed to list for multiple shifts
    
    for shift in shifts:
        schedule_grid[shift.employee_id][shift.date.isoformat()].append(shift)
    
    return render_template('schedule/view.html',
                         team_members=team_members,
                         dates=dates,
                         schedule_grid=schedule_grid,
                         view_type=view_type,
                         selected_date=selected_date,
                         can_edit=current_user.can_edit_schedule())


@bp.route('/api/shift/<int:shift_id>')
@login_required
def get_shift(shift_id):
    """Get shift details for editing - THIS WAS MISSING!"""
    try:
        shift = Shift.query.get(shift_id)
        if not shift:
            return jsonify({'success': False, 'error': 'Shift not found'}), 404
        
        # Check permissions
        if not current_user.can_edit_schedule() and shift.employee_id != current_user.id:
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        return jsonify({
            'success': True,
            'shift': {
                'id': shift.id,
                'employee_id': shift.employee_id,
                'date': shift.date.isoformat(),
                'start_time': shift.start_time.strftime('%H:%M') if shift.start_time else '',
                'end_time': shift.end_time.strftime('%H:%M') if shift.end_time else '',
                'role': shift.role or '',
                'status': shift.status.value,
                'notes': shift.notes or '',
                'color': shift.color or '#007bff'
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error loading shift: {str(e)}'}), 500

@bp.route('/api/shift', methods=['POST'])
@login_required
def create_or_update_shift():
    """Create or update a shift"""
    try:
        data = request.get_json()
        
        # Validate permissions
        employee_id = int(data.get('employee_id'))
        if not current_user.can_edit_schedule() and employee_id != current_user.id:
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        shift_id = data.get('shift_id')
        if shift_id and shift_id != '':
            shift = Shift.query.get(int(shift_id))
            if not shift:
                return jsonify({'success': False, 'error': 'Shift not found'}), 404
        else:
            shift = Shift()
            shift.employee_id = employee_id
            
            # NEW: Auto-assign sequence number for new shifts
            shift_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            existing_shifts = Shift.query.filter_by(
                employee_id=employee_id, 
                date=shift_date
            ).order_by(Shift.sequence.desc()).first()
            
            shift.sequence = (existing_shifts.sequence + 1) if existing_shifts else 1
        
        # Update shift data
        shift.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        
        # Handle time fields
        if data.get('start_time') and data['start_time'].strip():
            shift.start_time = datetime.strptime(data['start_time'], '%H:%M').time()
        else:
            shift.start_time = None
            
        if data.get('end_time') and data['end_time'].strip():
            shift.end_time = datetime.strptime(data['end_time'], '%H:%M').time()
        else:
            shift.end_time = None
        
        shift.role = data.get('role', '') or None
        shift.notes = data.get('notes', '') or None
        shift.status = ShiftStatus(data.get('status', 'scheduled'))
        shift.color = data.get('color', '#007bff')
        
        if not shift_id or shift_id == '':
            db.session.add(shift)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Shift saved successfully!',
            'shift': {
                'id': shift.id,
                'date': shift.date.isoformat(),
                'time_display': shift.time_display,
                'role': shift.role,
                'status': shift.status.value,
                'notes': shift.notes,
                'color': shift.color,
                'sequence': shift.sequence
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error saving shift: {str(e)}'}), 500

@bp.route('/api/shifts/<int:employee_id>/<date_str>')
@login_required
def get_employee_day_shifts(employee_id, date_str):
    """Get all shifts for an employee on a specific date"""
    try:
        # Check permissions
        if not current_user.can_edit_schedule() and employee_id != current_user.id:
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        shift_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        shifts = Shift.query.filter_by(
            employee_id=employee_id,
            date=shift_date
        ).order_by(Shift.sequence).all()
        
        shifts_data = []
        for shift in shifts:
            shifts_data.append({
                'id': shift.id,
                'employee_id': shift.employee_id,
                'date': shift.date.isoformat(),
                'start_time': shift.start_time.strftime('%H:%M') if shift.start_time else '',
                'end_time': shift.end_time.strftime('%H:%M') if shift.end_time else '',
                'role': shift.role or '',
                'status': shift.status.value,
                'notes': shift.notes or '',
                'color': shift.color or '#007bff',
                'sequence': shift.sequence
            })
        
        return jsonify({
            'success': True,
            'shifts': shifts_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error loading shifts: {str(e)}'}), 500

@bp.route('/api/shift/<int:shift_id>', methods=['DELETE'])
@login_required
def delete_shift(shift_id):
    """Delete a shift"""
    try:
        shift = Shift.query.get(shift_id)
        if not shift:
            return jsonify({'success': False, 'error': 'Shift not found'}), 404
        
        # Check permissions
        if not current_user.can_edit_schedule() and shift.employee_id != current_user.id:
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        db.session.delete(shift)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Shift deleted successfully!'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error deleting shift: {str(e)}'}), 500

@bp.route('/export')
@login_required
def export_schedule():
    if not current_user.can_edit_schedule():
        flash('You do not have permission to export schedules.', 'danger')
        return redirect(url_for('schedule.view_schedule'))
    
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    if not start_date_str or not end_date_str:
        flash('Please provide start and end dates for export.', 'warning')
        return redirect(url_for('schedule.view_schedule'))
    
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    
    # Get shifts for date range
    shifts = Shift.query.filter(
        Shift.date.between(start_date, end_date)
    ).join(User).all()
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Employee', 'Date', 'Start Time', 'End Time', 'Role', 'Status', 'Notes', 'Color'])
    
    # Write shift data
    for shift in shifts:
        writer.writerow([
            shift.employee.full_name,
            shift.date.strftime('%Y-%m-%d'),
            shift.start_time.strftime('%H:%M') if shift.start_time else '',
            shift.end_time.strftime('%H:%M') if shift.end_time else '',
            shift.role or '',
            shift.status.value,
            shift.notes or '',
            shift.color or ''
        ])
    
    # Create response
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=schedule_{start_date}_{end_date}.csv'
    
    return response