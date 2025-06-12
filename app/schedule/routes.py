# =============================================================================
# ENHANCED SCHEDULE ROUTES - app/schedule/routes.py
# Added Export Worksched function for managers
# =============================================================================

from flask import render_template, request, jsonify, redirect, url_for, flash, make_response
from flask_login import login_required, current_user
from app.schedule import bp
from app.models import (User, Shift, Section, Unit, ShiftStatus, WorkArrangement, db, 
                       DateRemark, DateRemarkType, ScheduleFormat, EmployeeType, ScheduleTemplateV2, TemplateType)  
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
    
    # UPDATED: Get team members based on user role and permissions
    if current_user.can_edit_schedule():
        # Managers and Admins see their organizational scope
        if current_user.section_id:
            team_members = User.query.filter_by(section_id=current_user.section_id, is_active=True).all()
        elif current_user.unit_id:
            team_members = User.query.filter_by(unit_id=current_user.unit_id, is_active=True).all()
        else:
            team_members = User.query.filter_by(is_active=True).all()
    else:
        # UPDATED: Regular employees can see their entire section
        if current_user.section_id:
            team_members = User.query.filter_by(section_id=current_user.section_id, is_active=True).all()
        elif current_user.unit_id:
            # If employee has unit but no section, show unit members
            team_members = User.query.filter_by(unit_id=current_user.unit_id, is_active=True).all()
        else:
            # Fallback: show only current user if no organizational assignment
            team_members = [current_user]
    
    # UPDATED: Sort team members by Unit name (if exists), then by last name
    def sort_key(member):
        unit_name = member.unit.name if member.unit else "ZZZ_No_Unit"  # Put users without unit at the end
        last_name = member.last_name or "ZZZ_No_Name"  # Handle missing last name
        return (unit_name, last_name)
    
    team_members = sorted(team_members, key=sort_key)
    
    # Get shifts for the date range and team members - ORDER BY sequence
    shifts = Shift.query.filter(
        Shift.date.between(start_date, end_date),
        Shift.employee_id.in_([tm.id for tm in team_members])
    ).order_by(Shift.employee_id, Shift.date, Shift.sequence).all()
    
    # TEMPORARY: Empty date remarks until DateRemark model is implemented
    date_remarks_dict = {}
    
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
                         date_remarks=date_remarks_dict,  # Empty for now
                         view_type=view_type,
                         selected_date=selected_date,
                         today=date.today(),
                         can_edit=current_user.can_edit_schedule())


@bp.route('/api/shift/<int:shift_id>')
@login_required
def get_shift(shift_id):
    """Get shift details for editing - THIS WAS MISSING!"""
    try:
        shift = Shift.query.get(shift_id)
        if not shift:
            return jsonify({'success': False, 'error': 'Shift not found'}), 404
        
        # UPDATED: Check permissions - allow viewing section schedules
        can_view = False
        
        if current_user.can_edit_schedule():
            can_view = True
        elif shift.employee_id == current_user.id:
            can_view = True
        elif current_user.section_id and shift.employee.section_id == current_user.section_id:
            # Allow viewing shifts within same section
            can_view = True
        elif current_user.unit_id and shift.employee.unit_id == current_user.unit_id:
            # Allow viewing shifts within same unit (if no section)
            can_view = True
        
        if not can_view:
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
                'color': shift.color or '#007bff',
                'work_arrangement': shift.work_arrangement.value if shift.work_arrangement else 'onsite',
                'work_arrangement': shift.work_arrangement.value if shift.work_arrangement else 'onsite'
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
        
        # UPDATED: Validate permissions for editing (not just viewing)
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
        shift.status = ShiftStatus(data.get('status', 'scheduled'))
        
        # FIXED: Handle time fields conditionally based on status
        if shift.status == ShiftStatus.SCHEDULED:
            # For scheduled shifts, require time fields
            if data.get('start_time') and data['start_time'].strip():
                shift.start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            else:
                shift.start_time = None
                
            if data.get('end_time') and data['end_time'].strip():
                shift.end_time = datetime.strptime(data['end_time'], '%H:%M').time()
            else:
                shift.end_time = None
                
            shift.role = data.get('role', '') or None
            shift.work_arrangement = WorkArrangement(data.get('work_arrangement', 'onsite'))
            
        elif shift.status == ShiftStatus.REST_DAY:
            # FIXED: For rest days, clear time and work fields
            shift.start_time = None
            shift.end_time = None
            shift.role = None
            shift.work_arrangement = WorkArrangement.ONSITE  # Default for rest days
            
        else:
            # FIXED: For leave types, clear times but keep work arrangement
            shift.start_time = None
            shift.end_time = None
            shift.role = None
            # Keep work arrangement for leave types (might be WFH, etc.)
            if data.get('work_arrangement'):
                shift.work_arrangement = WorkArrangement(data.get('work_arrangement', 'onsite'))
            else:
                shift.work_arrangement = WorkArrangement.ONSITE
        
        # Always set these fields regardless of status
        shift.notes = data.get('notes', '') or None
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
        # UPDATED: Check permissions for viewing
        can_view = False
        
        if current_user.can_edit_schedule():
            can_view = True
        elif employee_id == current_user.id:
            can_view = True
        else:
            # Check if employee is in same section/unit
            employee = User.query.get(employee_id)
            if employee:
                if current_user.section_id and employee.section_id == current_user.section_id:
                    can_view = True
                elif current_user.unit_id and employee.unit_id == current_user.unit_id:
                    can_view = True
        
        if not can_view:
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
                'sequence': shift.sequence,
                'work_arrangement': shift.work_arrangement.value if shift.work_arrangement else 'onsite'
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
        
        # Check permissions - only allow editing own shifts for regular employees
        if not current_user.can_edit_schedule() and shift.employee_id != current_user.id:
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        db.session.delete(shift)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Shift deleted successfully!'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error deleting shift: {str(e)}'}), 500

# ... [Rest of the routes remain the same - keeping them unchanged for brevity]

@bp.route('/api/date-remarks')
@login_required
def get_date_remarks():
    """Get date remarks for a date range"""
    try:
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        if not start_date_str or not end_date_str:
            return jsonify({'success': False, 'error': 'Start and end dates required'}), 400
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        remarks = DateRemark.get_remarks_for_period(start_date, end_date)
        
        return jsonify({
            'success': True,
            'remarks': [remark.to_dict() for remark in remarks]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error loading date remarks: {str(e)}'}), 500


@bp.route('/api/date-remarks', methods=['POST'])
@login_required
def create_or_update_date_remark():
    """Create or update a date remark"""
    try:
        # Check permissions - only managers and admins can create/edit date remarks
        if not current_user.can_edit_schedule():
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        data = request.get_json()
        
        remark_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        
        # Check if remark already exists for this date
        existing_remark = DateRemark.get_remark_for_date(remark_date)
        
        if existing_remark:
            # Update existing remark
            remark = existing_remark
        else:
            # Create new remark
            remark = DateRemark()
            remark.date = remark_date
            remark.created_by_id = current_user.id
        
        # Update remark data
        remark.title = data.get('title', '').strip()
        remark.description = data.get('description', '').strip() or None
        remark.remark_type = DateRemarkType(data.get('remark_type', 'holiday'))
        remark.color = data.get('color', '#dc3545')
        remark.is_work_day = data.get('is_work_day', False)
        remark.updated_at = datetime.utcnow()
        
        if not existing_remark:
            db.session.add(remark)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Date remark saved successfully!',
            'remark': remark.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error saving date remark: {str(e)}'}), 500

@bp.route('/api/date-remarks/<int:remark_id>', methods=['DELETE'])
@login_required
def delete_date_remark(remark_id):
    """Delete a date remark"""
    try:
        # Check permissions
        if not current_user.can_edit_schedule():
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        remark = DateRemark.query.get(remark_id)
        if not remark:
            return jsonify({'success': False, 'error': 'Date remark not found'}), 404
        
        db.session.delete(remark)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Date remark deleted successfully!'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error deleting date remark: {str(e)}'}), 500

@bp.route('/api/holidays/preset')
@login_required
def get_preset_holidays():
    """Get preset holidays for the Philippines"""
    if not current_user.can_edit_schedule():
        return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
    
    # You can expand this with more holidays or make it configurable
    preset_holidays = [
        {'title': 'New Year\'s Day', 'month': 1, 'day': 1},
        {'title': 'Maundy Thursday', 'month': 3, 'day': 28},  # Example date - varies yearly
        {'title': 'Good Friday', 'month': 3, 'day': 29},      # Example date - varies yearly
        {'title': 'Araw ng Kagitingan', 'month': 4, 'day': 9},
        {'title': 'Labor Day', 'month': 5, 'day': 1},
        {'title': 'Independence Day', 'month': 6, 'day': 12},
        {'title': 'National Heroes Day', 'month': 8, 'day': 26},  # Last Monday of August
        {'title': 'All Saints\' Day', 'month': 11, 'day': 1},
        {'title': 'Bonifacio Day', 'month': 11, 'day': 30},
        {'title': 'Christmas Day', 'month': 12, 'day': 25},
        {'title': 'Rizal Day', 'month': 12, 'day': 30},
        {'title': 'New Year\'s Eve', 'month': 12, 'day': 31}
    ]
    
    return jsonify({
        'success': True,
        'holidays': preset_holidays
    })

@bp.route('/api/holidays/apply-preset', methods=['POST'])
@login_required
def apply_preset_holidays():
    """Apply preset holidays for a specific year"""
    try:
        if not current_user.can_edit_schedule():
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        data = request.get_json()
        year = int(data.get('year', datetime.now().year))
        selected_holidays = data.get('holidays', [])
        
        created_count = 0
        skipped_count = 0
        
        for holiday in selected_holidays:
            holiday_date = date(year, holiday['month'], holiday['day'])
            
            # Check if holiday already exists
            existing = DateRemark.get_remark_for_date(holiday_date)
            if existing:
                skipped_count += 1
                continue
            
            # Create new holiday
            remark = DateRemark(
                date=holiday_date,
                title=holiday['title'],
                remark_type=DateRemarkType.HOLIDAY,
                color='#dc3545',
                is_work_day=False,
                created_by_id=current_user.id
            )
            
            db.session.add(remark)
            created_count += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Applied {created_count} holidays for {year}. {skipped_count} holidays were skipped (already exist).',
            'created_count': created_count,
            'skipped_count': skipped_count
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error applying preset holidays: {str(e)}'}), 500

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

