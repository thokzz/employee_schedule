# Create new file: app/work_extension/routes.py
from flask import render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import login_required, current_user
from app.work_extension import bp
from app.models import (User, WorkExtension, WorkExtensionStatus, EmployeeType, 
                       UserRole, db, Shift, ShiftStatus)
from app.utils.email_service import EmailService
from datetime import datetime, date, timedelta, time
import os
from werkzeug.utils import secure_filename
import pdfkit

# Replace the approver functions in app/work_extension/routes.py

def get_user_approver(user):
    """Get the designated approver for a user (reuse from leave module)"""
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
            User.role == UserRole.MANAGER,  # Only MANAGER, not ADMINISTRATOR
            User.is_active == True,
            User.id != user.id  # Don't let users approve themselves
        ).first()
        
        if manager_approver:
            approver = manager_approver
    
    return approver

def get_available_approvers_for_user(user):
    """Get all available approvers for a specific user based on their section/unit
    EXCLUDES administrators who are not part of the same section/unit"""
    print(f"DEBUG WORK EXT: Finding approvers for user {user.full_name}")
    print(f"DEBUG WORK EXT: User section_id: {user.section_id}, unit_id: {user.unit_id}")
    
    available_approvers = []
    
    # Get approvers from the same section
    if user.section_id:
        print(f"DEBUG WORK EXT: Searching for section approvers in section {user.section_id}")
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
        print(f"DEBUG WORK EXT: Found {len(section_approvers)} section approvers: {[a.full_name for a in section_approvers]}")
        available_approvers.extend(section_approvers)
    
    # Get approvers from the same unit (if different from section)
    if user.unit_id:
        print(f"DEBUG WORK EXT: Searching for unit approvers in unit {user.unit_id}")
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
        print(f"DEBUG WORK EXT: Found {len(unit_approvers)} unit approvers: {[a.full_name for a in unit_approvers]}")
        
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
        print(f"DEBUG WORK EXT: Added global admin: {global_admin.full_name}")
    
    # Remove duplicates and sort by name
    unique_approvers = list(set(available_approvers))
    unique_approvers.sort(key=lambda x: x.full_name)
    
    print(f"DEBUG WORK EXT: Final unique work extension approvers: {[a.full_name for a in unique_approvers]}")
    return unique_approvers

