# =============================================================================
# ENHANCED SCHEDULE ROUTES - app/schedule/routes.py
# Added Export Worksched function for managers
# =============================================================================

from flask import render_template, request, jsonify, redirect, url_for, flash, make_response
from flask_login import login_required, current_user
from app.schedule import bp
from app.models import User, Shift, Section, Unit, ShiftStatus, WorkArrangement, db
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
        
        # NEW: Handle work arrangement
        work_arrangement = data.get('work_arrangement', 'onsite')
        shift.work_arrangement = WorkArrangement(work_arrangement)
        
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
        
        # Check permissions
        if not current_user.can_edit_schedule() and shift.employee_id != current_user.id:
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        db.session.delete(shift)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Shift deleted successfully!'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error deleting shift: {str(e)}'}), 500

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
    
    def calculate_break_times(shift, employee):
        """Calculate break times based on employee's schedule format and shift duration"""
        if not shift.start_time or not shift.qualifies_for_break:
            return ('', '', '', '')  # No break times if shift < 4 hours
        
        break_duration = employee.get_break_duration_minutes()
        break_start_time = datetime.combine(shift.date, shift.start_time) + timedelta(hours=3)
        break_end_time = break_start_time + timedelta(minutes=break_duration)
        
        # Determine which columns to fill based on break duration
        if break_duration == 60:  # 9-hour shift (1 hr break)
            return (
                break_start_time.strftime('%H:%M'),  # 1hr break start
                break_end_time.strftime('%H:%M'),    # 1hr break end
                '',  # 30min break start (empty)
                ''   # 30min break end (empty)
            )
        else:  # 8-hour shift or others (30 min break)
            return (
                '',  # 1hr break start (empty)
                '',  # 1hr break end (empty)
                break_start_time.strftime('%H:%M'),  # 30min break start
                break_end_time.strftime('%H:%M')     # 30min break end
            )
    
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
                # No shifts = rest day
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
                    'Rest day'   # Remarks
                ])
            else:
                # Handle each shift for this employee on this date
                for shift_idx, shift in enumerate(emp_shifts):
                    # Determine DWS value and break eligibility
                    if shift.status in [ShiftStatus.REST_DAY]:
                        dws_value = 'FREE'
                        work_start = ''
                        work_end = ''
                        break_1hr_start = ''
                        break_1hr_end = ''
                        break_30min_start = ''
                        break_30min_end = ''
                        remarks = 'Rest day'
                    elif shift.status in [
                        ShiftStatus.SICK_LEAVE, ShiftStatus.PERSONAL_LEAVE, 
                        ShiftStatus.EMERGENCY_LEAVE, ShiftStatus.ANNUAL_VACATION,
                        ShiftStatus.HOLIDAY_OFF, ShiftStatus.BEREAVEMENT_LEAVE,
                        ShiftStatus.PATERNITY_LEAVE, ShiftStatus.MATERNITY_LEAVE,
                        ShiftStatus.UNION_LEAVE, ShiftStatus.FIRE_CALAMITY_LEAVE,
                        ShiftStatus.SOLO_PARENT_LEAVE, ShiftStatus.SPECIAL_LEAVE_WOMEN,
                        ShiftStatus.VAWC_LEAVE, ShiftStatus.OTHER
                    ]:
                        dws_value = 'FREE'
                        work_start = ''
                        work_end = ''
                        break_1hr_start = ''
                        break_1hr_end = ''
                        break_30min_start = ''
                        break_30min_end = ''
                        # Convert status to readable format
                        remarks = shift.status.value.replace('_', ' ').title()
                        if shift.notes:
                            remarks += f" - {shift.notes}"
                    else:
                        # Regular scheduled shift
                        dws_value = ''  # Blank for regular schedule
                        work_start = shift.start_time.strftime('%H:%M') if shift.start_time else ''
                        work_end = shift.end_time.strftime('%H:%M') if shift.end_time else ''
                        
                        # Calculate break times based on employee's schedule format
                        break_1hr_start, break_1hr_end, break_30min_start, break_30min_end = calculate_break_times(shift, employee)
                        
                        # Build remarks
                        remarks_parts = []
                        if shift.role:
                            remarks_parts.append(f"Role: {shift.role}")
                        if shift.work_arrangement and shift.work_arrangement.value != 'onsite':
                            remarks_parts.append(f"Work: {shift.work_arrangement.value.upper()}")
                        if shift.notes:
                            remarks_parts.append(shift.notes)
                        
                        remarks = ' - '.join(remarks_parts) if remarks_parts else ''
                        
                        # Add shift duration info for split schedules
                        if len(emp_shifts) > 1:
                            remarks = f"Split #{shift.sequence}" + (f" - {remarks}" if remarks else "")
                    
                    writer.writerow([
                        employee_name,
                        formatted_date,
                        formatted_date,      # Same as FROM date
                        dws_value,           # DWS (FREE for rest/leave, blank for regular)
                        work_start,          # Work schedule start time
                        work_end,            # Work schedule end time
                        break_1hr_start,     # 1hr paid break start (for 9-hour shifts)
                        break_1hr_end,       # 1hr paid break end (for 9-hour shifts)
                        break_30min_start,   # 30min paid break start (for 8-hour shifts)
                        break_30min_end,     # 30min paid break end (for 8-hour shifts)
                        remarks              # Remarks
                    ])
            
            current_date += timedelta(days=1)
    
    # Create response
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=worksched_{start_date.strftime("%b_%d")}_to_{end_date.strftime("%b_%d_%Y")}.csv'
    
    return response