@bp.route('/api/employee/<int:employee_id>/schedule-format')
@login_required
def get_employee_schedule_format(employee_id):
    """Get employee's schedule format for break calculations"""
    try:
        # Check permissions
        if not current_user.can_edit_schedule() and employee_id != current_user.id:
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        employee = User.query.get(employee_id)
        if not employee:
            return jsonify({'success': False, 'error': 'Employee not found'}), 404
        
        return jsonify({
            'success': True,
            'schedule_format': employee.schedule_format.value if employee.schedule_format else '8_hour_shift',
            'break_duration_minutes': employee.get_break_duration_minutes(),
            'employee_type': employee.employee_type.value if employee.employee_type else 'rank_and_file'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error getting employee info: {str(e)}'}), 500

@bp.route('/export-worksched')
@login_required
def export_worksched():
    """Export work schedule in the specific company format for managers"""
    if not current_user.can_edit_schedule():
        flash('You do not have permission to export work schedules.', 'danger')
        return redirect(url_for('schedule.view_schedule'))
    
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    if not start_date_str or not end_date_str:
        flash('Please provide start and end dates for export.', 'warning')
        return redirect(url_for('schedule.view_schedule'))
    
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    
    # Get team members based on manager's scope
    if current_user.section_id:
        team_members = User.query.filter_by(section_id=current_user.section_id, is_active=True).all()
    elif current_user.unit_id:
        team_members = User.query.filter_by(unit_id=current_user.unit_id, is_active=True).all()
    else:
        team_members = User.query.filter_by(is_active=True).all()
    
    # Get all shifts for the date range and team members
    shifts = Shift.query.filter(
        Shift.date.between(start_date, end_date),
        Shift.employee_id.in_([tm.id for tm in team_members])
    ).order_by(Shift.employee_id, Shift.date, Shift.sequence).all()
    
    # Organize shifts by employee and date
    employee_shifts = {}
    for shift in shifts:
        emp_id = shift.employee_id
        shift_date = shift.date
        
        if emp_id not in employee_shifts:
            employee_shifts[emp_id] = {}
        if shift_date not in employee_shifts[emp_id]:
            employee_shifts[emp_id][shift_date] = []
        
        employee_shifts[emp_id][shift_date].append(shift)
    
    # Create CSV in the specific company format
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header rows (exactly as in the template)
    writer.writerow(['Regular Work Schedule', '', '', '', '', '', '', '', '', '', ''])
    writer.writerow([
        'EMPLOYEE', 
        'WORK SCHEDULE (Dates)', 
        '', 
        'DWS', 
        'WORK SCHEDULE\n(TIME)', 
        '', 
        '1 HR UNPAID BREAK\n(9-HOUR SHIFT)', 
        '', 
        '30 MIN PAID BREAK\n(8-HOUR SHIFT)', 
        '', 
        ''
    ])
    writer.writerow(['FROM', 'TO', 'START', 'END', 'START', 'END', 'START', 'END', 'START', 'END', ''])
    writer.writerow(['', '', '', '', '', '', '', '', '', '', 'REMARKS'])
    
    def get_standard_schedule_for_employee(employee):
        """Get standard work schedule based on employee's schedule format - FALLBACK ONLY"""
        if employee.schedule_format == ScheduleFormat.NINE_HOUR:
            return {
                'start_time': '10:00',  # Default fallback start time
                'end_time': '19:00',    # 10:00 + 9 hours = 19:00 (7PM)
                'break_1hr_start': '13:00',
                'break_1hr_end': '14:00',
                'break_30min_start': '',
                'break_30min_end': ''
            }
        else:  # 8-hour shift or default
            return {
                'start_time': '10:00',  # Default fallback start time
                'end_time': '18:00',    # 10:00 + 8 hours = 18:00 (6PM)
                'break_1hr_start': '',
                'break_1hr_end': '',
                'break_30min_start': '13:00',
                'break_30min_end': '13:30'
            }
    
    def get_standard_shift_times(shift, employee):
        """Get standardized shift times based on employee's schedule format"""
        if not shift.start_time:
            return '', ''
        
        start_datetime = datetime.combine(shift.date, shift.start_time)
        
        # Calculate end time based on employee's schedule format
        if employee.schedule_format == ScheduleFormat.NINE_HOUR:
            end_datetime = start_datetime + timedelta(hours=9)
        else:  # 8-hour shift or default
            end_datetime = start_datetime + timedelta(hours=8)
        
        work_start = start_datetime.strftime('%H:%M')
        work_end = end_datetime.strftime('%H:%M')
        
        return work_start, work_end

    def get_schedule_for_leave_day(employee, employee_shifts_for_date):
        """Get schedule for leave day based on 1st shift start time"""
        
        # Find the first shift (sequence #1) for this employee on this date
        if employee_shifts_for_date:
            first_shift = min(employee_shifts_for_date, key=lambda x: x.sequence)
            
            if first_shift.start_time:
                # Use 1st shift start time as base
                start_datetime = datetime.combine(date.today(), first_shift.start_time)
                
                # Calculate end time based on employee's schedule format
                if employee.schedule_format == ScheduleFormat.NINE_HOUR:
                    end_datetime = start_datetime + timedelta(hours=9)
                    break_duration = 60  # 1 hour break
                else:  # 8-hour shift
                    end_datetime = start_datetime + timedelta(hours=8)
                    break_duration = 30  # 30 minute break
                
                # Calculate break times (start 3 hours after shift start)
                break_start_datetime = start_datetime + timedelta(hours=3)
                break_end_datetime = break_start_datetime + timedelta(minutes=break_duration)
                
                if employee.schedule_format == ScheduleFormat.NINE_HOUR:
                    return {
                        'start_time': start_datetime.strftime('%H:%M'),
                        'end_time': end_datetime.strftime('%H:%M'),
                        'break_1hr_start': break_start_datetime.strftime('%H:%M'),
                        'break_1hr_end': break_end_datetime.strftime('%H:%M'),
                        'break_30min_start': '',
                        'break_30min_end': ''
                    }
                else:  # 8-hour shift
                    return {
                        'start_time': start_datetime.strftime('%H:%M'),
                        'end_time': end_datetime.strftime('%H:%M'),
                        'break_1hr_start': '',
                        'break_1hr_end': '',
                        'break_30min_start': break_start_datetime.strftime('%H:%M'),
                        'break_30min_end': break_end_datetime.strftime('%H:%M')
                    }
        
        # Fallback to standard schedule if no shifts found or no start time
        return get_standard_schedule_for_employee(employee)

    def calculate_break_times_for_shift(shift, employee):
        """Calculate break times based on employee's schedule format and shift start time"""
        if not shift.start_time or not shift.qualifies_for_break:
            return ('', '', '', '')  # No break times if shift < 4 hours or no start time
        
        start_datetime = datetime.combine(shift.date, shift.start_time)
        break_start_datetime = start_datetime + timedelta(hours=3)  # Break starts 3 hours after shift start
        
        break_duration = employee.get_break_duration_minutes()
        break_end_datetime = break_start_datetime + timedelta(minutes=break_duration)
        
        # Determine which columns to fill based on employee's schedule format
        if employee.schedule_format == ScheduleFormat.NINE_HOUR:  # 1 hr break
            return (
                break_start_datetime.strftime('%H:%M'),  # 1hr break start
                break_end_datetime.strftime('%H:%M'),    # 1hr break end
                '',  # 30min break start (empty)
                ''   # 30min break end (empty)
            )
        else:  # 8-hour shift or others (30 min break)
            return (
                '',  # 1hr break start (empty)
                '',  # 1hr break end (empty)
                break_start_datetime.strftime('%H:%M'),  # 30min break start
                break_end_datetime.strftime('%H:%M')     # 30min break end
            )
    
    def get_filtered_remarks(status_value):
        """Filter remarks to show only specific leave type abbreviations"""
        leave_abbreviations = {
            'sick_leave': 'SL',
            'personal_leave': 'PL',
            'emergency_leave': 'EL',
            'annual_vacation': 'AVL',
            'bereavement_leave': 'BL',
            'paternity_leave': 'PatL',
            'maternity_leave': 'MatL',
            'union_leave': 'UL',
            'fire_calamity_leave': 'FCL',
            'solo_parent_leave': 'SPL',
            'special_leave_women': 'SLW',
            'vawc_leave': 'VAWCL',
            'other': 'OFFSET',
            'offset': 'OFFSET'
        }
        
        # Return the abbreviation if it's a recognized leave type, otherwise return blank
        return leave_abbreviations.get(status_value, '')
    
    # FIXED: Generate data by employee first, then by date
    for employee in sorted(team_members, key=lambda x: x.full_name):
        current_date = start_date
        while current_date <= end_date:
            emp_shifts = employee_shifts.get(employee.id, {}).get(current_date, [])
            
            # Format employee name as "LASTNAME, FIRSTNAME"
            employee_name = f"{employee.last_name.upper()}, {employee.first_name.upper()}"
            
            # Format date as DD-MM-YYYY
            formatted_date = current_date.strftime('%d-%m-%Y')
            
            if not emp_shifts:
                # No shifts = rest day (use blank remarks)
                writer.writerow([
                    employee_name,
                    formatted_date,
                    formatted_date,
                    'FREE',  # DWS = FREE for rest days
                    '',  # Work start time
                    '',  # Work end time
                    '',  # 1hr break start
                    '',  # 1hr break end
                    '',  # 30min break start
                    '',  # 30min break end
                    ''   # Remarks - blank for rest days
                ])
            else:
                # CORRECTED: For leave days, only create ONE row (not one per shift)
                leave_shifts = [s for s in emp_shifts if s.status in [
                    ShiftStatus.SICK_LEAVE, ShiftStatus.PERSONAL_LEAVE, 
                    ShiftStatus.EMERGENCY_LEAVE, ShiftStatus.ANNUAL_VACATION,
                    ShiftStatus.HOLIDAY_OFF, ShiftStatus.BEREAVEMENT_LEAVE,
                    ShiftStatus.PATERNITY_LEAVE, ShiftStatus.MATERNITY_LEAVE,
                    ShiftStatus.UNION_LEAVE, ShiftStatus.FIRE_CALAMITY_LEAVE,
                    ShiftStatus.SOLO_PARENT_LEAVE, ShiftStatus.SPECIAL_LEAVE_WOMEN,
                    ShiftStatus.VAWC_LEAVE, ShiftStatus.OTHER, ShiftStatus.OFFSET
                ]]
                
                rest_day_shifts = [s for s in emp_shifts if s.status == ShiftStatus.REST_DAY]
                
                if leave_shifts:
                    # CORRECTED: Leave days get ONE row using 1st shift start time
                    leave_schedule = get_schedule_for_leave_day(employee, emp_shifts)
                    status_value = leave_shifts[0].status.value
                    remarks = get_filtered_remarks(status_value)
                    
                    writer.writerow([
                        employee_name,
                        formatted_date,
                        formatted_date,
                        '',  # No DWS for leave
                        leave_schedule['start_time'],
                        leave_schedule['end_time'],
                        leave_schedule['break_1hr_start'],
                        leave_schedule['break_1hr_end'],
                        leave_schedule['break_30min_start'],
                        leave_schedule['break_30min_end'],
                        remarks
                    ])
                    
                elif rest_day_shifts:
                    # Rest days use blank remarks
                    writer.writerow([
                        employee_name,
                        formatted_date,
                        formatted_date,
                        'FREE',
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                        ''  # Blank remarks for rest days
                    ])
                else:
                    # Handle regular scheduled shifts (one row per shift)
                    for shift in emp_shifts:
                        # CORRECTED: Use standard shift times (not actual times)
                        work_start, work_end = get_standard_shift_times(shift, employee)
                        
                        # Calculate break times based on employee's schedule format
                        break_1hr_start, break_1hr_end, break_30min_start, break_30min_end = calculate_break_times_for_shift(shift, employee)
                        
                        # For regular shifts, use blank remarks
                        remarks = ''
                        
                        writer.writerow([
                            employee_name,
                            formatted_date,
                            formatted_date,      # Same as FROM date
                            '',                  # DWS blank for regular schedule
                            work_start,          # CORRECTED: Standard shift start time
                            work_end,            # CORRECTED: Standard shift end time
                            break_1hr_start,     # 1hr paid break start (for 9-hour shifts)
                            break_1hr_end,       # 1hr paid break end (for 9-hour shifts)
                            break_30min_start,   # 30min paid break start (for 8-hour shifts)
                            break_30min_end,     # 30min paid break end (for 8-hour shifts)
                            remarks              # Blank remarks for regular shifts
                        ])
            
            current_date += timedelta(days=1)
    
    # Create response
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=worksched_{start_date.strftime("%b_%d")}_to_{end_date.strftime("%b_%d_%Y")}.csv'
    
    return response

# OTND EXPORT DATA


@bp.route('/export-otnd')
@login_required
def export_otnd():
    """Export OTND (Overtime & Night Differential) data for payroll processing"""
    if not current_user.can_edit_schedule():
        flash('You do not have permission to export OTND data.', 'danger')
        return redirect(url_for('schedule.view_schedule'))
    
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    if not start_date_str or not end_date_str:
        flash('Please provide start and end dates for OTND export.', 'warning')
        return redirect(url_for('admin.export_data'))
    
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    
    # NEW: Extend query range to catch cross-midnight shifts
    extended_start_date = start_date - timedelta(days=1)
    
    # Get team members based on manager's scope - only RANK_AND_FILE employees
    from app.models import EmployeeType
    
    if current_user.section_id:
        team_members = User.query.filter(
            User.section_id == current_user.section_id,
            User.is_active == True,
            User.employee_type.in_([EmployeeType.RANK_AND_FILE, EmployeeType.RANK_AND_FILE_PROBATIONARY])
        ).all()
    elif current_user.unit_id:
        team_members = User.query.filter(
            User.unit_id == current_user.unit_id,
            User.is_active == True,
            User.employee_type.in_([EmployeeType.RANK_AND_FILE, EmployeeType.RANK_AND_FILE_PROBATIONARY])
        ).all()
    else:
        team_members = User.query.filter(
            User.is_active == True,
            User.employee_type.in_([EmployeeType.RANK_AND_FILE, EmployeeType.RANK_AND_FILE_PROBATIONARY])
        ).all()
    
    # MODIFIED: Get shifts with extended range
    shifts = Shift.query.filter(
        Shift.date.between(extended_start_date, end_date),  # Extended range
        Shift.employee_id.in_([tm.id for tm in team_members]),
        Shift.status.in_([ShiftStatus.SCHEDULED, ShiftStatus.HOLIDAY_OFF])
    ).order_by(Shift.employee_id, Shift.date, Shift.sequence).all()
    
    # UNCHANGED: Get date remarks (holidays) - keep original range
    date_remarks = DateRemark.query.filter(
        DateRemark.date.between(start_date, end_date),
        DateRemark.remark_type == DateRemarkType.HOLIDAY
    ).all()
    
    holiday_dates = {remark.date for remark in date_remarks}
    
    # MODIFIED: Calculate OTND entries with export range
    otnd_entries = []
    
    for employee in sorted(team_members, key=lambda x: x.last_name):
        employee_shifts = [s for s in shifts if s.employee_id == employee.id]
        
        for shift in employee_shifts:
            # Skip if no times set or invalid shift
            if not shift.start_time or not shift.end_time:
                continue
                
            # MODIFIED: Pass export date range to calculation function
            shift_entries = calculate_otnd_for_shift(employee, shift, holiday_dates, start_date, end_date)
            otnd_entries.extend(shift_entries)
    
    # NEW: Filter entries to only include relevant ones for the export
    otnd_entries = filter_otnd_entries_by_export_range(otnd_entries, start_date, end_date)
    
    # Sort entries by employee last name, then by date, then by type
    otnd_entries.sort(key=lambda x: (x['SURNAME'], x['START DATE'], x['TYPE']))
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header exactly as specified
    writer.writerow([
        'SURNAME', 'EMPLOYEE NAME', 'TYPE', 'PERSONNEL NUMBER', 'TYPE CODE',
        'START TIME', 'END TIME', 'START DATE', 'END DATE', '', 'TOTAL HOURS', 
        'REASON/REMARKS', 'SECTION', 'UNIT'
    ])
    
    # Write OTND data
    for entry in otnd_entries:
        writer.writerow([
            entry['SURNAME'],
            entry['EMPLOYEE NAME'],
            entry['TYPE'],
            entry['PERSONNEL NUMBER'],
            entry['TYPE CODE'],
            entry['START TIME'],
            entry['END TIME'],
            entry['START DATE'],
            entry['END DATE'],
            '',  # BLANK COLUMN
            entry['TOTAL HOURS'],
            entry['REASON/REMARKS'],
            entry['SECTION'],
            entry['UNIT']
        ])
    
    # Create response
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=OTND_{start_date.strftime("%b_%d")}_to_{end_date.strftime("%b_%d_%Y")}.csv'
    
    return response


def calculate_otnd_for_shift(employee, shift, holiday_dates, export_start_date, export_end_date):
    """Calculate OTND entries for a single shift with proper priority hierarchy"""
    entries = []
    
    # Get employee details
    surname = employee.last_name.upper()
    employee_name = employee.first_name.upper()
    personnel_number = employee.personnel_number or ''
    employee_type_code = employee.typecode or ''
    
    # Get section and unit separately
    section_name = employee.section.name if employee.section else ''
    unit_name = employee.unit.name if employee.unit else ''
    
    # Convert shift times to datetime objects for easier calculation
    shift_date = shift.date
    start_datetime = datetime.combine(shift_date, shift.start_time)
    end_datetime = datetime.combine(shift_date, shift.end_time)
    
    # Handle shifts that cross midnight
    if end_datetime <= start_datetime:
        end_datetime += timedelta(days=1)
    
    # Get employee-specific night differential hours
    nd_start_hour = employee.night_differential_start_hour
    nd_end_hour = employee.night_differential_end_hour
    
    # Calculate standard work hours based on schedule format
    standard_hours = 8 if employee.schedule_format == ScheduleFormat.EIGHT_HOUR else 9
    
    # Calculate total shift duration
    total_shift_hours = (end_datetime - start_datetime).total_seconds() / 3600
    
    # Check if shift crosses into ANY holiday dates
    shift_crosses_holiday = False
    current_check_date = start_datetime.date()
    end_check_date = end_datetime.date()
    
    # Check all dates that the shift spans
    while current_check_date <= end_check_date:
        if current_check_date in holiday_dates:
            shift_crosses_holiday = True
            break
        current_check_date += timedelta(days=1)
    
    # 1. Process Holiday Duty first (takes priority over EVERYTHING)
    holiday_entries = []
    if shift.status == ShiftStatus.HOLIDAY_OFF or shift_crosses_holiday:
        holiday_entries = calculate_holiday_hours(
            start_datetime, end_datetime, shift_date, holiday_dates,
            export_start_date, export_end_date,
            surname, employee_name, personnel_number, section_name, unit_name
        )
        entries.extend(holiday_entries)
    
    # 2. Calculate Overtime (excluding holiday periods)
    ot_entries = []
    if shift.status != ShiftStatus.HOLIDAY_OFF and total_shift_hours > standard_hours:
        # Calculate overtime start time
        ot_start_datetime = start_datetime + timedelta(hours=standard_hours)
        
        # If shift extends beyond standard hours
        if ot_start_datetime < end_datetime:
            ot_entries = calculate_overtime_excluding_holidays(
                ot_start_datetime, end_datetime, holiday_entries,
                surname, employee_name, personnel_number, section_name, unit_name
            )
            entries.extend(ot_entries)
    
    # 3. Calculate Night Differential (excluding holiday AND overtime hours)
    nd_entries = calculate_night_differential_excluding_ot_and_holiday(
        start_datetime, end_datetime, nd_start_hour, nd_end_hour,
        holiday_entries, ot_entries, surname, employee_name, personnel_number, 
        section_name, unit_name
    )
    entries.extend(nd_entries)
    
    return entries


def calculate_holiday_hours(start_datetime, end_datetime, shift_date, holiday_dates, 
                          export_start_date, export_end_date,
                          surname, employee_name, personnel_number, section_name, unit_name):
    """Calculate holiday hours with cross-midnight and range logic"""
    entries = []
    current_datetime = start_datetime
    
    while current_datetime < end_datetime:
        current_date = current_datetime.date()
        
        if (current_date in holiday_dates and 
            export_start_date <= current_date <= export_end_date):
            
            # Find the end of holiday period - use midnight (00:00) of next day
            end_of_day = datetime.combine(current_date + timedelta(days=1), time(0, 0))
            holiday_end = min(end_datetime, end_of_day)
            
            holiday_hours = (holiday_end - current_datetime).total_seconds() / 3600
            
            if holiday_hours > 0:
                entries.append({
                    'SURNAME': surname,
                    'EMPLOYEE NAME': employee_name,
                    'TYPE': 'OT',
                    'PERSONNEL NUMBER': personnel_number,
                    'TYPE CODE': '801',
                    'START TIME': current_datetime.strftime('%H:%M'),
                    'END TIME': holiday_end.strftime('%H:%M'),
                    'START DATE': current_datetime.strftime('%m/%d/%Y'),
                    'END DATE': holiday_end.strftime('%m/%d/%Y'),
                    'TOTAL HOURS': f"{holiday_hours:.2f}",
                    'REASON/REMARKS': 'OT HOLIDAY',
                    'SECTION': section_name,
                    'UNIT': unit_name
                })
            
            current_datetime = holiday_end
        else:
            # Move to next day if current day is not a claimable holiday
            next_day = datetime.combine(current_date + timedelta(days=1), time(0, 0))
            current_datetime = min(next_day, end_datetime)
    
    return entries


def calculate_overtime_excluding_holidays(ot_start_datetime, end_datetime, holiday_entries,
                                        surname, employee_name, personnel_number, section_name, unit_name):
    """Calculate overtime hours excluding holiday periods"""
    entries = []
    
    # Create set of holiday time periods to exclude
    holiday_periods = []
    for holiday_entry in holiday_entries:
        holiday_start = datetime.strptime(f"{holiday_entry['START DATE']} {holiday_entry['START TIME']}", '%m/%d/%Y %H:%M')
        holiday_end = datetime.strptime(f"{holiday_entry['END DATE']} {holiday_entry['END TIME']}", '%m/%d/%Y %H:%M')
        holiday_periods.append((holiday_start, holiday_end))
    
    # Start with the full OT period
    ot_segments = [(ot_start_datetime, end_datetime)]
    
    # Remove holiday periods from OT calculation
    for holiday_start, holiday_end in holiday_periods:
        new_segments = []
        for seg_start, seg_end in ot_segments:
            # If holiday overlaps with OT segment
            if holiday_start < seg_end and holiday_end > seg_start:
                # Add segment before holiday (if any)
                if seg_start < holiday_start:
                    new_segments.append((seg_start, min(seg_end, holiday_start)))
                # Add segment after holiday (if any)
                if seg_end > holiday_end:
                    new_segments.append((max(seg_start, holiday_end), seg_end))
            else:
                # No overlap, keep segment
                new_segments.append((seg_start, seg_end))
        ot_segments = new_segments
    
    # Create OT entries for remaining segments
    for seg_start, seg_end in ot_segments:
        ot_hours = (seg_end - seg_start).total_seconds() / 3600
        if ot_hours > 0:
            entries.append({
                'SURNAME': surname,
                'EMPLOYEE NAME': employee_name,
                'TYPE': 'OT',
                'PERSONNEL NUMBER': personnel_number,
                'TYPE CODE': '801',
                'START TIME': seg_start.strftime('%H:%M'),
                'END TIME': seg_end.strftime('%H:%M'),
                'START DATE': seg_start.strftime('%m/%d/%Y'),
                'END DATE': seg_end.strftime('%m/%d/%Y'),
                'TOTAL HOURS': f"{ot_hours:.2f}",
                'REASON/REMARKS': 'OT PEAKLOAD',
                'SECTION': section_name,
                'UNIT': unit_name
            })
    
    return entries


def calculate_night_differential_excluding_ot_and_holiday(start_datetime, end_datetime, nd_start_hour, nd_end_hour,
                                                        holiday_entries, ot_entries, surname, employee_name, personnel_number,
                                                        section_name, unit_name):
    """Calculate night differential hours excluding BOTH holiday AND overtime periods"""
    entries = []
    
    # Create set of holiday time periods to exclude
    holiday_periods = []
    for holiday_entry in holiday_entries:
        holiday_start = datetime.strptime(f"{holiday_entry['START DATE']} {holiday_entry['START TIME']}", '%m/%d/%Y %H:%M')
        holiday_end = datetime.strptime(f"{holiday_entry['END DATE']} {holiday_entry['END TIME']}", '%m/%d/%Y %H:%M')
        holiday_periods.append((holiday_start, holiday_end))
    
    # Create set of OT time periods to exclude
    ot_periods = []
    for ot_entry in ot_entries:
        ot_start = datetime.strptime(f"{ot_entry['START DATE']} {ot_entry['START TIME']}", '%m/%d/%Y %H:%M')
        ot_end = datetime.strptime(f"{ot_entry['END DATE']} {ot_entry['END TIME']}", '%m/%d/%Y %H:%M')
        ot_periods.append((ot_start, ot_end))
    
    # FIXED: Process ND for all days that the shift spans, including previous day ND periods
    current_datetime = start_datetime
    shift_start_date = start_datetime.date()
    shift_end_date = end_datetime.date()
    
    # Check ND periods that could overlap with this shift
    # We need to check the day before shift starts (for ND periods ending at 6AM)
    # and the day the shift starts (for ND periods starting at 8PM/10PM)
    check_dates = []
    
    # Add the day before shift start date (to catch ND periods ending at 6AM)
    check_dates.append(shift_start_date - timedelta(days=1))
    
    # Add all dates that the shift spans
    current_check_date = shift_start_date
    while current_check_date <= shift_end_date:
        check_dates.append(current_check_date)
        current_check_date += timedelta(days=1)
    
    # Process each potential ND period
    for check_date in check_dates:
        # Define ND period for this date (8PM/10PM to 6AM next day)
        nd_start = datetime.combine(check_date, time(nd_start_hour, 0))
        nd_end = datetime.combine(check_date + timedelta(days=1), time(nd_end_hour, 0))
        
        # Find intersection of shift time and ND period
        nd_period_start = max(start_datetime, nd_start)
        nd_period_end = min(end_datetime, nd_end)
        
        if nd_period_start < nd_period_end:
            # Start with the ND period that intersects with the shift
            nd_segments = [(nd_period_start, nd_period_end)]
            
            # Remove holiday periods from ND calculation
            for holiday_start, holiday_end in holiday_periods:
                new_segments = []
                for seg_start, seg_end in nd_segments:
                    if holiday_start < seg_end and holiday_end > seg_start:
                        if seg_start < holiday_start:
                            new_segments.append((seg_start, min(seg_end, holiday_start)))
                        if seg_end > holiday_end:
                            new_segments.append((max(seg_start, holiday_end), seg_end))
                    else:
                        new_segments.append((seg_start, seg_end))
                nd_segments = new_segments
            
            # Remove OT periods from ND calculation
            for ot_start, ot_end in ot_periods:
                new_segments = []
                for seg_start, seg_end in nd_segments:
                    if ot_start < seg_end and ot_end > seg_start:
                        if seg_start < ot_start:
                            new_segments.append((seg_start, min(seg_end, ot_start)))
                        if seg_end > ot_end:
                            new_segments.append((max(seg_start, ot_end), seg_end))
                    else:
                        new_segments.append((seg_start, seg_end))
                nd_segments = new_segments
            
            # Create ND entries for remaining segments
            for seg_start, seg_end in nd_segments:
                nd_hours = (seg_end - seg_start).total_seconds() / 3600
                if nd_hours > 0:
                    entries.append({
                        'SURNAME': surname,
                        'EMPLOYEE NAME': employee_name,
                        'TYPE': 'ND',
                        'PERSONNEL NUMBER': personnel_number,
                        'TYPE CODE': '803',
                        'START TIME': seg_start.strftime('%H:%M'),
                        'END TIME': seg_end.strftime('%H:%M'),
                        'START DATE': seg_start.strftime('%m/%d/%Y'),
                        'END DATE': seg_end.strftime('%m/%d/%Y'),
                        'TOTAL HOURS': f"{nd_hours:.2f}",
                        'REASON/REMARKS': 'ND',
                        'SECTION': section_name,
                        'UNIT': unit_name
                    })
    
    return entries


def filter_otnd_entries_by_export_range(otnd_entries, export_start_date, export_end_date):
    """Filter OTND entries to only include those relevant to export range"""
    filtered_entries = []
    
    for entry in otnd_entries:
        entry_start_date = datetime.strptime(entry['START DATE'], '%m/%d/%Y').date()
        
        if entry['TYPE'] == 'OT' and 'HOLIDAY' in entry['REASON/REMARKS']:
            # Holiday entries: only include if holiday date is within export range
            if export_start_date <= entry_start_date <= export_end_date:
                filtered_entries.append(entry)
        else:
            # OT and ND entries: include if shift date is within original export range
            # This prevents including OT/ND from the extended query date
            if export_start_date <= entry_start_date <= export_end_date:
                filtered_entries.append(entry)
    
    return filtered_entries

# Add this to the END of your app/schedule/routes.py file

@bp.route('/calendar')
@login_required
def calendar_view():
    """Calendar view for schedule visualization - Managers and Admins only"""
    if not current_user.can_edit_schedule():
        flash('You do not have permission to access the calendar view.', 'danger')
        return redirect(url_for('schedule.view_schedule'))
    
    # Get date from request or default to current month
    date_str = request.args.get('date', date.today().isoformat())
    selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    
    # Get the first and last day of the month
    first_day = selected_date.replace(day=1)
    last_day = date(selected_date.year, selected_date.month, calendar.monthrange(selected_date.year, selected_date.month)[1])
    
    # Get calendar start and end (including previous/next month days for full calendar grid)
    calendar_start = first_day - timedelta(days=first_day.weekday())
    calendar_end = last_day + timedelta(days=(6 - last_day.weekday()))
    
    # Get team members based on user role and permissions
    if current_user.section_id:
        team_members = User.query.filter_by(section_id=current_user.section_id, is_active=True).all()
    elif current_user.unit_id:
        team_members = User.query.filter_by(unit_id=current_user.unit_id, is_active=True).all()
    else:
        team_members = User.query.filter_by(is_active=True).all()
    
    # Get all shifts for the calendar period
    shifts = Shift.query.filter(
        Shift.date.between(calendar_start, calendar_end),
        Shift.employee_id.in_([tm.id for tm in team_members])
    ).order_by(Shift.employee_id, Shift.date, Shift.sequence).all()
    
    # Get date remarks for the calendar period
    date_remarks = DateRemark.query.filter(
        DateRemark.date.between(calendar_start, calendar_end)
    ).all()
    
    # Convert shifts to JSON-serializable format
    def shift_to_dict(shift):
        return {
            'id': shift.id,
            'employee_id': shift.employee_id,
            'date': shift.date.isoformat(),
            'start_time': shift.start_time.strftime('%H:%M') if shift.start_time else None,
            'end_time': shift.end_time.strftime('%H:%M') if shift.end_time else None,
            'role': shift.role,
            'status': shift.status.value,
            'notes': shift.notes,
            'color': shift.color or shift.status_color,
            'work_arrangement': shift.work_arrangement.value if shift.work_arrangement else 'onsite',
            'sequence': shift.sequence,
            'time_display': shift.time_display
        }
    
    # Organize data by date
    shifts_by_date = {}
    shifts_by_date_serializable = {}
    
    for shift in shifts:
        shift_date = shift.date.isoformat()
        if shift_date not in shifts_by_date:
            shifts_by_date[shift_date] = []
            shifts_by_date_serializable[shift_date] = []
        shifts_by_date[shift_date].append(shift)
        shifts_by_date_serializable[shift_date].append(shift_to_dict(shift))
    
    # Organize remarks by date
    remarks_by_date = {}
    remarks_by_date_serializable = {}
    
    for remark in date_remarks:
        remark_date = remark.date.isoformat()
        remarks_by_date[remark_date] = remark
        remarks_by_date_serializable[remark_date] = remark.to_dict()
    
    # Create calendar grid (6 weeks x 7 days = 42 days)
    calendar_weeks = []
    current_date = calendar_start
    
    for week in range(6):
        week_days = []
        for day in range(7):
            day_info = {
                'date': current_date,
                'is_current_month': current_date.month == selected_date.month,
                'is_today': current_date == date.today(),
                'shifts': shifts_by_date.get(current_date.isoformat(), []),
                'remark': remarks_by_date.get(current_date.isoformat()),
                'shift_count': len(shifts_by_date.get(current_date.isoformat(), [])),
                'employee_count': len(set(shift.employee_id for shift in shifts_by_date.get(current_date.isoformat(), [])))
            }
            week_days.append(day_info)
            current_date += timedelta(days=1)
        calendar_weeks.append(week_days)
    
    # Calculate summary statistics
    month_shifts = [shift for shift in shifts if shift.date.month == selected_date.month]
    stats = {
        'total_shifts': len(month_shifts),
        'total_employees': len(set(shift.employee_id for shift in month_shifts)),
        'scheduled_shifts': len([s for s in month_shifts if s.status == ShiftStatus.SCHEDULED]),
        'leave_shifts': len([s for s in month_shifts if 'leave' in s.status.value or s.status == ShiftStatus.REST_DAY])
    }
    
    return render_template('schedule/calendar.html',
                         calendar_weeks=calendar_weeks,
                         selected_date=selected_date,
                         first_day=first_day,
                         last_day=last_day,
                         team_members=team_members,
                         stats=stats,
                         shifts_by_date_serializable=shifts_by_date_serializable,
                         remarks_by_date_serializable=remarks_by_date_serializable)

# ----------BLANK TEMPLATE

@bp.route('/api/templates/create-blank', methods=['POST'])
@login_required
def create_blank_template():
    """Create a BLANK template for clearing schedules"""
    try:
        if not current_user.can_edit_schedule():
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # Validate required fields
        name = data.get('name', '').strip()
        if not name or len(name) < 3:
            return jsonify({
                'success': False, 
                'error': 'Template name must be at least 3 characters long'
            }), 400
        
        if len(name) > 100:
            return jsonify({
                'success': False, 
                'error': 'Template name cannot exceed 100 characters'
            }), 400
        
        # Check for duplicate template names
        existing_template = ScheduleTemplateV2.query.filter_by(
            name=name,
            created_by_id=current_user.id
        ).first()
        
        if existing_template:
            return jsonify({
                'success': False, 
                'error': f'You already have a template named "{name}". Please choose a different name.'
            }), 400
        
        # Validate duration
        duration_days = data.get('duration_days', 7)
        try:
            duration_days = int(duration_days)
            if duration_days < 1 or duration_days > 14:
                return jsonify({
                    'success': False, 
                    'error': 'Duration must be between 1 and 14 days'
                }), 400
        except (ValueError, TypeError):
            return jsonify({
                'success': False, 
                'error': 'Invalid duration format'
            }), 400
        
        # SECURITY: Restrict scope to user's organizational boundaries
        section_id = None
        unit_id = None
        department_id = None
        division_id = None
        
        scope_type = data.get('scope_type')
        scope_id = data.get('scope_id')
        
        # Handle scope selection with security validation
        if scope_type and scope_id:
            try:
                scope_id = int(scope_id)
                
                if scope_type == 'section':
                    # User can only create BLANK templates for their own section or if admin
                    if not current_user.can_admin() and current_user.section_id != scope_id:
                        return jsonify({
                            'success': False, 
                            'error': 'You can only create BLANK templates for your own section'
                        }), 403
                    section_id = scope_id
                    
                elif scope_type == 'unit':
                    # User can only create BLANK templates for their own unit or if admin
                    if not current_user.can_admin() and current_user.unit_id != scope_id:
                        return jsonify({
                            'success': False, 
                            'error': 'You can only create BLANK templates for your own unit'
                        }), 403
                    unit_id = scope_id
                    
                else:
                    return jsonify({
                        'success': False, 
                        'error': f'Invalid scope type for BLANK templates: {scope_type}. Only section or unit allowed.'
                    }), 400
                    
            except (ValueError, TypeError):
                return jsonify({
                    'success': False, 
                    'error': 'Invalid scope ID'
                }), 400
        else:
            # Use current user's scope as default (section takes priority)
            if current_user.section_id:
                section_id = current_user.section_id
            elif current_user.unit_id:
                unit_id = current_user.unit_id
            else:
                return jsonify({
                    'success': False, 
                    'error': 'You must belong to a section or unit to create BLANK templates'
                }), 403
        
        # Validate that exactly one scope is provided (section OR unit, not both)
        scope_count = sum([1 for x in [section_id, unit_id] if x is not None])
        if scope_count != 1:
            return jsonify({
                'success': False, 
                'error': 'BLANK templates require exactly one organizational scope (section OR unit)'
            }), 400
        
        # Create BLANK template
        try:
            template = ScheduleTemplateV2.create_blank_template(
                user=current_user,
                name=name,
                description=data.get('description', '').strip(),
                duration_days=duration_days,
                section_id=section_id,
                unit_id=unit_id,
                department_id=None,  # Not allowed for BLANK templates
                division_id=None,    # Not allowed for BLANK templates
                is_public=data.get('is_public', False)
            )
            
            db.session.add(template)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'BLANK template "{template.name}" created successfully! This template will clear all shifts in a {duration_days}-day range.',
                'template': template.to_dict(),
                'template_info': {
                    'type': 'BLANK',
                    'duration_days': duration_days,
                    'scope': template.scope_display,
                    'purpose': 'Clear existing schedules'
                }
            })
            
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False, 
                'error': f'BLANK template creation failed: {str(e)}'
            }), 500
            
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False, 
            'error': f'Unexpected error creating BLANK template: {str(e)}'
        }), 500