@bp.route('/')
@bp.route('/request')
@login_required
def request_work_extension():
    """Display work extension request form"""
    # Check if user can file work extensions
    if not current_user.can_file_work_extension():
        flash('Work Extension requests are only available for Confidential employees.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Get the designated approver for current user
    approver = get_user_approver(current_user)
    
    # Get all available approvers using the new restricted function
    available_approvers = get_available_approvers_for_user(current_user)
    
    return render_template('work_extension/request_form.html', 
                         approver=approver,
                         available_approvers=available_approvers)

@bp.route('/submit', methods=['POST'])
@login_required
def submit_work_extension():
    """Process work extension submission"""
    try:
        # Check if user can file work extensions
        if not current_user.can_file_work_extension():
            flash('You are not authorized to file work extensions.', 'danger')
            return redirect(url_for('main.dashboard'))
        
        # Employee is always the current user
        employee = current_user
        
        # Get approver from form
        approver_id = request.form.get('approver_id')
        if not approver_id:
            flash('No approver selected. Please try again.', 'danger')
            return redirect(url_for('work_extension.request_work_extension'))
        
        approver = User.query.get(approver_id)
        if not approver or not approver.can_approve_leaves():
            flash('Selected approver is not valid.', 'danger')
            return redirect(url_for('work_extension.request_work_extension'))
        
        # Validate required fields
        extension_date_str = request.form.get('extension_date')
        reason = request.form.get('reason', '').strip()
        
        if not extension_date_str or not reason:
            flash('Please fill in all required fields.', 'danger')
            return redirect(url_for('work_extension.request_work_extension'))
        
        # Parse dates and times
        extension_date = datetime.strptime(extension_date_str, '%Y-%m-%d').date()
        
        # Parse times
        shift_start = None
        shift_end = None
        actual_time_in = None
        actual_time_out = None
        extended_from = None
        extended_to = None
        
        if request.form.get('shift_start'):
            shift_start = datetime.strptime(request.form.get('shift_start'), '%H:%M').time()
        if request.form.get('shift_end'):
            shift_end = datetime.strptime(request.form.get('shift_end'), '%H:%M').time()
        if request.form.get('actual_time_in'):
            actual_time_in = datetime.strptime(request.form.get('actual_time_in'), '%H:%M').time()
        if request.form.get('actual_time_out'):
            actual_time_out = datetime.strptime(request.form.get('actual_time_out'), '%H:%M').time()
        if request.form.get('extended_from'):
            extended_from = datetime.strptime(request.form.get('extended_from'), '%H:%M').time()
        if request.form.get('extended_to'):
            extended_to = datetime.strptime(request.form.get('extended_to'), '%H:%M').time()
        
        # Create work extension
        work_ext = WorkExtension(
            reference_code=WorkExtension.generate_reference_code(),
            employee_id=employee.id,
            employee_name=employee.full_name,
            employee_email=employee.email,
            employee_contact=request.form.get('contact', employee.contact_number),
            employee_section=employee.section.name if employee.section else '',
            employee_signature_path=getattr(employee, 'signature', '') or '',
            
            extension_date=extension_date,
            shift_start=shift_start,
            shift_end=shift_end,
            actual_time_in=actual_time_in,
            actual_time_out=actual_time_out,
            extended_from=extended_from,
            extended_to=extended_to,
            reason=reason,
            
            approver_id=approver.id,
            approver_name=approver.full_name,
            approver_email=approver.email,
            approver_signature_path=getattr(approver, 'signature', '') or '',
            
            date_filed=date.today(),
            status=WorkExtensionStatus.PENDING
        )
        
        # Calculate extension hours
        work_ext.calculate_extension_hours()
        
        db.session.add(work_ext)
        db.session.commit()
        
        # Send email notification to approver
        try:
            email_sent = send_work_extension_notification(work_ext)
            if email_sent:
                flash(f'Work Extension {work_ext.reference_code} submitted successfully! Approver has been notified by email.', 'success')
            else:
                flash(f'Work Extension {work_ext.reference_code} submitted successfully! (Email notification could not be sent)', 'warning')
        except Exception as e:
            print(f"Email notification error: {str(e)}")
            flash(f'Work Extension {work_ext.reference_code} submitted successfully! (Email notification failed)', 'warning')
        
        return redirect(url_for('work_extension.my_work_extensions'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error submitting work extension: {str(e)}', 'danger')
        return redirect(url_for('work_extension.request_work_extension'))

@bp.route('/my-work-extensions')
@login_required
def my_work_extensions():
    """View user's own work extensions"""
    if not current_user.can_file_work_extension():
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    extensions = WorkExtension.query.filter_by(employee_id=current_user.id)\
                                  .order_by(WorkExtension.created_at.desc()).all()
    return render_template('work_extension/my_work_extensions.html', extensions=extensions)

@bp.route('/management')
@login_required
def work_extension_management():
    """Work Extension Management - View extensions to approve"""
    if not current_user.can_approve_leaves():
        flash('You do not have permission to access Work Extension Management.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Get extensions this user can approve
    approvable_employees = current_user.get_approvable_employees()
    # Filter to only confidential employees
    confidential_employees = [emp for emp in approvable_employees 
                            if emp.can_file_work_extension()]
    employee_ids = [emp.id for emp in confidential_employees]
    
    # Get pending and recent extensions
    pending_extensions = WorkExtension.query\
        .filter(WorkExtension.employee_id.in_(employee_ids))\
        .filter_by(status=WorkExtensionStatus.PENDING)\
        .order_by(WorkExtension.date_filed.asc()).all()
    
    recent_extensions = WorkExtension.query\
        .filter(WorkExtension.employee_id.in_(employee_ids))\
        .filter(WorkExtension.status.in_([WorkExtensionStatus.APPROVED, WorkExtensionStatus.DISAPPROVED]))\
        .order_by(WorkExtension.date_reviewed.desc()).limit(20).all()
    
    stats = {
        'pending_count': len(pending_extensions),
        'total_confidential_employees': len(confidential_employees),
        'approver_scope': current_user.approver_scope
    }
    
    return render_template('work_extension/management.html', 
                         pending_extensions=pending_extensions,
                         recent_extensions=recent_extensions,
                         stats=stats)

@bp.route('/api/work-extension/<int:ext_id>')
@login_required
def get_work_extension(ext_id):
    """Get work extension details"""
    extension = WorkExtension.query.get(ext_id)
    if not extension:
        return jsonify({'success': False, 'error': 'Work extension not found'}), 404
    
    # Check permissions
    if (extension.employee_id != current_user.id and 
        extension.approver_id != current_user.id and 
        not current_user.can_admin()):
        return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
    
    return jsonify({
        'success': True,
        'extension': extension.to_dict()
    })

@bp.route('/api/work-extension/<int:ext_id>/download-pdf')
@login_required
def download_work_extension_pdf(ext_id):
    """Download work extension as PDF"""
    try:
        extension = WorkExtension.query.get(ext_id)
        if not extension:
            return jsonify({'success': False, 'error': 'Work extension not found'}), 404
        
        # Check permissions
        if (extension.employee_id != current_user.id and 
            extension.approver_id != current_user.id and 
            not current_user.can_admin()):
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        # Generate HTML with populated data
        html_content = create_populated_work_extension_html(extension)
        
        # Convert HTML to PDF using wkhtmltopdf
        pdf_data = html_to_pdf(html_content)
        
        # Create response
        response = make_response(pdf_data)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=WorkExtension_{extension.reference_code}.pdf'
        
        return response
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error generating PDF: {str(e)}'}), 500

@bp.route('/api/approve/<int:ext_id>', methods=['POST'])
@login_required
def approve_work_extension(ext_id):
    """Approve work extension"""
    try:
        extension = WorkExtension.query.get(ext_id)
        if not extension:
            return jsonify({'success': False, 'error': 'Work extension not found'}), 404
        
        # Check permissions
        if (extension.approver_id != current_user.id and not current_user.can_admin()):
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        if extension.status != WorkExtensionStatus.PENDING:
            return jsonify({'success': False, 'error': 'Work extension is no longer pending'}), 400
        
        # Get form data
        data = request.get_json()
        comments = data.get('comments', '').strip()
        
        # Update extension status
        extension.status = WorkExtensionStatus.APPROVED
        extension.date_reviewed = datetime.utcnow()
        extension.reviewer_comments = comments
        
        db.session.commit()
        
        # Send status update email to employee
        try:
            send_work_extension_status_notification(extension, "approved")
        except Exception as e:
            print(f"Email notification error: {str(e)}")
        
        return jsonify({
            'success': True,
            'message': f'Work Extension {extension.reference_code} approved successfully!'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error approving work extension: {str(e)}'}), 500

@bp.route('/api/disapprove/<int:ext_id>', methods=['POST'])
@login_required
def disapprove_work_extension(ext_id):
    """Disapprove work extension"""
    try:
        extension = WorkExtension.query.get(ext_id)
        if not extension:
            return jsonify({'success': False, 'error': 'Work extension not found'}), 404
        
        # Check permissions
        if (extension.approver_id != current_user.id and not current_user.can_admin()):
            return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
        
        if extension.status != WorkExtensionStatus.PENDING:
            return jsonify({'success': False, 'error': 'Work extension is no longer pending'}), 400
        
        # Get form data
        data = request.get_json()
        comments = data.get('comments', '').strip()
        
        if not comments:
            return jsonify({'success': False, 'error': 'Comments are required for disapproval'}), 400
        
        # Update extension status
        extension.status = WorkExtensionStatus.DISAPPROVED
        extension.date_reviewed = datetime.utcnow()
        extension.reviewer_comments = comments
        
        db.session.commit()
        
        # Send status update email to employee
        try:
            send_work_extension_status_notification(extension, "disapproved")
        except Exception as e:
            print(f"Email notification error: {str(e)}")
        
        return jsonify({
            'success': True,
            'message': f'Work Extension {extension.reference_code} disapproved.'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error disapproving work extension: {str(e)}'}), 500

# EMAIL NOTIFICATION FUNCTIONS
def send_work_extension_notification(work_extension):
    """Send work extension notification to approver"""
    try:
        # Check if notifications are enabled
        from app.models import EmailSettings
        settings = EmailSettings.get_settings()
        if not settings.notify_leave_requests:  # Reuse leave notification setting
            print("DEBUG: Leave request notifications are disabled")
            return False
        
        approver_email = work_extension.approver_email
        if not approver_email:
            print(f"DEBUG: No approver email for work extension {work_extension.reference_code}")
            return False
        
        # Create email content
        subject = f"New Work Extension Request - {work_extension.reference_code}"
        
        # Get app URL for links
        from app.utils.email_service import EmailService
        app_url = EmailService.get_app_url()
        management_url = f"{app_url.rstrip('/')}/work-extension/management"
        
        body = f"""
New Work Extension Request Submitted

Reference Code: {work_extension.reference_code}
Employee: {work_extension.employee_name}
Extension Date: {work_extension.extension_date.strftime('%B %d, %Y')}
Extension Hours: {work_extension.extension_hours or 'N/A'} hours
Section: {work_extension.employee_section}
Reason: {work_extension.reason}
Date Filed: {work_extension.date_filed.strftime('%B %d, %Y')}

To review and approve this request, please visit:
{management_url}

---
Employee Scheduling System - Automated Notification
        """.strip()
        
        # Create HTML version
        html_body = f"""
        <h2>New Work Extension Request Submitted</h2>
        <p><strong>Reference Code:</strong> {work_extension.reference_code}</p>
        <p><strong>Employee:</strong> {work_extension.employee_name}</p>
        <p><strong>Extension Date:</strong> {work_extension.extension_date.strftime('%B %d, %Y')}</p>
        <p><strong>Extension Hours:</strong> {work_extension.extension_hours or 'N/A'} hours</p>
        <p><strong>Section:</strong> {work_extension.employee_section}</p>
        <p><strong>Reason:</strong> {work_extension.reason}</p>
        <p><strong>Date Filed:</strong> {work_extension.date_filed.strftime('%B %d, %Y')}</p>
        
        <p><a href="{management_url}" style="background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Review Work Extension Request</a></p>
        
        <p style="font-size: 12px; color: #666;">Employee Scheduling System - Automated Notification</p>
        """
        
        return EmailService.send_email(approver_email, subject, body, html_body)
        
    except Exception as e:
        print(f"DEBUG: Error sending work extension notification: {str(e)}")
        return False

def send_work_extension_status_notification(work_extension, new_status):
    """Send notification to employee when work extension status changes"""
    try:
        from app.models import EmailSettings
        settings = EmailSettings.get_settings()
        if not settings.notify_leave_requests:
            print("DEBUG: Leave request notifications are disabled")
            return False
        
        employee_email = work_extension.employee_email
        if not employee_email:
            print(f"DEBUG: No employee email for work extension {work_extension.reference_code}")
            return False
        
        status_word = "Approved" if new_status == "approved" else "Disapproved"
        subject = f"Work Extension {status_word} - {work_extension.reference_code}"
        
        # Get app URL for links
        from app.utils.email_service import EmailService
        app_url = EmailService.get_app_url()
        my_extensions_url = f"{app_url.rstrip('/')}/work-extension/my-work-extensions"
        
        comments_text = ""
        if work_extension.reviewer_comments:
            comments_text = f"\nComments: {work_extension.reviewer_comments}"
        
        body = f"""
Your Work Extension Request Has Been {status_word}

Reference Code: {work_extension.reference_code}
Extension Date: {work_extension.extension_date.strftime('%B %d, %Y')}
Extension Hours: {work_extension.extension_hours or 'N/A'} hours
Status: {status_word}
Reviewed By: {work_extension.approver_name}
Review Date: {work_extension.date_reviewed.strftime('%B %d, %Y %I:%M %p') if work_extension.date_reviewed else 'N/A'}{comments_text}

To view your work extension details, please visit:
{my_extensions_url}

---
Employee Scheduling System - Automated Notification
        """.strip()
        
        # Create HTML version
        status_color = "#28a745" if new_status == "approved" else "#dc3545"
        html_body = f"""
        <h2 style="color: {status_color};">Your Work Extension Request Has Been {status_word}</h2>
        <p><strong>Reference Code:</strong> {work_extension.reference_code}</p>
        <p><strong>Extension Date:</strong> {work_extension.extension_date.strftime('%B %d, %Y')}</p>
        <p><strong>Extension Hours:</strong> {work_extension.extension_hours or 'N/A'} hours</p>
        <p><strong>Status:</strong> <span style="color: {status_color};">{status_word}</span></p>
        <p><strong>Reviewed By:</strong> {work_extension.approver_name}</p>
        <p><strong>Review Date:</strong> {work_extension.date_reviewed.strftime('%B %d, %Y %I:%M %p') if work_extension.date_reviewed else 'N/A'}</p>
        {f'<p><strong>Comments:</strong> {work_extension.reviewer_comments}</p>' if work_extension.reviewer_comments else ''}
        
        <p><a href="{my_extensions_url}" style="background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View My Work Extensions</a></p>
        
        <p style="font-size: 12px; color: #666;">Employee Scheduling System - Automated Notification</p>
        """
        
        return EmailService.send_email(employee_email, subject, body, html_body)
        
    except Exception as e:
        print(f"DEBUG: Error sending work extension status notification: {str(e)}")
        return False

# PDF GENERATION FUNCTIONS
def html_to_pdf(html_content):
    """Convert HTML content to PDF using wkhtmltopdf"""
    try:
        options = {
            'page-size': 'A6',
            'orientation': 'landscape',
            'margin-top': '0.2in',
            'margin-right': '0.4in', 
            'margin-bottom': '0.4in',
            'margin-left': '0.6in',
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

def get_signature_html(signature_path, alt_text="Signature"):
    """Generate HTML for signature image if it exists"""
    if not signature_path:
        return ''
    
    from flask import current_app
    import os
    
    # Use the correct path based on where signatures are actually stored
    signature_file_path = os.path.join(current_app.root_path, 'static', 'uploads', 'signatures', signature_path)
    
    if os.path.exists(signature_file_path):
        # Use absolute path for wkhtmltopdf
        absolute_path = os.path.abspath(signature_file_path)
        return f'<img src="file://{absolute_path}" alt="{alt_text}" style="max-height: 40px; max-width: 200px;">'
    else:
        return ''

def create_populated_work_extension_html(extension):
    """Create HTML content with populated Work Extension form data optimized for A5 landscape"""
    
    # Get signature images
    employee_signature = get_signature_html(extension.employee_signature_path, "Employee Signature")
    approver_signature = get_signature_html(extension.approver_signature_path, "Approver Signature")
    
    # Format dates and times
    formatted_extension_date = extension.extension_date.strftime('%m/%d/%Y') if extension.extension_date else ''
    formatted_date_filed = extension.date_filed.strftime('%m/%d/%Y') if extension.date_filed else ''
    
    shift_start_str = extension.shift_start.strftime('%H:%M') if extension.shift_start else ''
    shift_end_str = extension.shift_end.strftime('%H:%M') if extension.shift_end else ''
    actual_time_in_str = extension.actual_time_in.strftime('%H:%M') if extension.actual_time_in else ''
    actual_time_out_str = extension.actual_time_out.strftime('%H:%M') if extension.actual_time_out else ''
    extended_from_str = extension.extended_from.strftime('%H:%M') if extension.extended_from else ''
    extended_to_str = extension.extended_to.strftime('%H:%M') if extension.extended_to else ''
    
    # Split reason into multiple lines for the form
    reason_lines = extension.reason.split('\n') if extension.reason else ['']
    reason_text = extension.reason[:400] if extension.reason else ''  # Reduced to fit better

    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Work Extension Form</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 0;
                background-color: white;
                font-size: 12px;
                line-height: 1.1;
            }}
            
            .form-container {{
                width: 148mm;  /* A5 landscape width */
                height: 105mm;  /* A5 landscape height */
                margin: 0 auto;
                padding: 8mm 6mm;  /* Reduced padding significantly */
                box-sizing: border-box;
                position: relative;
            }}
            
            .title {{
                font-size: 14px;
                font-weight: bold;
                text-decoration: underline;
                margin-bottom: 8mm;  /* Reduced from 80px */
                letter-spacing: 0.5px;
                text-align: center;
            }}
            
            .basic-info {{
                margin-bottom: 4mm;  /* Reduced from 40px */
            }}
            
            .name-line {{
                margin-bottom: 3mm;  /* Reduced from 20px */
                display: flex;
                align-items: baseline;
            }}
            
            .section-date-line {{
                display: flex;
                align-items: baseline;
                margin-bottom: 4mm;  /* Reduced from 40px */
            }}
            
            .name-line label,
            .section-date-line label {{
                font-weight: bold;
                margin-right: 3px;
                font-size: 11px;
            }}
            
            .underline {{
                border-bottom: 1px solid #000;
                flex: 1;
                height: 14px;  /* Reduced height */
                margin-left: 3px;
                margin-right: 3px;
                position: relative;
                padding-left: 3px;
                font-size: 11px;
                display: flex;
                align-items: flex-end;
            }}
            
            .underline-section {{
                border-bottom: 1px solid #000;
                width: 60mm;  /* Adjusted for A5 */
                height: 14px;
                margin-left: 3px;
                margin-right: 5mm;
                position: relative;
                padding-left: 3px;
                font-size: 11px;
                display: flex;
                align-items: flex-end;
            }}
            
            .underline-date {{
                border-bottom: 1px solid #000;
                width: 40mm;  /* Adjusted for A5 */
                height: 14px;
                margin-left: 3px;
                position: relative;
                padding-left: 3px;
                font-size: 11px;
                display: flex;
                align-items: flex-end;
            }}
            
            .main-content {{
                display: flex;
                border: 2px solid #000;
                margin-bottom: 6mm;  /* Reduced from 60px */
                height: 45mm;  /* Fixed height for main content */
            }}
            
            .left-section {{
                width: 50%;
                padding: 3mm;  /* Reduced padding */
                border-right: 1px solid #000;
                box-sizing: border-box;
            }}
            
            .right-section {{
                width: 50%;
                padding: 3mm;  /* Reduced padding */
                box-sizing: border-box;
            }}
            
            .left-section .field {{
                margin-bottom: 2.5mm;  /* Reduced spacing */
                display: flex;
                align-items: baseline;
            }}
            
            .left-section .field label {{
                font-weight: bold;
                margin-right: 3px;
                white-space: nowrap;
                font-size: 10px;
            }}
            
            .field-underline {{
                border-bottom: 1px solid #000;
                flex: 1;
                height: 12px;  /* Reduced height */
                margin-left: 3px;
                position: relative;
                padding-left: 3px;
                font-size: 10px;
                display: flex;
                align-items: flex-end;
            }}
            
            .shift-schedule {{
                display: flex;
                align-items: baseline;
                margin-bottom: 2.5mm;
            }}
            
            .shift-schedule label {{
                font-weight: bold;
                margin-right: 3px;
                font-size: 10px;
            }}
            
            .shift-from {{
                border-bottom: 1px solid #000;
                width: 15mm;  /* Adjusted for A5 */
                height: 12px;
                margin: 0 3px;
                position: relative;
                padding-left: 2px;
                font-size: 10px;
                display: flex;
                align-items: flex-end;
            }}
            
            .shift-to {{
                border-bottom: 1px solid #000;
                width: 15mm;  /* Adjusted for A5 */
                height: 12px;
                margin: 0 3px;
                position: relative;
                padding-left: 2px;
                font-size: 10px;
                display: flex;
                align-items: flex-end;
            }}
            
            .time-in-out {{
                display: flex;
                align-items: baseline;
                margin-bottom: 3mm;  /* Reduced spacing */
            }}
            
            .time-in-out label {{
                font-weight: bold;
                margin-right: 3px;
                font-size: 10px;
            }}
            
            .time-in {{
                border-bottom: 1px solid #000;
                width: 18mm;  /* Adjusted for A5 */
                height: 12px;
                margin: 0 3px 0 3px;
                position: relative;
                padding-left: 2px;
                font-size: 10px;
                display: flex;
                align-items: flex-end;
            }}
            
            .time-out {{
                border-bottom: 1px solid #000;
                width: 18mm;  /* Adjusted for A5 */
                height: 12px;
                margin: 0 3px;
                position: relative;
                padding-left: 2px;
                font-size: 10px;
                display: flex;
                align-items: flex-end;
            }}
            
            .extended-time-section {{
                margin-top: 1mm;  /* Reduced spacing */
            }}
            
            .extended-time-title {{
                font-weight: bold;
                margin-bottom: 2mm;  /* Reduced spacing */
                font-size: 10px;
            }}
            
            .extended-time-fields {{
                display: flex;
                align-items: baseline;
            }}
            
            .extended-time-fields label {{
                font-weight: bold;
                margin-right: 3px;
                font-size: 10px;
            }}
            
            .extended-from {{
                border-bottom: 1px solid #000;
                width: 22mm;  /* Adjusted for A5 */
                height: 12px;
                margin: 0 3px 0 3px;
                position: relative;
                padding-left: 2px;
                font-size: 10px;
                display: flex;
                align-items: flex-end;
            }}
            
            .extended-to {{
                border-bottom: 1px solid #000;
                width: 22mm;  /* Adjusted for A5 */
                height: 12px;
                margin: 0 3px;
                position: relative;
                padding-left: 2px;
                font-size: 10px;
                display: flex;
                align-items: flex-end;
            }}
            
            .right-section h3 {{
                font-weight: bold;
                font-size: 11px;
                margin: 0 0 2mm 0;  /* Reduced margin */
            }}
            
            .reason-content {{
                width: 100%;
                height: 35mm;  /* Fixed height for reason box */
                font-size: 10px;
                line-height: 1.2;
                padding: 2mm;
                word-wrap: break-word;
                overflow: hidden;
                box-sizing: border-box;
            }}
            
            .signatures {{
                display: flex;
                justify-content: space-between;
                margin-top: 4mm;  /* Reduced from 40px */
                height: 20mm;  /* Fixed height for signatures */
            }}
            
            .signature-block {{
                text-align: left;
                width: 30%;
            }}
            
            .signature-title {{
                font-weight: bold;
                margin-bottom: 3mm;  /* Reduced spacing */
                font-size: 10px;
            }}
            
            .signature-line {{
                border-bottom: 1px solid #000;
                height: 8mm;  /* Reduced signature line height */
                margin-bottom: 1mm;
                width: 35mm;  /* Adjusted for A5 */
                display: flex;
                align-items: flex-end;
                padding-left: 2px;
            }}
            
            .signature-label {{
                font-weight: normal;
                font-size: 9px;  /* Smaller label text */
                line-height: 1;
            }}
            
            @media print {{
                body {{
                    margin: 0;
                    padding: 0;
                }}
                
                .form-container {{
                    margin: 0;
                    padding: 8mm 6mm;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="form-container">
            <div class="title">WORK EXTENSION FORM</div>
            
            <div class="basic-info">
                <div class="name-line">
                    <label>Name:</label>
                    <div class="underline">{extension.employee_name}</div>
                </div>
                
                <div class="section-date-line">
                    <label>Section:</label>
                    <div class="underline-section">{extension.employee_section}</div>
                    <label>Date Filed:</label>
                    <div class="underline-date">{formatted_date_filed}</div>
                </div>
            </div>
            
            <div class="main-content">
                <div class="left-section">
                    <div class="field">
                        <label>Date of Extended Work:</label>
                        <div class="field-underline">{formatted_extension_date}</div>
                    </div>
                    
                    <div class="shift-schedule">
                        <label>Shift Schedule: From</label>
                        <div class="shift-from">{shift_start_str}</div>
                        <label>To</label>
                        <div class="shift-to">{shift_end_str}</div>
                    </div>
                    
                    <div class="time-in-out">
                        <label>Time In:</label>
                        <div class="time-in">{actual_time_in_str}</div>
                        <label>Time Out:</label>
                        <div class="time-out">{actual_time_out_str}</div>
                    </div>
                    
                    <div class="extended-time-section">
                        <div class="extended-time-title">Extended Time:</div>
                        <div class="extended-time-fields">
                            <label>From:</label>
                            <div class="extended-from">{extended_from_str}</div>
                            <label>To:</label>
                            <div class="extended-to">{extended_to_str}</div>
                        </div>
                    </div>
                </div>
                
                <div class="right-section">
                    <h3>Reason/s for the need to extended work hours:</h3>
                    <div class="reason-content">
                        {reason_text}
                    </div>
                </div>
            </div>
            
            <div class="signatures">
                <div class="signature-block">
                    <div class="signature-title">Prepared by:</div>
                    <div class="signature-line">{employee_signature if employee_signature else extension.employee_name}</div>
                    <div class="signature-label">Employee's Name & Signature</div>
                </div>
                
                <div class="signature-block">
                    <div class="signature-title">Endorsed by:</div>
                    <div class="signature-line">{approver_signature if approver_signature else extension.approver_name}</div>
                    <div class="signature-label">Unit Head/Section Head</div>
                </div>
                
                <div class="signature-block">
                    <div class="signature-title">Approved by:</div>
                    <div class="signature-line"></div>
                    <div class="signature-label">First VP or VP Post Production</div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_template
