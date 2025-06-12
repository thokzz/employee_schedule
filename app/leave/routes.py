# app/leave/routes.py - FIXED VERSION with email notifications

from flask import render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import login_required, current_user
from app.leave import bp
from app.models import (User, Section, Unit, LeaveApplication, LeaveType, 
                       LeaveStatus, UserRole, db, Shift, ShiftStatus, WorkExtension, WorkExtensionStatus)
from app.utils.email_service import EmailService
from datetime import datetime, date, timedelta
import os
from werkzeug.utils import secure_filename
import pdfkit

def get_user_approver(user):
    """Get the designated approver for a user based on their section/unit"""
    approver = None
    
    # First, try to find a section approver (but EXCLUDE the user themselves)
    if user.section_id:
        section_approver = User.query.filter(
            User.section_id == user.section_id,
            User.is_section_approver == True,
            User.is_active == True,
            User.id != user.id  # Don't let users approve themselves
        ).first()
        
        if section_approver:
            approver = section_approver
    
    # If no section approver, try unit approver (but EXCLUDE the user themselves)
    if not approver and user.unit_id:
        unit_approver = User.query.filter(
            User.unit_id == user.unit_id,
            User.is_unit_approver == True,
            User.is_active == True,
            User.id != user.id  # Don't let users approve themselves
        ).first()
        
        if unit_approver:
            approver = unit_approver
    
    # If still no approver, try to find a manager in the same section (but EXCLUDE the user themselves)
    if not approver and user.section_id:
        manager_approver = User.query.filter(
            User.section_id == user.section_id,
            User.role == UserRole.MANAGER,
            User.is_active == True,
            User.id != user.id  # Don't let users approve themselves
        ).first()
        
        if manager_approver:
            approver = manager_approver
    
    return approver

# REPLACE the entire get_available_approvers_for_user function in app/leave/routes.py with this:

def get_available_approvers_for_user(user):
    """Get all available approvers for a specific user based on their section/unit
    EXCLUDES administrators who are not part of the same section/unit"""
    print(f"DEBUG LEAVE: Finding approvers for user {user.full_name}")
    print(f"DEBUG LEAVE: User section_id: {user.section_id}, unit_id: {user.unit_id}")
    
    available_approvers = []
    
    # Get approvers from the same section
    if user.section_id:
        print(f"DEBUG LEAVE: Searching for section approvers in section {user.section_id}")
        section_approvers = User.query.filter(
            User.section_id == user.section_id,
            db.or_(
                User.is_section_approver == True,
                db.and_(
                    User.role == UserRole.MANAGER,
                    User.section_id == user.section_id  # Only managers in same section
                ),
                db.and_(
                    User.role == UserRole.ADMINISTRATOR,
                    User.section_id == user.section_id,  # Only admins in same section
                    User.email != 'post_it@gmanetwork.com'  # Exclude global admin from section filtering
                )
            ),
            User.is_active == True,
            User.id != user.id  # Exclude the user themselves
        ).all()
        print(f"DEBUG LEAVE: Found {len(section_approvers)} section approvers: {[a.full_name for a in section_approvers]}")
        available_approvers.extend(section_approvers)
    
    # Get approvers from the same unit (if different from section)
    if user.unit_id:
        print(f"DEBUG LEAVE: Searching for unit approvers in unit {user.unit_id}")
        unit_approvers = User.query.filter(
            User.unit_id == user.unit_id,
            db.or_(
                User.is_unit_approver == True,
                db.and_(
                    User.role == UserRole.MANAGER,
                    User.unit_id == user.unit_id  # Only managers in same unit
                ),
                db.and_(
                    User.role == UserRole.ADMINISTRATOR,
                    User.unit_id == user.unit_id,  # Only admins in same unit
                    User.email != 'post_it@gmanetwork.com'  # Exclude global admin from unit filtering
                )
            ),
            User.is_active == True,
            User.id != user.id  # Exclude the user themselves
        ).all()
        print(f"DEBUG LEAVE: Found {len(unit_approvers)} unit approvers: {[a.full_name for a in unit_approvers]}")
        
        # Add unit approvers that aren't already in the list
        for approver in unit_approvers:
            if approver not in available_approvers:
                available_approvers.append(approver)
    
    # ALWAYS include the global admin (post_it@gmanetwork.com) as an option
    global_admin = User.query.filter(
        User.email == 'post_it@gmanetwork.com',
        User.role == UserRole.ADMINISTRATOR,
        User.is_active == True,
        User.id != user.id
    ).first()
    
    if global_admin and global_admin not in available_approvers:
        available_approvers.append(global_admin)
        print(f"DEBUG LEAVE: Added global admin: {global_admin.full_name}")
    
    # Remove duplicates and sort by name
    unique_approvers = list(set(available_approvers))
    unique_approvers.sort(key=lambda x: x.full_name)
    
    print(f"DEBUG LEAVE: Final unique leave approvers: {[a.full_name for a in unique_approvers]}")
    return unique_approvers