@bp.route('/api/templates/<int:template_id>/apply-blank', methods=['POST'])
@login_required
def apply_blank_template(template_id):
    """Apply BLANK template to clear schedules"""
    try:
        if not current_user.can_edit_schedule():
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        template = ScheduleTemplateV2.query.get(template_id)
        if not template:
            return jsonify({'success': False, 'error': 'Template not found'}), 404
        
        if template.template_type != TemplateType.BLANK:
            return jsonify({'success': False, 'error': 'This is not a BLANK template'}), 400
        
        if not template.can_user_access(current_user):
            return jsonify({'success': False, 'error': 'Access denied to this template'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # Parse and validate target dates
        try:
            target_start = datetime.strptime(data['target_start_date'], '%Y-%m-%d').date()
            target_end = datetime.strptime(data['target_end_date'], '%Y-%m-%d').date()
        except (ValueError, KeyError) as e:
            return jsonify({
                'success': False, 
                'error': f'Invalid target date format: {str(e)}'
            }), 400
        
        # Validate date range
        if target_start > target_end:
            return jsonify({
                'success': False, 
                'error': 'Target start date must be before or equal to target end date'
            }), 400
        
        target_duration = (target_end - target_start).days + 1
        template_duration = template.template_data.get('duration_days', 7)
        
        if target_duration != template_duration:
            return jsonify({
                'success': False, 
                'error': f'Target date range ({target_duration} days) must match template duration ({template_duration} days)'
            }), 400
        
        # Get application options
        target_section_id = data.get('target_section_id')
        target_unit_id = data.get('target_unit_id')
        clear_all_types = data.get('clear_all_types', True)
        preserve_leave_types = data.get('preserve_leave_types', [])
        
        # Convert preserve_leave_types to enum values if provided
        preserve_enum_types = []
        if preserve_leave_types:
            try:
                preserve_enum_types = [ShiftStatus(status) for status in preserve_leave_types]
            except ValueError as e:
                return jsonify({
                    'success': False, 
                    'error': f'Invalid preserve leave type: {str(e)}'
                }), 400
        
        # SECURITY: Validate organizational scope restrictions
        if target_section_id:
            try:
                target_section_id = int(target_section_id)
                
                # User can only clear shifts in their own section unless admin
                if not current_user.can_admin() and current_user.section_id != target_section_id:
                    return jsonify({
                        'success': False, 
                        'error': 'You can only clear shifts in your own section'
                    }), 403
                    
                target_section = Section.query.get(target_section_id)
                if not target_section:
                    return jsonify({
                        'success': False, 
                        'error': f'Target section ID {target_section_id} not found'
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'success': False, 
                    'error': 'Invalid target section ID'
                }), 400
        
        if target_unit_id:
            try:
                target_unit_id = int(target_unit_id)
                
                # User can only clear shifts in their own unit unless admin
                if not current_user.can_admin() and current_user.unit_id != target_unit_id:
                    return jsonify({
                        'success': False, 
                        'error': 'You can only clear shifts in your own unit'
                    }), 403
                    
                target_unit = Unit.query.get(target_unit_id)
                if not target_unit:
                    return jsonify({
                        'success': False, 
                        'error': f'Target unit ID {target_unit_id} not found'
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'success': False, 
                    'error': 'Invalid target unit ID'
                }), 400
        
        # If no target scope specified, use user's own scope
        if not target_section_id and not target_unit_id:
            if current_user.section_id:
                target_section_id = current_user.section_id
            elif current_user.unit_id:
                target_unit_id = current_user.unit_id
            else:
                return jsonify({
                    'success': False, 
                    'error': 'You must belong to a section or unit to apply BLANK templates'
                }), 403
        
        # Get preview of what will be deleted - SECURITY: Only user's scope
        if target_section_id:
            # Validate user can access this section
            if not current_user.can_admin() and current_user.section_id != target_section_id:
                return jsonify({
                    'success': False, 
                    'error': 'Access denied to this section'
                }), 403
            target_employees = User.query.filter_by(section_id=target_section_id, is_active=True).all()
            
        elif target_unit_id:
            # Validate user can access this unit
            if not current_user.can_admin() and current_user.unit_id != target_unit_id:
                return jsonify({
                    'success': False, 
                    'error': 'Access denied to this unit'
                }), 403
            target_employees = User.query.filter_by(unit_id=target_unit_id, is_active=True).all()
            
        elif template.section_id:
            # Validate user can access template's section
            if not current_user.can_admin() and current_user.section_id != template.section_id:
                return jsonify({
                    'success': False, 
                    'error': 'Access denied to template\'s section'
                }), 403
            target_employees = User.query.filter_by(section_id=template.section_id, is_active=True).all()
            
        elif template.unit_id:
            # Validate user can access template's unit
            if not current_user.can_admin() and current_user.unit_id != template.unit_id:
                return jsonify({
                    'success': False, 
                    'error': 'Access denied to template\'s unit'
                }), 403
            target_employees = User.query.filter_by(unit_id=template.unit_id, is_active=True).all()
            
        else:
            return jsonify({
                'success': False, 
                'error': 'No valid organizational scope found for this template'
            }), 400
        
        if not target_employees:
            return jsonify({
                'success': False, 
                'error': 'No active employees found in target scope'
            }), 400
        
        # Apply the BLANK template
        try:
            result = template.apply_blank_template(
                start_date=target_start,
                end_date=target_end,
                user=current_user,
                target_section_id=target_section_id,
                target_unit_id=target_unit_id,
                clear_all_types=clear_all_types,
                preserve_leave_types=preserve_enum_types
            )
            
            db.session.commit()
            
            # Create success message
            success_message = f'BLANK template applied successfully! Cleared {result["deleted_shifts"]} shifts affecting {result["affected_employees"]} employees.'
            if result['preserved_shifts'] > 0:
                success_message += f' {result["preserved_shifts"]} shifts were preserved.'
            
            return jsonify({
                'success': True,
                'message': success_message,
                'result': result
            })
            
        except ValueError as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False, 
                'error': f'BLANK template application failed: {str(e)}'
            }), 500
            
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False, 
            'error': f'Unexpected error applying BLANK template: {str(e)}'
        }), 500