def format_leave_dates_for_filename(start_date_str):
    """Convert leave dates to filename format (JAN1, FEB2, etc.)"""
    if not start_date_str:
        return ''
    
    from datetime import datetime
    import re
    
    # Handle multiple dates separated by commas or multiple lines
    if ',' in start_date_str or '\n' in start_date_str:
        # Multiple dates case
        # Split by commas or newlines
        date_parts = re.split(r'[,\n]', start_date_str)
        date_parts = [part.strip() for part in date_parts if part.strip()]
        
        # Remove any (1), (2), (3) markers
        cleaned_parts = []
        for part in date_parts:
            cleaned = re.sub(r'\(\d+\)', '', part).strip()
            if cleaned:
                cleaned_parts.append(cleaned)
        
        formatted_dates = []
        
        for date_part in cleaned_parts:
            try:
                # Try to parse the date
                for fmt in ['%m/%d/%Y', '%Y-%m-%d', '%B %d, %Y', '%b %d, %Y']:
                    try:
                        parsed_date = datetime.strptime(date_part, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue
                
                # Get month abbreviation and day
                month_abbr = parsed_date.strftime('%b').upper()  # JAN, FEB, etc.
                formatted_date = f"{month_abbr}{parsed_date.day}"
                formatted_dates.append(formatted_date)
                
            except Exception:
                continue
        
        return ','.join(formatted_dates)
    
    else:
        # Single date case - this is what your database has
        try:
            # Parse single date in MM/dd/yyyy format
            parsed_date = datetime.strptime(start_date_str.strip(), '%m/%d/%Y')
            
            # Get month abbreviation and day
            month_abbr = parsed_date.strftime('%b').upper()  # JAN, FEB, etc.
            day = parsed_date.day
            
            return f"{month_abbr}{day}"
            
        except ValueError:
            # Try other formats as fallback
            for fmt in ['%Y-%m-%d', '%B %d, %Y', '%b %d, %Y']:
                try:
                    parsed_date = datetime.strptime(start_date_str.strip(), fmt)
                    month_abbr = parsed_date.strftime('%b').upper()
                    day = parsed_date.day
                    return f"{month_abbr}{day}"
                except ValueError:
                    continue
            
            # If all parsing fails, return empty string
            return ''

def get_leave_type_abbreviation(leave_type):
    """Get abbreviation for leave type"""
    leave_type_mapping = {
        'SICK_LEAVE': 'SL',
        'PERSONAL_LEAVE': 'PL', 
        'EMERGENCY_LEAVE': 'EL',
        'ANNUAL_VACATION': 'AVL',
        'BEREAVEMENT_LEAVE': 'BL',
        'PATERNITY_LEAVE': 'PatL',
        'MATERNITY_LEAVE': 'MatL',
        'UNION_LEAVE': 'UL',
        'FIRE_CALAMITY_LEAVE': 'FCL',
        'SOLO_PARENT_LEAVE': 'SPL',
        'SPECIAL_LEAVE_WOMEN': 'SLW',
        'VAWC_LEAVE': 'VAWC',
        'OTHER': 'OFFSET'
    }
    
    # Handle enum values
    if hasattr(leave_type, 'value'):
        leave_type_str = leave_type.value
    else:
        leave_type_str = str(leave_type)
    
    return leave_type_mapping.get(leave_type_str, 'OFFSET')

def format_work_extension_date_for_filename(extension_date):
    """Format work extension date for filename (JAN1, FEB2, etc.)"""
    if not extension_date:
        return ''
    
    try:
        # Get month abbreviation and day
        month_abbr = extension_date.strftime('%b').upper()  # JAN, FEB, etc.
        day = extension_date.day
        return f"{month_abbr}{day}"
    except Exception:
        return ''


# ----- TEMPORARY DEBUG FOR APPROVER SELECTION

def get_available_approvers_for_user(user):
    """Get all available approvers for a specific user based on their section/unit"""
    print(f"DEBUG: Finding approvers for user {user.full_name}")
    print(f"DEBUG: User section_id: {user.section_id}, unit_id: {user.unit_id}")
    
    available_approvers = []
    
    # Get approvers from the same section
    if user.section_id:
        print(f"DEBUG: Searching for section approvers in section {user.section_id}")
        section_approvers = User.query.filter(
            User.section_id == user.section_id,
            db.or_(
                User.is_section_approver == True,
                User.role.in_([UserRole.MANAGER, UserRole.ADMINISTRATOR])
            ),
            User.is_active == True,
            User.id != user.id  # Exclude the user themselves
        ).all()
        print(f"DEBUG: Found {len(section_approvers)} section approvers: {[a.full_name for a in section_approvers]}")
        available_approvers.extend(section_approvers)
    
    # Get approvers from the same unit (if different from section)
    if user.unit_id:
        print(f"DEBUG: Searching for unit approvers in unit {user.unit_id}")
        unit_approvers = User.query.filter(
            User.unit_id == user.unit_id,
            db.or_(
                User.is_unit_approver == True,
                User.role.in_([UserRole.MANAGER, UserRole.ADMINISTRATOR])
            ),
            User.is_active == True,
            User.id != user.id  # Exclude the user themselves
        ).all()
        print(f"DEBUG: Found {len(unit_approvers)} unit approvers: {[a.full_name for a in unit_approvers]}")
        
        # Add unit approvers that aren't already in the list
        for approver in unit_approvers:
            if approver not in available_approvers:
                available_approvers.append(approver)
    
    
    # Remove duplicates and sort by name
    unique_approvers = list(set(available_approvers))
    unique_approvers.sort(key=lambda x: x.full_name)
    
    print(f"DEBUG: Final unique approvers: {[a.full_name for a in unique_approvers]}")
    return unique_approvers

@bp.route('/')
@bp.route('/request')
@login_required
def request_leave():
    """Display leave request form"""
    print(f"DEBUG: Current user: {current_user.full_name}")
    
    # Get the designated approver for current user
    approver = get_user_approver(current_user)
    print(f"DEBUG: Designated approver: {approver.full_name if approver else 'None'}")
    
    # Get all available approvers for this specific user
    available_approvers = get_available_approvers_for_user(current_user)
    print(f"DEBUG: Available approvers count: {len(available_approvers)}")
    
    # Get approved work extensions for confidential employees
    approved_work_extensions = []
    if current_user.can_file_work_extension():
        approved_work_extensions = WorkExtension.query.filter_by(
            employee_id=current_user.id,
            status=WorkExtensionStatus.APPROVED
        ).order_by(WorkExtension.extension_date.desc()).all()
    
    return render_template('leave/request_form.html', 
                         approver=approver,
                         available_approvers=available_approvers,
                         leave_types=LeaveType,
                         approved_work_extensions=approved_work_extensions)

@bp.route('/submit', methods=['POST'])
@login_required
def submit_leave():
    """Process leave application submission"""
    try:
        # Employee is always the current user
        employee = current_user
        
        # Get approver from form
        approver_id = request.form.get('manager_id')
        if not approver_id:
            flash('No approver selected. Please try again.', 'danger')
            return redirect(url_for('leave.request_leave'))
        
        approver = User.query.get(approver_id)
        if not approver or not approver.can_approve_leaves():
            flash('Selected approver is not valid.', 'danger')
            return redirect(url_for('leave.request_leave'))
        
        # Validate required fields
        leave_type = request.form.get('leave_type')
        reason = request.form.get('reason', '').strip()
        contact = request.form.get('contact', '').strip()
        
        if not leave_type or not reason or not contact:
            flash('Please fill in all required fields.', 'danger')
            return redirect(url_for('leave.request_leave'))
        
        # Special validation for "Other" leave type
        if leave_type == 'Other':
            if not current_user.can_file_work_extension():
                flash('Only Confidential employees can file "Other" leave types.', 'danger')
                return redirect(url_for('leave.request_leave'))
            
            # Check if work extensions are selected
            selected_extensions = request.form.getlist('work_extensions')
            if not selected_extensions:
                flash('Please select at least one approved work extension for "Other" leave type.', 'warning')
                return redirect(url_for('leave.request_leave'))
        
        # Get total days from the correct field
        total_days = 1  # Default
        if request.form.get('multiple_total_days'):
            total_days = float(request.form.get('multiple_total_days', 1))
        elif request.form.get('total_days'):
            total_days = float(request.form.get('total_days', 1))
        elif request.form.get('hours'):
            total_days = float(request.form.get('hours', 1))
        
        # Create leave application
        leave_app = LeaveApplication(
            reference_code=LeaveApplication.generate_reference_code(),
            employee_id=employee.id,
            employee_name=employee.full_name,
            employee_idno=employee.id_number or '',
            employee_email=employee.email,
            employee_contact=contact,
            employee_unit=employee.div_department or '',
            employee_signature_path=getattr(employee, 'signature', '') or '',
            
            leave_type=LeaveType(leave_type),
            reason=reason,
            start_date=request.form.get('start_date', '').strip(),
            end_date=request.form.get('end_date', '').strip(),
            total_days=total_days,
            is_hours_based=bool(request.form.get('is_hours_based')),
            
            approver_id=approver.id,
            approver_name=approver.full_name,
            approver_email=approver.email,
            approver_signature_path=getattr(approver, 'signature', '') or '',
            
            date_filed=date.today(),
            status=LeaveStatus.PENDING
        )
        
        # Handle work extension attachments for "Other" leave type
        if leave_type == 'Other' and current_user.can_file_work_extension():
            selected_extensions = request.form.getlist('work_extensions')
            if selected_extensions:
                # Store work extension references in the reason field or create a separate field
                extension_refs = []
                total_extension_hours = 0
                
                for ext_id in selected_extensions:
                    extension = WorkExtension.query.get(int(ext_id))
                    if extension and extension.employee_id == current_user.id and extension.status == WorkExtensionStatus.APPROVED:
                        extension_refs.append(f"Work Extension: {extension.reference_code} ({extension.extension_hours}hrs on {extension.extension_date.strftime('%m/%d/%Y')})")
                        total_extension_hours += extension.extension_hours or 0
                
                if extension_refs:
                    # Append work extension details to reason
                    leave_app.reason += f"\n\nAttached Work Extensions:\n" + "\n".join(extension_refs)
                    leave_app.reason += f"\nTotal Extension Hours: {total_extension_hours} hours"
        
        db.session.add(leave_app)
        db.session.commit()
        
        # Send email notification to approver
        try:
            email_sent = EmailService.send_leave_request_notification(leave_app)
            if email_sent:
                flash(f'Leave application {leave_app.reference_code} submitted successfully! Approver has been notified by email.', 'success')
            else:
                flash(f'Leave application {leave_app.reference_code} submitted successfully! (Email notification could not be sent)', 'warning')
        except Exception as e:
            print(f"Email notification error: {str(e)}")
            flash(f'Leave application {leave_app.reference_code} submitted successfully! (Email notification failed)', 'warning')
        
        return redirect(url_for('leave.my_applications'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error submitting leave application: {str(e)}', 'danger')
        return redirect(url_for('leave.request_leave'))

@bp.route('/api/approved-work-extensions')
@login_required
def get_approved_work_extensions():
    """Get approved work extensions for current user"""
    if not current_user.can_file_work_extension():
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    extensions = WorkExtension.query.filter_by(
        employee_id=current_user.id,
        status=WorkExtensionStatus.APPROVED
    ).order_by(WorkExtension.extension_date.desc()).all()
    
    extensions_data = []
    for ext in extensions:
        extensions_data.append({
            'id': ext.id,
            'reference_code': ext.reference_code,
            'extension_date': ext.extension_date.strftime('%m/%d/%Y'),
            'extension_hours': ext.extension_hours,
            'reason': ext.reason[:100] + '...' if len(ext.reason) > 100 else ext.reason
        })
    
    return jsonify({
        'success': True,
        'extensions': extensions_data
    })

@bp.route('/my-applications')
@login_required
def my_applications():
    """View user's own leave applications"""
    applications = LeaveApplication.query.filter_by(employee_id=current_user.id)\
                                        .order_by(LeaveApplication.created_at.desc()).all()
    return render_template('leave/my_applications.html', applications=applications)


@bp.route('/management')
@login_required
def alaf_management():
    """ALAF Management - View applications to approve"""
    if not current_user.can_approve_leaves():
        flash('You do not have permission to access ALAF Management.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Get applications this user can approve
    approvable_employees = current_user.get_approvable_employees()
    employee_ids = [emp.id for emp in approvable_employees]
    
    # Get pending and recent applications
    pending_applications = LeaveApplication.query\
        .filter(LeaveApplication.employee_id.in_(employee_ids))\
        .filter_by(status=LeaveStatus.PENDING)\
        .order_by(LeaveApplication.date_filed.asc()).all()
    
    recent_applications = LeaveApplication.query\
        .filter(LeaveApplication.employee_id.in_(employee_ids))\
        .filter(LeaveApplication.status.in_([LeaveStatus.APPROVED, LeaveStatus.DISAPPROVED]))\
        .order_by(LeaveApplication.date_reviewed.desc()).limit(20).all()
    
    stats = {
        'pending_count': len(pending_applications),
        'total_employees': len(approvable_employees),
        'approver_scope': current_user.approver_scope
    }
    
    return render_template('leave/alaf_management.html', 
                         pending_applications=pending_applications,
                         recent_applications=recent_applications,
                         stats=stats)

@bp.route('/api/application/<int:app_id>')
@login_required
def get_application(app_id):
    """Get leave application details"""
    application = LeaveApplication.query.get(app_id)
    if not application:
        return jsonify({'success': False, 'error': 'Application not found'}), 404
    
    # Check permissions
    if (application.employee_id != current_user.id and 
        application.approver_id != current_user.id and 
        not current_user.can_admin()):
        return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
    
    return jsonify({
        'success': True,
        'application': application.to_dict()
    })

@bp.route('/api/application/<int:app_id>/download-pdf')
@login_required
def download_application_pdf(app_id):
    """Download leave application as PDF in ALAF format with new filename"""
    try:
        application = LeaveApplication.query.get(app_id)
        if not application:
            return jsonify({'success': False, 'error': 'Application not found'}), 404
        
        # Check permissions
        if (application.employee_id != current_user.id and 
            application.approver_id != current_user.id and 
            not current_user.can_admin()):
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        # Generate HTML with populated data
        html_content = create_populated_alaf_html(application)
        
        # Convert HTML to PDF using wkhtmltopdf
        pdf_data = html_to_pdf(html_content)
        
        # Get employee information - use username
        employee = User.query.get(application.employee_id)
        username = employee.username or employee.id_number or f"USER{employee.id}"
        username = username.upper().replace(' ', '')  # Remove spaces and make uppercase
        
        # Format leave dates for filename
        formatted_dates = format_leave_dates_for_filename(application.start_date)
        
        # Get leave type abbreviation
        leave_abbr = get_leave_type_abbreviation(application.leave_type)
        
        # Build filename components
        filename_parts = [
            'ALAF',
            username,
            formatted_dates,
            leave_abbr,
            application.reference_code
        ]
        
        # Remove empty parts and join
        filename_parts = [part for part in filename_parts if part]
        filename = '_'.join(filename_parts) + '.pdf'
        
        # Create response
        response = make_response(pdf_data)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        
        return response
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error generating PDF: {str(e)}'}), 500


@bp.route('/api/approve/<int:app_id>', methods=['POST'])
@login_required
def approve_application(app_id):
    """Approve leave application"""
    try:
        application = LeaveApplication.query.get(app_id)
        if not application:
            return jsonify({'success': False, 'error': 'Application not found'}), 404
        
        # Check permissions
        if (application.approver_id != current_user.id and not current_user.can_admin()):
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        if application.status != LeaveStatus.PENDING:
            return jsonify({'success': False, 'error': 'Application is no longer pending'}), 400
        
        # Get form data
        data = request.get_json()
        comments = data.get('comments', '').strip()
        
        # Update application status
        application.status = LeaveStatus.APPROVED
        application.date_reviewed = datetime.utcnow()
        application.reviewer_comments = comments
        
        # Create shifts in the schedule
        create_leave_shifts(application)
        
        db.session.commit()
        
        # FIXED: Send status update email to employee
        try:
            EmailService.send_leave_status_notification(application, "approved")
        except Exception as e:
            print(f"Email notification error: {str(e)}")
        
        return jsonify({
            'success': True,
            'message': f'Leave application {application.reference_code} approved successfully!'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error approving application: {str(e)}'}), 500

@bp.route('/api/disapprove/<int:app_id>', methods=['POST'])
@login_required
def disapprove_application(app_id):
    """Disapprove leave application"""
    try:
        application = LeaveApplication.query.get(app_id)
        if not application:
            return jsonify({'success': False, 'error': 'Application not found'}), 404
        
        # Check permissions
        if (application.approver_id != current_user.id and not current_user.can_admin()):
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        if application.status != LeaveStatus.PENDING:
            return jsonify({'success': False, 'error': 'Application is no longer pending'}), 400
        
        # Get form data
        data = request.get_json()
        comments = data.get('comments', '').strip()
        
        if not comments:
            return jsonify({'success': False, 'error': 'Comments are required for disapproval'}), 400
        
        # Update application status
        application.status = LeaveStatus.DISAPPROVED
        application.date_reviewed = datetime.utcnow()
        application.reviewer_comments = comments
        
        db.session.commit()
        
        # FIXED: Send status update email to employee
        try:
            EmailService.send_leave_status_notification(application, "disapproved")
        except Exception as e:
            print(f"Email notification error: {str(e)}")
        
        return jsonify({
            'success': True,
            'message': f'Leave application {application.reference_code} disapproved.'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error disapproving application: {str(e)}'}), 500


def create_leave_shifts(leave_application):
    """Create shift entries for approved leave"""
    try:
        employee = leave_application.employee
        leave_dates = leave_application.parse_leave_dates()
        
        # Map leave types to shift statuses
        leave_type_mapping = {
            LeaveType.ANNUAL_VACATION: ShiftStatus.ANNUAL_VACATION,
            LeaveType.EMERGENCY_LEAVE: ShiftStatus.EMERGENCY_LEAVE,
            LeaveType.PERSONAL_LEAVE: ShiftStatus.PERSONAL_LEAVE,
            LeaveType.MATERNITY_LEAVE: ShiftStatus.MATERNITY_LEAVE,
            LeaveType.BEREAVEMENT_LEAVE: ShiftStatus.BEREAVEMENT_LEAVE,
            LeaveType.UNION_LEAVE: ShiftStatus.UNION_LEAVE,
            LeaveType.SICK_LEAVE: ShiftStatus.SICK_LEAVE,
            LeaveType.PATERNITY_LEAVE: ShiftStatus.PATERNITY_LEAVE,
            LeaveType.FIRE_CALAMITY_LEAVE: ShiftStatus.FIRE_CALAMITY_LEAVE,
            LeaveType.SOLO_PARENT_LEAVE: ShiftStatus.SOLO_PARENT_LEAVE,
            LeaveType.VAWC_LEAVE: ShiftStatus.VAWC_LEAVE,
            LeaveType.OTHER: ShiftStatus.OTHER
        }
        
        shift_status = leave_type_mapping.get(leave_application.leave_type, ShiftStatus.OTHER)
        
        for leave_date in leave_dates:
            # Check if shift already exists for this date
            existing_shift = Shift.query.filter_by(
                employee_id=employee.id,
                date=leave_date
            ).first()
            
            if existing_shift:
                # Update existing shift
                existing_shift.status = shift_status
                existing_shift.notes = f"Leave: {leave_application.reference_code} - {leave_application.reason}"
                existing_shift.start_time = None
                existing_shift.end_time = None
                existing_shift.role = None
                existing_shift.color = '#ffc107'  # Warning yellow for leave
            else:
                # Create new shift
                new_shift = Shift(
                    employee_id=employee.id,
                    date=leave_date,
                    status=shift_status,
                    notes=f"Leave: {leave_application.reference_code} - {leave_application.reason}",
                    start_time=None,
                    end_time=None,
                    role=None,
                    color='#ffc107',  # Warning yellow for leave
                    sequence=1
                )
                db.session.add(new_shift)
        
    except Exception as e:
        print(f"Error creating leave shifts: {str(e)}")
        raise e

# WKHTMLTOPDF FUNCTIONS
def html_to_pdf(html_content):
    """Convert HTML content to PDF using wkhtmltopdf in A5 Landscape"""
    try:
        options = {
            'page-size': 'A5',
            'orientation': 'Landscape',
            'margin-top': '0.01in',
            'margin-right': '0.1in', 
            'margin-bottom': '0.01in',
            'margin-left': '0.1in',
            'encoding': "UTF-8",
            'no-outline': None,
            'enable-local-file-access': None,
            'disable-smart-shrinking': None,
            'print-media-type': None,
            'quiet': None
        }
        
        return pdfkit.from_string(html_content, False, options=options)
        
    except Exception as e:
        print(f"Error converting HTML to PDF: {str(e)}")
        raise e

def clean_leave_dates(start_date_str):
    """Clean leave dates by removing (1), (2), (3) markers"""
    if not start_date_str:
        return ''
    
    # Remove the (1), (2), (3) etc. markers from dates
    import re
    cleaned = re.sub(r'\(\d+\)', '', start_date_str)
    
    # Clean up extra commas and spaces
    cleaned = re.sub(r',\s*,', ',', cleaned)  # Remove double commas
    cleaned = re.sub(r'^\s*,\s*', '', cleaned)  # Remove leading comma
    cleaned = re.sub(r'\s*,\s*$', '', cleaned)  # Remove trailing comma
    cleaned = re.sub(r'\s+', ' ', cleaned)  # Replace multiple spaces with single space
    
    return cleaned.strip()

def get_signature_html(signature_path, alt_text="Signature"):
    """Generate HTML for signature image if it exists"""
    if not signature_path:
        return ''
    
    from flask import current_app
    import os
    
    # Use the correct path based on where signatures are actually stored
    signature_file_path = os.path.join(current_app.root_path, 'static', 'uploads', 'signatures', signature_path)
    
    # Fallback: also check the old instance path in case some signatures are still there
    if not os.path.exists(signature_file_path):
        signature_file_path = os.path.join(current_app.instance_path, 'uploads', 'signatures', signature_path)
    
    if os.path.exists(signature_file_path):
        # Use absolute path for wkhtmltopdf
        absolute_path = os.path.abspath(signature_file_path)
        return f'<img src="file://{absolute_path}" alt="{alt_text}" style="max-height: 40px; max-width: 200px;">'
    else:
        # Debug: print the paths being checked
        print(f"DEBUG: Signature file not found at:")
        print(f"  - {os.path.join(current_app.root_path, 'static', 'uploads', 'signatures', signature_path)}")
        print(f"  - {os.path.join(current_app.instance_path, 'uploads', 'signatures', signature_path)}")
        return ''

def create_populated_alaf_html(application):
    """Create HTML content with populated ALAF form data for A5 Landscape"""
    
    # Map LeaveType enum values to HTML form names
    leave_type_mapping = {
        'Annual Vacation Leave': 'vacation_leave',
        'Emergency Leave': 'emergency_leave', 
        'Personal Leave': 'personal_leave',
        'Maternity Leave': 'maternity_leave',
        'Bereavement Leave': 'bereavement_leave',
        'Union Leave': 'union_leave',
        'Sick Leave': 'sick_leave',
        'Paternity Leave': 'paternity_leave',
        'Fire/Calamity Leave': 'fire_calamity_leave',
        'Solo Parent Leave': 'solo_parent_leave',
        'Special Leave for Women': 'special_leave_women',
        'VAWC Leave': 'vawc_leave'
    }
    
    # Get the checkbox name for the selected leave type
    selected_leave_checkbox = leave_type_mapping.get(application.leave_type.value, 'others')
    
    # Generate checkbox HTML for leave types (150% size, no border)
    checkbox_style = 'display: inline-block; width: 18px; height: 18px; margin-right: 5px; text-align: center; line-height: 16px; font-size: 14px; font-weight: bold;'
    
    leave_checkboxes = {
        'vacation_leave': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "vacation_leave" else "☐"}</span>',
        'avl': f'<span style="{checkbox_style}">☐</span>',  # AVL not in our enum
        'emergency_leave': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "emergency_leave" else "☐"}</span>',
        'personal_leave': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "personal_leave" else "☐"}</span>',
        'maternity_leave': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "maternity_leave" else "☐"}</span>',
        'bereavement_leave': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "bereavement_leave" else "☐"}</span>',
        'union_leave': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "union_leave" else "☐"}</span>',
        'sick_leave': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "sick_leave" else "☐"}</span>',
        'paternity_leave': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "paternity_leave" else "☐"}</span>',
        'fire_calamity_leave': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "fire_calamity_leave" else "☐"}</span>',
        'solo_parent_leave': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "solo_parent_leave" else "☐"}</span>',
        'special_leave_women': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "special_leave_women" else "☐"}</span>',
        'vawc_leave': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "vawc_leave" else "☐"}</span>',
        'others': f'<span style="{checkbox_style}">{"✓" if selected_leave_checkbox == "others" else "☐"}</span>',
    }
    
    # Official Action checkboxes
    approved_check = f'<span style="{checkbox_style}">{"✓" if application.status == LeaveStatus.APPROVED else "☐"}</span>'
    disapproved_check = f'<span style="{checkbox_style}">{"✓" if application.status == LeaveStatus.DISAPPROVED else "☐"}</span>'
    
    # Split reason into multiple lines for the form
    reason_lines = application.reason.split('\n') if application.reason else ['']
    reason_1 = reason_lines[0][:60] if len(reason_lines) > 0 else ''
    reason_2 = reason_lines[1][:60] if len(reason_lines) > 1 else ''
    reason_3 = reason_lines[2][:60] if len(reason_lines) > 2 else ''
    
    # If reason is one long line, split it into chunks
    if len(reason_lines) == 1 and len(reason_lines[0]) > 60:
        full_reason = reason_lines[0]
        reason_1 = full_reason[:60]
        reason_2 = full_reason[60:120] if len(full_reason) > 60 else ''
        reason_3 = full_reason[120:180] if len(full_reason) > 120 else ''
    
    # Clean the leave dates
    cleaned_leave_dates = clean_leave_dates(application.start_date)
    
    # Get signature images
    employee_signature = get_signature_html(application.employee_signature_path, "Employee Signature")
    approver_signature = get_signature_html(application.approver_signature_path, "Approver Signature")
    
    # Get logo path - using Flask's url_for to get the static file path
    from flask import current_app
    import os
    
    # For wkhtmltopdf, we need the absolute file path
    logo_path = os.path.join(current_app.static_folder, 'images', 'gma_logo.png')
    logo_html = ''
    if os.path.exists(logo_path):
        logo_html = f'<img src="file://{os.path.abspath(logo_path)}" alt="GMA Logo" style="width: 80px; height: 60px; object-fit: contain;">'
    else:
        logo_html = '<div style="width: 80px; height: 60px; display: flex; align-items: center; justify-content: center; border: 1px solid #ccc; background: #f0f0f0; font-size: 10px; color: #666;">GMA LOGO</div>'

    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>GMA Application for Leave of Absence Form (ALAF)</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 1000px;
                margin: 0 auto;
                padding: 15px;
                line-height: 1.2;
                background: white;
                font-size: 12px;
            }}
            .header {{
                display: flex;
                align-items: center;
                justify-content: center;
                margin-bottom: 20px;
                text-align: center;
            }}
            .logo {{
                width: 80px;
                margin-right: 15px;
                display: flex;
                align-items: center;
                justify-content: center;
                height: 60px;
            }}
            .title {{
                font-size: 16px;
                font-weight: bold;
            }}
            .form-row {{
                display: flex;
                margin-bottom: 12px;
                align-items: flex-end;
            }}
            .label {{
                font-weight: normal;
                margin-right: 5px;
                white-space: nowrap;
            }}
            .bold-label {{
                font-weight: bold;
                margin-right: 5px;
                white-space: nowrap;
            }}
            .input-line {{
                border-bottom: 1px solid black;
                flex-grow: 1;
                margin-right: 15px;
                height: 16px;
                position: relative;
                padding-left: 5px;
                font-size: 12px;
                display: flex;
                align-items: flex-end;
            }}
            .leave-types {{
                display: flex;
                margin-bottom: 10px;
            }}
            .leave-column {{
                flex: 1;
            }}
            .leave-option {{
                display: flex;
                align-items: center;
                margin-bottom: 4px;
                padding-left: 15px;
                font-size: 12px;
            }}
            .details-column {{
                flex: 1.5;
            }}
            .details-line {{
                border-bottom: 1px solid black;
                width: 100%;
                margin-bottom: 10px;
                height: 16px;
                position: relative;
                padding-left: 5px;
                font-size: 12px;
                display: flex;
                align-items: flex-end;
            }}
            .table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 15px;
                border: 2px solid black;
            }}
            .table td {{
                border: 1px solid black;
                padding: 8px;
                height: 40px;
                vertical-align: top;
                font-size: 12px;
            }}
            .official-action {{
                margin-bottom: 15px;
            }}
            .approval-section {{
                display: flex;
                align-items: flex-start;
                margin-top: 12px;
                margin-bottom: 12px;
                flex-wrap: wrap;
            }}
            .approval-checkbox {{
                margin-right: 30px;
                display: flex;
                align-items: center;
                margin-bottom: 10px;
            }}
            .disapproval-section {{
                display: flex;
                flex-direction: column;
                margin-right: 20px;
                margin-bottom: 10px;
                min-width: 300px;
            }}
            .disapproval-line {{
                display: flex;
                align-items: center;
                margin-bottom: 5px;
            }}
            .superior-label {{
                font-size: 10px;
                text-align: center;
                margin-top: 2px;
            }}
            .date-received {{
                margin-left: auto;
                display: flex;
                align-items: center;
                margin-bottom: 10px;
            }}
            .signatories {{
                margin-bottom: 15px;
            }}
            .signatories-item {{
                padding-left: 15px;
                margin-bottom: 4px;
                font-size: 11px;
            }}
            .ermd-section {{
                margin-bottom: 10px;
            }}
            .ermd-table {{
                width: 100%;
                border-collapse: collapse;
                border: 2px solid black;
            }}
            .ermd-table th, .ermd-table td {{
                border: 1px solid black;
                padding: 6px;
                position: relative;
            }}
            .ermd-table th {{
                font-weight: normal;
                height: 25px;
                vertical-align: middle;
                text-align: center;
                background: #f0f0f0;
                font-size: 11px;
            }}
            .ermd-table td {{
                height: 50px;
                vertical-align: top;
                font-size: 11px;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">{logo_html}</div>
            <div class="title">APPLICATION FOR LEAVE OF ABSENCE FORM (ALAF)</div>
        </div>

        <div class="form-row">
            <div class="label">Name:</div>
            <div class="input-line">{application.employee_name}</div>
            <div class="label">Date Filed:</div>
            <div class="input-line">{application.date_filed.strftime('%m/%d/%Y')}</div>
            <div class="label">Div. /Dept.:</div>
            <div class="input-line">{application.employee_unit or ''}</div>
            <div class="label">ID No.</div>
            <div class="input-line">{application.employee_idno or ''}</div>
        </div>

        <div class="label">Type of Leave (pls. check)</div>
        <div class="leave-types">
            <div class="leave-column">
                <div class="leave-option">
                    {leave_checkboxes['vacation_leave']} Vacation Leave
                </div>
                <div class="leave-option">
                    {leave_checkboxes['avl']} AVL
                </div>
                <div class="leave-option">
                    {leave_checkboxes['emergency_leave']} Emergency Leave
                </div>
                <div class="leave-option">
                    {leave_checkboxes['personal_leave']} Personal Leave
                </div>
                <div class="leave-option">
                    {leave_checkboxes['maternity_leave']} Maternity Leave
                </div>
                <div class="leave-option">
                    {leave_checkboxes['bereavement_leave']} Bereavement Leave
                </div>
                <div class="leave-option">
                    {leave_checkboxes['union_leave']} Union Leave
                </div>
            </div>
            <div class="leave-column">
                <div class="leave-option">
                    {leave_checkboxes['sick_leave']} Sick Leave
                </div>
                <div class="leave-option">
                    {leave_checkboxes['paternity_leave']} Paternity Leave
                </div>
                <div class="leave-option">
                    {leave_checkboxes['fire_calamity_leave']} Fire/Calamity Leave
                </div>
                <div class="leave-option">
                    {leave_checkboxes['solo_parent_leave']} Solo Parent Leave
                </div>
                <div class="leave-option">
                    {leave_checkboxes['special_leave_women']} Special Leave for Women
                </div>
                <div class="leave-option">
                    {leave_checkboxes['vawc_leave']} VAWC Leave
                </div>
                <div class="leave-option">
                    {leave_checkboxes['others']} Others 
                    <span style="border-bottom: 1px solid black; width: 100px; display: inline-block; margin-left: 5px;"></span>
                </div>
            </div>
            <div class="details-column">
                <div class="label">Details / Reasons :</div>
                <div class="details-line">{reason_1}</div>
                <div class="details-line">{reason_2}</div>
                <div class="details-line">{reason_3}</div>
                <div class="label">I can be contacted at:</div>
                <div class="details-line">{application.employee_contact or ''}</div>
            </div>
        </div>

        <table class="table">
            <tr>
                <td>Date/s of Leave Applied For:<br>{cleaned_leave_dates}</td>
                <td>Total No. of Leave Days:<br>{application.total_days or ''}</td>
                <td>Employee Signature:<br>{employee_signature}</td>
            </tr>
        </table>

        <div class="official-action">
            <div class="bold-label">Official Action</div>
            <div class="approval-section">
                <div class="approval-checkbox">
                    {approved_check} Approved
                </div>
                
                <div class="disapproval-section">
                    <div class="disapproval-line">
                        {disapproved_check} Disapproved by 
                        <span style="border-bottom: 1px solid black; width: 180px; margin-left: 5px; padding-left: 5px; display: inline-block; height: 20px; vertical-align: bottom;">
                            {approver_signature if approver_signature else application.approver_name}
                        </span>
                        <div style="margin-left: 10px; font-size: 10px; text-align: center; display: inline-block; vertical-align: bottom;">
                            <div>Immediate Superior</div>
                            <div>(Managers & up only)</div>
                        </div>
                    </div>
                </div>
                
                <div class="date-received">
                    <div class="label">Date Received:</div>
                    <span style="border-bottom: 1px solid black; width: 100px; margin-left: 5px; padding-left: 5px;">{application.date_reviewed.strftime('%m/%d/%Y') if application.date_reviewed else ''}</span>
                </div>
            </div>
        </div>

        <div class="signatories">
            <div class="label">Signatories for the ALAF are the following:</div>
            <div class="signatories-item">· Non-managerial levels (RF and Confi B) - to be signed by immediate manager/superior</div>
            <div class="signatories-item">· Managerial level and up - to be signed by the Group/Department/Division Head</div>
        </div>

        <div class="ermd-section">
            <div class="label">For ERMD Use Only:</div>
            <table class="ermd-table">
                <tr>
                    <th style="width: 15%;">Date Received:</th>
                    <th style="width: 50%;">Remarks</th>
                    <th style="width: 17.5%;">VL Balance</th>
                    <th style="width: 17.5%;">SL Balance</th>
                </tr>
                <tr>
                    <td></td>
                    <td>
                        <div>{f'<span style="{checkbox_style}">☐</span>'} for deduction against leave credits (<span style="border-bottom: 1px solid black; width: 60px; display: inline-block;"></span>)</div>
                        <div>{f'<span style="{checkbox_style}">☐</span>'} for salary deduction (<span style="border-bottom: 1px solid black; width: 60px; display: inline-block;"></span>)</div>
                        <div>Others : <span style="border-bottom: 1px solid black; width: 150px; display: inline-block;"></span></div>
                        {f'<div style="margin-top: 8px; font-weight: bold; font-size: 10px;">Reviewer Comments:</div><div style="font-size: 10px;">{application.reviewer_comments}</div>' if application.reviewer_comments else ''}
                    </td>
                    <td></td>
                    <td></td>
                </tr>
            </table>
        </div>
    </body>
    </html>
    """
    
    return html_template

# Enhanced routes.py - Add work extension download functionality

@bp.route('/api/work-extension/<int:extension_id>/download')
@login_required
def download_work_extension(extension_id):
    """Download work extension document/PDF with new filename format"""
    try:
        extension = WorkExtension.query.get(extension_id)
        if not extension:
            return jsonify({'success': False, 'error': 'Work extension not found'}), 404
        
        # Check permissions
        if (extension.employee_id != current_user.id and 
            not current_user.can_approve_leaves() and 
            not current_user.can_admin()):
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        # Get employee information - use username
        employee = User.query.get(extension.employee_id)
        username = employee.username or employee.id_number or f"USER{employee.id}"
        username = username.upper().replace(' ', '')  # Remove spaces and make uppercase
        
        # Format extension date for filename
        formatted_date = format_work_extension_date_for_filename(extension.extension_date)
        
        # Build filename: WORKEXTENSION_USERNAME_DATE_REFERENCECODE
        filename_parts = [
            'WORKEXTENSION',
            username,
            formatted_date,
            extension.reference_code
        ]
        
        # Remove empty parts and join
        filename_parts = [part for part in filename_parts if part]
        filename = '_'.join(filename_parts) + '.pdf'
        
        # If the work extension has an attached file
        if hasattr(extension, 'document_path') and extension.document_path:
            from flask import current_app, send_file
            import os
            
            file_path = os.path.join(current_app.instance_path, 'uploads', 'work_extensions', extension.document_path)
            if os.path.exists(file_path):
                return send_file(file_path, as_attachment=True, download_name=filename)
        
        # If no file is attached, generate a PDF summary of the work extension
        html_content = create_work_extension_summary_html(extension)
        pdf_data = html_to_pdf(html_content)
        
        response = make_response(pdf_data)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        
        return response
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error downloading work extension: {str(e)}'}), 500


@bp.route('/api/leave-application/<int:app_id>/work-extensions')
@login_required
def get_leave_work_extensions(app_id):
    """Get work extensions referenced in a leave application"""
    try:
        application = LeaveApplication.query.get(app_id)
        if not application:
            return jsonify({'success': False, 'error': 'Application not found'}), 404
        
        # Check permissions
        if (application.employee_id != current_user.id and 
            application.approver_id != current_user.id and 
            not current_user.can_admin()):
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        # Extract work extension references from the reason
        work_extensions = []
        if application.leave_type == LeaveType.OTHER and "Work Extension:" in application.reason:
            import re
            # Find all work extension reference codes in the reason
            pattern = r'Work Extension: (WE-[A-Z0-9]+)'
            matches = re.findall(pattern, application.reason)
            
            for ref_code in matches:
                extension = WorkExtension.query.filter_by(reference_code=ref_code).first()
                if extension:
                    work_extensions.append({
                        'id': extension.id,
                        'reference_code': extension.reference_code,
                        'extension_date': extension.extension_date.strftime('%m/%d/%Y'),
                        'extension_hours': extension.extension_hours,
                        'reason': extension.reason[:100] + '...' if len(extension.reason) > 100 else extension.reason,
                        'has_document': hasattr(extension, 'document_path') and bool(extension.document_path)
                    })
        
        return jsonify({
            'success': True,
            'work_extensions': work_extensions
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error retrieving work extensions: {str(e)}'}), 500

def create_work_extension_summary_html(extension):
    """Create HTML summary for work extension"""
    from flask import current_app
    import os
    
    # Get logo path
    logo_path = os.path.join(current_app.static_folder, 'images', 'gma_logo.png')
    logo_html = ''
    if os.path.exists(logo_path):
        logo_html = f'<img src="file://{os.path.abspath(logo_path)}" alt="GMA Logo" style="width: 60px; height: 45px; object-fit: contain;">'
    
    employee = User.query.get(extension.employee_id)
    approver = User.query.get(extension.approver_id) if hasattr(extension, 'approver_id') else None
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Work Extension Summary - {extension.reference_code}</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                line-height: 1.4;
                background: white;
                font-size: 12px;
            }}
            .header {{
                display: flex;
                align-items: center;
                justify-content: center;
                margin-bottom: 20px;
                text-align: center;
                border-bottom: 2px solid #333;
                padding-bottom: 15px;
            }}
            .logo {{
                margin-right: 15px;
            }}
            .title {{
                font-size: 18px;
                font-weight: bold;
            }}
            .form-row {{
                display: flex;
                margin-bottom: 10px;
                align-items: flex-end;
            }}
            .label {{
                font-weight: bold;
                margin-right: 10px;
                white-space: nowrap;
                min-width: 120px;
            }}
            .value {{
                border-bottom: 1px solid black;
                flex-grow: 1;
                padding-left: 5px;
                min-height: 16px;
            }}
            .section {{
                margin-bottom: 20px;
                border: 1px solid #ccc;
                padding: 15px;
            }}
            .section-title {{
                font-weight: bold;
                font-size: 14px;
                margin-bottom: 10px;
                color: #333;
                border-bottom: 1px solid #ddd;
                padding-bottom: 5px;
            }}
            .reason-box {{
                border: 1px solid black;
                padding: 10px;
                min-height: 100px;
                margin-top: 10px;
            }}
            .status-approved {{
                color: green;
                font-weight: bold;
            }}
            .status-pending {{
                color: orange;
                font-weight: bold;
            }}
            .status-disapproved {{
                color: red;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">{logo_html}</div>
            <div class="title">WORK EXTENSION SUMMARY</div>
        </div>

        <div class="section">
            <div class="section-title">Work Extension Details</div>
            <div class="form-row">
                <div class="label">Reference Code:</div>
                <div class="value">{extension.reference_code}</div>
            </div>
            <div class="form-row">
                <div class="label">Extension Date:</div>
                <div class="value">{extension.extension_date.strftime('%B %d, %Y')}</div>
            </div>
            <div class="form-row">
                <div class="label">Extension Hours:</div>
                <div class="value">{extension.extension_hours} hours</div>
            </div>
            <div class="form-row">
                <div class="label">Status:</div>
                <div class="value status-{extension.status.value.lower()}">{extension.status.value.title()}</div>
            </div>
        </div>

        <div class="section">
            <div class="section-title">Employee Information</div>
            <div class="form-row">
                <div class="label">Name:</div>
                <div class="value">{employee.full_name if employee else 'N/A'}</div>
            </div>
            <div class="form-row">
                <div class="label">Department:</div>
                <div class="value">{employee.div_department if employee else 'N/A'}</div>
            </div>
            <div class="form-row">
                <div class="label">Date Filed:</div>
                <div class="value">{extension.created_at.strftime('%B %d, %Y') if hasattr(extension, 'created_at') else 'N/A'}</div>
            </div>
        </div>

        <div class="section">
            <div class="section-title">Reason for Extension</div>
            <div class="reason-box">
                {extension.reason}
            </div>
        </div>

        {f'''
        <div class="section">
            <div class="section-title">Approval Information</div>
            <div class="form-row">
                <div class="label">Approved By:</div>
                <div class="value">{approver.full_name if approver else 'N/A'}</div>
            </div>
            <div class="form-row">
                <div class="label">Approval Date:</div>
                <div class="value">{extension.date_reviewed.strftime('%B %d, %Y') if hasattr(extension, 'date_reviewed') and extension.date_reviewed else 'N/A'}</div>
            </div>
        </div>
        ''' if extension.status == WorkExtensionStatus.APPROVED else ''}

        <div style="margin-top: 30px; text-align: center; font-size: 10px; color: #666;">
            Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}
        </div>
    </body>
    </html>
    """
    
    return html_template

# Enhanced version of the displayApplicationDetails function for the frontend
def get_enhanced_application_details_js():
    """Return enhanced JavaScript for displaying application details with work extension downloads"""
    return """
    function displayApplicationDetails(app) {
        const detailsContainer = document.getElementById('applicationDetails');
        
        const statusBadge = `<span class="badge" style="background-color: ${app.status_color};">${app.status.charAt(0).toUpperCase() + app.status.slice(1)}</span>`;
        
        // Check if this is an "Other" leave type that might have work extensions
        let workExtensionSection = '';
        if (app.leave_type === 'Other' && app.reason.includes('Work Extension:')) {
            workExtensionSection = `
                <div class="row mt-3">
                    <div class="col-12">
                        <h6 class="text-warning">Work Extensions</h6>
                        <div id="workExtensionsList">
                            <div class="d-flex align-items-center">
                                <span class="spinner-border spinner-border-sm me-2" role="status"></span>
                                Loading work extensions...
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }
        
        detailsContainer.innerHTML = `
            <div class="row">
                <div class="col-md-6">
                    <h6 class="text-primary">Employee Information</h6>
                    <table class="table table-sm">
                        <tr><td><strong>Name:</strong></td><td>${app.employee_name}</td></tr>
                        <tr><td><strong>Email:</strong></td><td>${app.employee_email || 'N/A'}</td></tr>
                        <tr><td><strong>Reference:</strong></td><td><code>${app.reference_code}</code></td></tr>
                    </table>
                </div>
                <div class="col-md-6">
                    <h6 class="text-success">Leave Details</h6>
                    <table class="table table-sm">
                        <tr><td><strong>Type:</strong></td><td>${app.leave_type}</td></tr>
                        <tr><td><strong>Duration:</strong></td><td>${app.total_days} ${app.is_hours_based ? 'hours' : 'days'}</td></tr>
                        <tr><td><strong>Status:</strong></td><td>${statusBadge}</td></tr>
                    </table>
                </div>
            </div>
            
            <div class="row mt-3">
                <div class="col-12">
                    <h6 class="text-info">Leave Dates/Times</h6>
                    <div class="alert alert-light">
                        <code>${app.start_date}</code>
                    </div>
                </div>
            </div>
            
            ${workExtensionSection}
            
            <div class="row mt-3">
                <div class="col-12">
                    <h6 class="text-warning">Reason</h6>
                    <div class="alert alert-light">
                        ${app.reason}
                    </div>
                </div>
            </div>
            
            ${app.reviewer_comments ? `
                <div class="row mt-3">
                    <div class="col-12">
                        <h6 class="text-secondary">Reviewer Comments</h6>
                        <div class="alert alert-info">
                            ${app.reviewer_comments}
                        </div>
                    </div>
                </div>
            ` : ''}
            
            <div class="row mt-3">
                <div class="col-md-6">
                    <small class="text-muted">
                        <strong>Filed:</strong> ${new Date(app.date_filed).toLocaleDateString()}
                    </small>
                </div>
                <div class="col-md-6 text-end">
                    <small class="text-muted">
                        <strong>Approver:</strong> ${app.approver_name}
                    </small>
                </div>
            </div>
        `;
        
        // Load work extensions if this is an "Other" leave type
        if (app.leave_type === 'Other' && app.reason.includes('Work Extension:')) {
            loadWorkExtensions(app.id);
        }
    }
    
    function loadWorkExtensions(applicationId) {
        fetch(`/leave/api/leave-application/${applicationId}/work-extensions`)
            .then(response => response.json())
            .then(data => {
                const container = document.getElementById('workExtensionsList');
                if (data.success && data.work_extensions.length > 0) {
                    let html = '<div class="list-group">';
                    data.work_extensions.forEach(ext => {
                        html += `
                            <div class="list-group-item">
                                <div class="d-flex justify-content-between align-items-start">
                                    <div class="flex-grow-1">
                                        <h6 class="mb-1">
                                            <code>${ext.reference_code}</code>
                                            <span class="badge bg-primary ms-2">${ext.extension_hours} hours</span>
                                        </h6>
                                        <p class="mb-1">
                                            <strong>Date:</strong> ${ext.extension_date}<br>
                                            <strong>Reason:</strong> ${ext.reason}
                                        </p>
                                    </div>
                                    <div class="btn-group-vertical" role="group">
                                        <button class="btn btn-sm btn-outline-primary" onclick="downloadWorkExtension(${ext.id})">
                                            <i class="bi bi-download"></i> Download
                                        </button>
                                        ${ext.has_document ? 
                                            '<small class="text-success"><i class="bi bi-file-earmark-pdf"></i> Has Document</small>' : 
                                            '<small class="text-muted"><i class="bi bi-file-earmark-text"></i> Summary Only</small>'
                                        }
                                    </div>
                                </div>
                            </div>
                        `;
                    });
                    html += '</div>';
                    container.innerHTML = html;
                } else {
                    container.innerHTML = '<div class="alert alert-warning">No work extensions found.</div>';
                }
            })
            .catch(error => {
                console.error('Error loading work extensions:', error);
                document.getElementById('workExtensionsList').innerHTML = 
                    '<div class="alert alert-danger">Error loading work extensions.</div>';
            });
    }
    
    function downloadWorkExtension(extensionId) {
        // Show loading state
        const button = event.target.closest('button');
        const originalHTML = button.innerHTML;
        button.innerHTML = '<i class="bi bi-hourglass-split"></i> Generating...';
        button.disabled = true;
        
        // Create a temporary link to trigger download
        const link = document.createElement('a');
        link.href = `/leave/api/work-extension/${extensionId}/download`;
        link.download = `WorkExtension_${extensionId}.pdf`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        // Reset button state after a short delay
        setTimeout(() => {
            button.innerHTML = originalHTML;
            button.disabled = false;
        }, 2000);
    }
    """;

def get_updated_download_js():
    """Return updated JavaScript for download functionality"""
    return """
    function downloadWorkExtension(extensionId) {
        // Show loading state
        const button = event.target.closest('button');
        const originalHTML = button.innerHTML;
        button.innerHTML = '<i class="bi bi-hourglass-split"></i> Generating...';
        button.disabled = true;
        
        // Create a temporary link to trigger download
        const link = document.createElement('a');
        link.href = `/leave/api/work-extension/${extensionId}/download`;
        // Note: The actual filename will be determined by the server
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        // Reset button state after a short delay
        setTimeout(() => {
            button.innerHTML = originalHTML;
            button.disabled = false;
        }, 2000);
    }
    
    function downloadALAF(applicationId) {
        // Show loading state
        const button = event.target.closest('button');
        const originalHTML = button.innerHTML;
        button.innerHTML = '<i class="bi bi-hourglass-split"></i> Generating PDF...';
        button.disabled = true;
        
        // Create a temporary link to trigger download
        const link = document.createElement('a');
        link.href = `/leave/api/application/${applicationId}/download-pdf`;
        // Note: The actual filename will be determined by the server
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        // Reset button state after a short delay
        setTimeout(() => {
            button.innerHTML = originalHTML;
            button.disabled = false;
        }, 2000);
    }
    """