@bp.route('/api/templates/<int:template_id>/preview-blank', methods=['POST'])
@login_required
def preview_blank_template(template_id):
    """Preview what a BLANK template application would do"""
    try:
        template = ScheduleTemplateV2.query.get(template_id)
        if not template:
            return jsonify({'success': False, 'error': 'Template not found'}), 404
        
        if template.template_type != TemplateType.BLANK:
            return jsonify({'success': False, 'error': 'This is not a BLANK template'}), 400
        
        if not template.can_user_access(current_user):
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # Parse target dates
        try:
            target_start = datetime.strptime(data['target_start_date'], '%Y-%m-%d').date()
            target_end = datetime.strptime(data['target_end_date'], '%Y-%m-%d').date()
        except (ValueError, KeyError):
            return jsonify({'success': False, 'error': 'Invalid date format'}), 400
        
        # Get target employees
        target_section_id = data.get('target_section_id')
        target_unit_id = data.get('target_unit_id')
        clear_all_types = data.get('clear_all_types', True)
        preserve_leave_types = data.get('preserve_leave_types', [])
        
        if target_section_id:
            target_employees = User.query.filter_by(section_id=target_section_id, is_active=True).all()
        elif target_unit_id:
            target_employees = User.query.filter_by(unit_id=target_unit_id, is_active=True).all()
        else:
            return jsonify({'success': False, 'error': 'No target scope specified'}), 400
        
        if not target_employees:
            return jsonify({'success': False, 'error': 'No employees found in target scope'}), 400
        
        # Find existing shifts that would be affected
        preserve_enum_types = []
        if preserve_leave_types:
            try:
                preserve_enum_types = [ShiftStatus(status) for status in preserve_leave_types]
            except ValueError:
                preserve_enum_types = []
        
        # Get all shifts in date range
        all_shifts = Shift.query.filter(
            Shift.date.between(target_start, target_end),
            Shift.employee_id.in_([emp.id for emp in target_employees])
        ).all()
        
        # Categorize shifts
        shifts_to_delete = []
        shifts_to_preserve = []
        
        for shift in all_shifts:
            if not clear_all_types and shift.status in preserve_enum_types:
                shifts_to_preserve.append(shift)
            else:
                shifts_to_delete.append(shift)
        
        # Count by type
        delete_by_type = {}
        preserve_by_type = {}
        
        for shift in shifts_to_delete:
            shift_type = shift.status.value
            delete_by_type[shift_type] = delete_by_type.get(shift_type, 0) + 1
        
        for shift in shifts_to_preserve:
            shift_type = shift.status.value
            preserve_by_type[shift_type] = preserve_by_type.get(shift_type, 0) + 1
        
        target_duration = (target_end - target_start).days + 1
        template_duration = template.template_data.get('duration_days', 7)
        
        preview_data = {
            'target_employees': [
                {
                    'id': emp.id, 
                    'name': emp.full_name, 
                    'role': emp.job_title
                } for emp in target_employees
            ],
            'date_range': f"{target_start.strftime('%Y-%m-%d')} to {target_end.strftime('%Y-%m-%d')}",
            'duration_match': target_duration == template_duration,
            'duration_info': {
                'target_days': target_duration,
                'template_days': template_duration,
                'difference': target_duration - template_duration
            },
            'shifts_to_delete': len(shifts_to_delete),
            'shifts_to_preserve': len(shifts_to_preserve),
            'total_existing_shifts': len(all_shifts),
            'affected_employees': len(target_employees),
            'delete_by_type': delete_by_type,
            'preserve_by_type': preserve_by_type,
            'clear_all_types': clear_all_types,
            'preserve_leave_types': preserve_leave_types,
            'action_summary': f"Will clear {len(shifts_to_delete)} shifts and preserve {len(shifts_to_preserve)} shifts"
        }
        
        return jsonify({
            'success': True,
            'preview': preview_data
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'Error generating preview: {str(e)}'
        }), 500

# ----------TEMPLATE APPLICATION ---------

@bp.route('/api/templates')
@login_required
def get_templates():
    """Get available schedule templates for current user"""
    try:
        # Get templates user can access
        templates_query = ScheduleTemplateV2.query.filter(
            db.or_(
                ScheduleTemplateV2.created_by_id == current_user.id,
                ScheduleTemplateV2.is_public == True
            )
        )
        
        # Filter by organizational scope if not admin
        if not current_user.can_admin():
            org_filter = []
            if current_user.department_id:
                org_filter.append(ScheduleTemplateV2.department_id == current_user.department_id)
            if current_user.division_id:
                org_filter.append(ScheduleTemplateV2.division_id == current_user.division_id)
            if current_user.section_id:
                org_filter.append(ScheduleTemplateV2.section_id == current_user.section_id)
            if current_user.unit_id:
                org_filter.append(ScheduleTemplateV2.unit_id == current_user.unit_id)
            
            if org_filter:
                templates_query = templates_query.filter(db.or_(*org_filter))
        
        templates = templates_query.order_by(
            ScheduleTemplateV2.last_used_at.desc().nullslast(),
            ScheduleTemplateV2.created_at.desc()
        ).all()
        
        # Enhanced template data with delete permissions
        templates_data = []
        for template in templates:
            template_dict = template.to_dict()
            
            # IMPORTANT: Add delete permission check
            can_delete = (current_user.can_admin() or 
                         template.created_by_id == current_user.id)
            template_dict['can_delete'] = can_delete
            
            templates_data.append(template_dict)
        
        return jsonify({
            'success': True,
            'templates': templates_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error loading templates: {str(e)}'}), 500

@bp.route('/api/templates/create-snapshot', methods=['POST'])
@login_required
def create_template_snapshot():
    """FIXED: Create template from current schedule snapshot with better validation"""
    try:
        if not current_user.can_edit_schedule():
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        data = request.get_json()
        
        # FIXED: Enhanced validation with specific error messages
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        required_fields = ['name', 'start_date', 'end_date']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            return jsonify({
                'success': False, 
                'error': f'Missing required fields: {", ".join(missing_fields)}'
            }), 400
        
        # FIXED: Parse and validate dates with better error handling
        try:
            start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        except ValueError as e:
            return jsonify({
                'success': False, 
                'error': f'Invalid date format. Use YYYY-MM-DD: {str(e)}'
            }), 400
        
        # FIXED: Enhanced date range validation
        if start_date > end_date:
            return jsonify({
                'success': False, 
                'error': 'Start date must be before or equal to end date'
            }), 400
        
        duration = (end_date - start_date).days + 1
        if duration > 14:
            return jsonify({
                'success': False, 
                'error': f'Template duration cannot exceed 14 days. Requested: {duration} days'
            }), 400
        
        if duration < 1:
            return jsonify({
                'success': False, 
                'error': 'Template must span at least 1 day'
            }), 400
        
        # FIXED: Validate template name
        name = data['name'].strip()
        if len(name) < 3:
            return jsonify({
                'success': False, 
                'error': 'Template name must be at least 3 characters long'
            }), 400
        
        if len(name) > 100:
            return jsonify({
                'success': False, 
                'error': 'Template name cannot exceed 100 characters'
            }), 400
        
        # Check for duplicate template names
        existing_template = ScheduleTemplateV2.query.filter_by(
            name=name,
            created_by_id=current_user.id
        ).first()
        
        if existing_template:
            return jsonify({
                'success': False, 
                'error': f'You already have a template named "{name}". Please choose a different name.'
            }), 400
        
        # Determine organizational scope with validation
        section_id = data.get('section_id')
        unit_id = data.get('unit_id')
        department_id = data.get('department_id')
        division_id = data.get('division_id')
        scope_type = data.get('scope_type')
        scope_id = data.get('scope_id')
        
        # FIXED: Better scope validation and assignment
        if scope_type and scope_id:
            try:
                scope_id = int(scope_id)
                if scope_type == 'section':
                    section_id = scope_id
                elif scope_type == 'unit':
                    unit_id = scope_id
                elif scope_type == 'department':
                    department_id = scope_id
                elif scope_type == 'division':
                    division_id = scope_id
                else:
                    return jsonify({
                        'success': False, 
                        'error': f'Invalid scope type: {scope_type}'
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'success': False, 
                    'error': 'Invalid scope ID - must be a number'
                }), 400
        else:
            # Use current user's scope if not specified
            section_id = section_id or current_user.section_id
            unit_id = unit_id or current_user.unit_id
            department_id = department_id or current_user.department_id
            division_id = division_id or current_user.division_id
        
        # FIXED: Validate that at least one organizational scope is provided
        if not any([section_id, unit_id, department_id, division_id]):
            return jsonify({
                'success': False, 
                'error': 'No organizational scope specified. Please select a department, division, section, or unit.'
            }), 400
        
        # Determine template type
        template_type = TemplateType.WEEKLY if duration == 7 else TemplateType.CUSTOM
        
        # FIXED: Pre-check if there are any shifts in the date range
        preview_query = Shift.query.filter(
            Shift.date.between(start_date, end_date)
        )
        
        # Apply organizational filter for preview
        if section_id:
            preview_employees = User.query.filter_by(section_id=section_id, is_active=True).all()
        elif unit_id:
            preview_employees = User.query.filter_by(unit_id=unit_id, is_active=True).all()
        elif department_id:
            preview_employees = User.query.filter_by(department_id=department_id, is_active=True).all()
        elif division_id:
            preview_employees = User.query.filter_by(division_id=division_id, is_active=True).all()
        else:
            return jsonify({
                'success': False, 
                'error': 'Unable to determine organizational scope'
            }), 400
        
        if not preview_employees:
            return jsonify({
                'success': False, 
                'error': 'No active employees found in the specified organizational scope'
            }), 400
        
        # Check for shifts in the date range
        shift_count = preview_query.filter(
            Shift.employee_id.in_([emp.id for emp in preview_employees])
        ).count()
        
        if shift_count == 0:
            return jsonify({
                'success': False, 
                'error': f'No shifts found in the date range {start_date} to {end_date} for the selected organizational scope'
            }), 400
        
        # FIXED: Create template with enhanced error handling
        try:
            template = ScheduleTemplateV2.create_from_schedule(
                user=current_user,
                name=name,
                description=data.get('description', '').strip(),
                start_date=start_date,
                end_date=end_date,
                section_id=section_id,
                unit_id=unit_id,
                department_id=department_id,
                division_id=division_id,
                is_public=data.get('is_public', False),
                template_type=template_type
            )
            
            # FIXED: Validate template was created properly
            if not template.template_data or not template.template_data.get('shifts'):
                return jsonify({
                    'success': False, 
                    'error': 'Template creation failed - no shifts captured'
                }), 500
            
            db.session.add(template)
            db.session.commit()
            
            # FIXED: Return enhanced response with validation info
            return jsonify({
                'success': True,
                'message': f'Template "{template.name}" created successfully with {template.total_shifts} shifts from {template.total_employees} employees!',
                'template': template.to_dict(),
                'validation': {
                    'shifts_captured': len(template.template_data['shifts']),
                    'employees_captured': len(template.template_data['employees']),
                    'date_range': f"{start_date} to {end_date}",
                    'duration_days': duration,
                    'has_metadata': 'metadata' in template.template_data
                }
            })
            
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False, 
                'error': f'Template creation failed: {str(e)}'
            }), 500
            
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False, 
            'error': f'Unexpected error creating template: {str(e)}'
        }), 500

@bp.route('/api/templates/<int:template_id>/apply', methods=['POST'])
@login_required
def apply_template(template_id):
    """FIXED: Apply template to new date range with comprehensive validation"""
    try:
        if not current_user.can_edit_schedule():
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        template = ScheduleTemplateV2.query.get(template_id)
        if not template:
            return jsonify({'success': False, 'error': 'Template not found'}), 404
        
        if not template.can_user_access(current_user):
            return jsonify({'success': False, 'error': 'Access denied to this template'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # FIXED: Enhanced validation for target dates
        try:
            target_start = datetime.strptime(data['target_start_date'], '%Y-%m-%d').date()
            target_end = datetime.strptime(data['target_end_date'], '%Y-%m-%d').date()
        except (ValueError, KeyError) as e:
            return jsonify({
                'success': False, 
                'error': f'Invalid target date format. Use YYYY-MM-DD: {str(e)}'
            }), 400
        
        # FIXED: Validate date range
        if target_start > target_end:
            return jsonify({
                'success': False, 
                'error': 'Target start date must be before or equal to target end date'
            }), 400
        
        target_duration = (target_end - target_start).days + 1
        template_duration = template.duration_days
        
        if target_duration != template_duration:
            return jsonify({
                'success': False, 
                'error': f'Target date range ({target_duration} days) must match template duration ({template_duration} days)'
            }), 400
        
        # FIXED: Validate template data integrity
        if not template.template_data or 'shifts' not in template.template_data:
            return jsonify({
                'success': False, 
                'error': 'Template data is corrupted or missing'
            }), 500
        
        if not template.template_data.get('employees'):
            return jsonify({
                'success': False, 
                'error': 'Template contains no employee data'
            }), 500
        
        # Get target organizational scope
        target_section_id = data.get('target_section_id')
        target_unit_id = data.get('target_unit_id')
        replace_existing = data.get('replace_existing', False)
        employee_mapping_overrides = data.get('employee_mappings')
        
        # FIXED: Validate organizational scope
        if target_section_id:
            try:
                target_section_id = int(target_section_id)
                target_section = Section.query.get(target_section_id)
                if not target_section:
                    return jsonify({
                        'success': False, 
                        'error': f'Target section ID {target_section_id} not found'
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'success': False, 
                    'error': 'Invalid target section ID'
                }), 400
        
        if target_unit_id:
            try:
                target_unit_id = int(target_unit_id)
                target_unit = Unit.query.get(target_unit_id)
                if not target_unit:
                    return jsonify({
                        'success': False, 
                        'error': f'Target unit ID {target_unit_id} not found'
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'success': False, 
                    'error': 'Invalid target unit ID'
                }), 400
        
        # FIXED: Validate employee mapping overrides format
        if employee_mapping_overrides:
            if not isinstance(employee_mapping_overrides, dict):
                return jsonify({
                    'success': False, 
                    'error': 'Employee mappings must be a dictionary'
                }), 400
            
            # Validate mapping format
            for template_emp_id, target_emp_id in employee_mapping_overrides.items():
                try:
                    int(target_emp_id)  # Ensure target employee ID is valid
                except (ValueError, TypeError):
                    return jsonify({
                        'success': False, 
                        'error': f'Invalid target employee ID in mapping: {target_emp_id}'
                    }), 400
        
        # FIXED: Pre-validate that we can apply the template
        try:
            # Get target employees to validate scope
            if target_section_id:
                target_employees = User.query.filter_by(section_id=target_section_id, is_active=True).all()
            elif target_unit_id:
                target_employees = User.query.filter_by(unit_id=target_unit_id, is_active=True).all()
            elif template.section_id:
                target_employees = User.query.filter_by(section_id=template.section_id, is_active=True).all()
            elif template.unit_id:
                target_employees = User.query.filter_by(unit_id=template.unit_id, is_active=True).all()
            else:
                return jsonify({
                    'success': False, 
                    'error': 'No target organizational scope specified'
                }), 400
            
            if not target_employees:
                return jsonify({
                    'success': False, 
                    'error': 'No active employees found in target scope'
                }), 400
            
            # Check for existing shifts if not replacing
            if not replace_existing:
                existing_shift_count = Shift.query.filter(
                    Shift.date.between(target_start, target_end),
                    Shift.employee_id.in_([emp.id for emp in target_employees])
                ).count()
                
                if existing_shift_count > 0:
                    return jsonify({
                        'success': False, 
                        'error': f'{existing_shift_count} shifts already exist in the target date range. Enable "Replace existing shifts" to overwrite them.',
                        'existing_shift_count': existing_shift_count
                    }), 400
            
        except Exception as e:
            return jsonify({
                'success': False, 
                'error': f'Validation error: {str(e)}'
            }), 400
        
        # FIXED: Apply template with comprehensive error handling
        try:
            result = template.apply_to_date_range(
                start_date=target_start,
                end_date=target_end,
                user=current_user,
                target_section_id=target_section_id,
                target_unit_id=target_unit_id,
                employee_mapping_overrides=employee_mapping_overrides,
                replace_existing=replace_existing
            )
            
            # FIXED: Validate application results
            if result['created_shifts'] == 0 and result['skipped_shifts'] == 0:
                return jsonify({
                    'success': False, 
                    'error': 'No shifts were created. Check employee mappings and template data.'
                }), 500
            
            db.session.commit()
            
            # FIXED: Enhanced success response
            success_message = f'Template applied successfully! Created {result["created_shifts"]} shifts.'
            if result['skipped_shifts'] > 0:
                success_message += f' {result["skipped_shifts"]} shifts were skipped.'
            
            return jsonify({
                'success': True,
                'message': success_message,
                'result': result,
                'template_info': {
                    'name': template.name,
                    'duration': template.duration_days,
                    'version': template.template_data.get('version', 'unknown')
                }
            })
            
        except ValueError as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False, 
                'error': f'Template application failed: {str(e)}'
            }), 500
            
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False, 
            'error': f'Unexpected error applying template: {str(e)}'
        }), 500

@bp.route('/api/templates/<int:template_id>')
@login_required
def get_template_details(template_id):
    """Get detailed template information"""
    try:
        template = ScheduleTemplateV2.query.get(template_id)
        if not template:
            return jsonify({'success': False, 'error': 'Template not found'}), 404
        
        if not template.can_user_access(current_user):
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        # Get template details with employee mappings
        template_dict = template.to_dict()
        template_dict['template_data'] = template.template_data
        template_dict['employee_mappings'] = template.employee_mappings
        
        return jsonify({
            'success': True,
            'template': template_dict
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error loading template: {str(e)}'}), 500

@bp.route('/api/templates/<int:template_id>/preview', methods=['POST'])
@login_required
def preview_template_application():
    """FIXED: Preview template application with detailed validation"""
    try:
        template = ScheduleTemplateV2.query.get(template_id)
        if not template:
            return jsonify({'success': False, 'error': 'Template not found'}), 404
        
        if not template.can_user_access(current_user):
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # Parse target dates
        try:
            target_start = datetime.strptime(data['target_start_date'], '%Y-%m-%d').date()
            target_end = datetime.strptime(data['target_end_date'], '%Y-%m-%d').date()
        except (ValueError, KeyError):
            return jsonify({'success': False, 'error': 'Invalid date format'}), 400
        
        # FIXED: Validate template data integrity
        if not template.template_data or not template.template_data.get('shifts'):
            return jsonify({
                'success': False, 
                'error': 'Template data is corrupted - cannot generate preview'
            }), 500
        
        # Get target employees
        target_section_id = data.get('target_section_id')
        target_unit_id = data.get('target_unit_id')
        
        if target_section_id:
            target_employees = User.query.filter_by(section_id=target_section_id, is_active=True).all()
        elif target_unit_id:
            target_employees = User.query.filter_by(unit_id=target_unit_id, is_active=True).all()
        else:
            return jsonify({'success': False, 'error': 'No target scope specified'}), 400
        
        if not target_employees:
            return jsonify({'success': False, 'error': 'No employees found in target scope'}), 400
        
        # FIXED: Enhanced preview data with detailed analysis
        target_duration = (target_end - target_start).days + 1
        template_duration = template.duration_days
        
        # Check for existing shifts
        existing_shifts = Shift.query.filter(
            Shift.date.between(target_start, target_end),
            Shift.employee_id.in_([emp.id for emp in target_employees])
        ).all()
        
        # Analyze employee role distribution
        target_roles = {}
        template_roles = {}
        
        for emp in target_employees:
            role_key = f"{emp.job_title or 'General'}_{emp.rank or 'Staff'}"
            target_roles[role_key] = target_roles.get(role_key, 0) + 1
        
        for emp_data in template.template_data['employees'].values():
            role_key = f"{emp_data.get('job_title') or 'General'}_{emp_data.get('rank') or 'Staff'}"
            template_roles[role_key] = template_roles.get(role_key, 0) + 1
        
        # Calculate mapping potential
        mappable_employees = 0
        role_mismatches = []
        
        for template_role, template_count in template_roles.items():
            target_count = target_roles.get(template_role, 0)
            if target_count >= template_count:
                mappable_employees += template_count
            else:
                mappable_employees += target_count
                if target_count == 0:
                    role_mismatches.append(f"No target employees with role '{template_role}' (need {template_count})")
                else:
                    role_mismatches.append(f"Role '{template_role}': need {template_count}, found {target_count}")
        
        preview_data = {
            'target_employees': [
                {
                    'id': emp.id, 
                    'name': emp.full_name, 
                    'role': emp.job_title,
                    'rank': emp.rank,
                    'role_key': f"{emp.job_title or 'General'}_{emp.rank or 'Staff'}"
                } for emp in target_employees
            ],
            'template_employees': dict(template.template_data.get('employees', {})),
            'shifts_to_create': len(template.template_data.get('shifts', [])),
            'date_range': f"{target_start.strftime('%Y-%m-%d')} to {target_end.strftime('%Y-%m-%d')}",
            'duration_match': target_duration == template_duration,
            'duration_info': {
                'target_days': target_duration,
                'template_days': template_duration,
                'difference': target_duration - template_duration
            },
            'existing_shifts': len(existing_shifts),
            'conflicts': len(existing_shifts) > 0,
            'role_analysis': {
                'target_roles': target_roles,
                'template_roles': template_roles,
                'mappable_employees': mappable_employees,
                'total_template_employees': len(template.template_data['employees']),
                'role_mismatches': role_mismatches,
                'mapping_success_rate': round((mappable_employees / len(template.template_data['employees'])) * 100, 1) if template.template_data['employees'] else 0
            },
            'template_validation': {
                'has_metadata': 'metadata' in template.template_data,
                'version': template.template_data.get('version', 'unknown'),
                'data_integrity': all([
                    'shifts' in template.template_data,
                    'employees' in template.template_data,
                    len(template.template_data['shifts']) > 0,
                    len(template.template_data['employees']) > 0
                ])
            }
        }
        
        return jsonify({
            'success': True,
            'preview': preview_data
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': f'Error generating preview: {str(e)}'
        }), 500

@bp.route('/api/templates/<int:template_id>', methods=['DELETE'])
@login_required
def delete_template(template_id):
    """Delete a schedule template"""
    try:
        template = ScheduleTemplateV2.query.get(template_id)
        if not template:
            return jsonify({'success': False, 'error': 'Template not found'}), 404
        
        # Only creator or admin can delete
        if template.created_by_id != current_user.id and not current_user.can_admin():
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        template_name = template.name
        db.session.delete(template)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Template "{template_name}" deleted successfully!'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error deleting template: {str(e)}'}), 500

@bp.route('/api/templates/<int:template_id>/duplicate', methods=['POST'])
@login_required
def duplicate_template(template_id):
    """Create a copy of existing template"""
    try:
        if not current_user.can_edit_schedule():
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        original_template = ScheduleTemplateV2.query.get(template_id)
        if not original_template:
            return jsonify({'success': False, 'error': 'Template not found'}), 404
        
        if not original_template.can_user_access(current_user):
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        data = request.get_json()
        new_name = data.get('name', f"{original_template.name} (Copy)")
        
        # Create duplicate
        duplicate = ScheduleTemplateV2(
            name=new_name,
            description=data.get('description', original_template.description),
            template_type=original_template.template_type,
            department_id=original_template.department_id,
            division_id=original_template.division_id,
            section_id=original_template.section_id,
            unit_id=original_template.unit_id,
            source_start_date=original_template.source_start_date,
            source_end_date=original_template.source_end_date,
            total_employees=original_template.total_employees,
            total_shifts=original_template.total_shifts,
            template_data=original_template.template_data.copy(),
            employee_mappings=original_template.employee_mappings.copy() if original_template.employee_mappings else None,
            created_by_id=current_user.id,
            is_public=data.get('is_public', False)
        )
        
        db.session.add(duplicate)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Template duplicated as "{new_name}"!',
            'template': duplicate.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error duplicating template: {str(e)}'}), 500

@bp.route('/api/organizational-scope')
@login_required
def get_organizational_scope():
    """Get available organizational units for template creation/application"""
    try:
        scope_data = {
            'departments': [],
            'divisions': [],
            'sections': [],
            'units': [],
            'current_user_scope': {
                'department_id': current_user.department_id,
                'division_id': current_user.division_id,
                'section_id': current_user.section_id,
                'unit_id': current_user.unit_id
            }
        }
        
        if current_user.can_admin():
            # Admins can see all organizational units
            from app.models import Department, Division, Section, Unit
            
            scope_data['departments'] = [
                {'id': dept.id, 'name': dept.name} 
                for dept in Department.query.order_by(Department.name).all()
            ]
            scope_data['divisions'] = [
                {'id': div.id, 'name': div.name, 'department_id': div.department_id} 
                for div in Division.query.order_by(Division.name).all()
            ]
            scope_data['sections'] = [
                {'id': sec.id, 'name': sec.name, 'division_id': sec.division_id} 
                for sec in Section.query.order_by(Section.name).all()
            ]
            scope_data['units'] = [
                {'id': unit.id, 'name': unit.name, 'section_id': unit.section_id} 
                for unit in Unit.query.order_by(Unit.name).all()
            ]
        elif current_user.can_edit_schedule():
            # Managers can see their organizational scope
            if current_user.department_id:
                scope_data['departments'] = [
                    {'id': current_user.department.id, 'name': current_user.department.name}
                ]
                scope_data['divisions'] = [
                    {'id': div.id, 'name': div.name, 'department_id': div.department_id}
                    for div in current_user.department.divisions
                ]
            
            if current_user.division_id:
                if not scope_data['divisions']:  # If not already populated from department
                    scope_data['divisions'] = [
                        {'id': current_user.division.id, 'name': current_user.division.name, 'department_id': current_user.division.department_id}
                    ]
                scope_data['sections'] = [
                    {'id': sec.id, 'name': sec.name, 'division_id': sec.division_id}
                    for sec in current_user.division.sections
                ]
            
            if current_user.section_id:
                if not scope_data['sections']:  # If not already populated
                    scope_data['sections'] = [
                        {'id': current_user.section.id, 'name': current_user.section.name, 'division_id': current_user.section.division_id}
                    ]
                scope_data['units'] = [
                    {'id': unit.id, 'name': unit.name, 'section_id': unit.section_id}
                    for unit in current_user.section.units
                ]
            
            if current_user.unit_id and not scope_data['units']:
                scope_data['units'] = [
                    {'id': current_user.unit.id, 'name': current_user.unit.name, 'section_id': current_user.unit.section_id}
                ]
        
        return jsonify({
            'success': True,
            'scope': scope_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error loading organizational scope: {str(e)}'}), 500
            
