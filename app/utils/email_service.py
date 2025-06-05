# Replace your app/utils/email_service.py with this working version

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app
from datetime import datetime

class EmailService:
    """Simple email service for sending notifications"""
    
    @staticmethod
    def get_smtp_config():
        """Get SMTP configuration from database"""
        try:
            from app.models import EmailSettings
            settings = EmailSettings.get_settings()
            
            if not settings.mail_server or not settings.mail_username:
                return None
                
            return {
                'server': settings.mail_server,
                'port': settings.mail_port,
                'use_tls': settings.mail_use_tls,
                'username': settings.mail_username,
                'password': settings.mail_password,
                'default_sender': settings.mail_default_sender or settings.mail_username
            }
        except Exception as e:
            print(f"DEBUG: Error getting SMTP config: {str(e)}")
            return None
    
    @staticmethod
    def get_app_url():
        """Get application base URL"""
        try:
            from app.models import AppSettings
            settings = AppSettings.get_settings()
            return settings.external_url or 'http://localhost:5000'
        except:
            return 'http://localhost:5000'
    
    @staticmethod
    def send_email(to_email, subject, body, html_body=None):
        """Send an email using configured SMTP settings"""
        try:
            config = EmailService.get_smtp_config()
            if not config:
                print("DEBUG: Email not configured - skipping email notification")
                return False
            
            print(f"DEBUG: Sending email to {to_email} with subject: {subject}")
            
            # Create message
            msg = MIMEMultipart('alternative')
            msg['From'] = config['default_sender']
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Add plain text part
            msg.attach(MIMEText(body, 'plain'))
            
            # Add HTML part if provided
            if html_body:
                msg.attach(MIMEText(html_body, 'html'))
            
            # Connect and send
            if config['use_tls']:
                server = smtplib.SMTP(config['server'], config['port'])
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP(config['server'], config['port'])
                server.ehlo()
            
            if config['password']:
                server.login(config['username'], config['password'])
            
            server.sendmail(config['default_sender'], to_email, msg.as_string())
            server.quit()
            
            print(f"DEBUG: Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            print(f"DEBUG: Failed to send email to {to_email}: {str(e)}")
            return False
    
    @staticmethod
    def send_leave_request_notification(leave_application):
        """Send leave request notification to approver"""
        try:
            # Check if notifications are enabled
            from app.models import EmailSettings
            settings = EmailSettings.get_settings()
            if not settings.notify_leave_requests:
                print("DEBUG: Leave request notifications are disabled")
                return False
            
            approver_email = leave_application.approver_email
            if not approver_email:
                print(f"DEBUG: No approver email for leave request {leave_application.reference_code}")
                return False
            
            # Create simple email content
            subject = f"New Leave Request - {leave_application.reference_code}"
            
            # Get app URL for links
            app_url = EmailService.get_app_url()
            management_url = f"{app_url.rstrip('/')}/leave/management"
            
            body = f"""
New Leave Request Submitted

Reference Code: {leave_application.reference_code}
Employee: {leave_application.employee_name}
Leave Type: {leave_application.leave_type.value}
Dates: {leave_application.start_date}
Total Days: {leave_application.total_days or 'N/A'}
Reason: {leave_application.reason}
Date Filed: {leave_application.date_filed.strftime('%B %d, %Y')}

To review and approve this request, please visit:
{management_url}

---
Employee Scheduling System - Automated Notification
            """.strip()
            
            # Create simple HTML version
            html_body = f"""
            <h2>New Leave Request Submitted</h2>
            <p><strong>Reference Code:</strong> {leave_application.reference_code}</p>
            <p><strong>Employee:</strong> {leave_application.employee_name}</p>
            <p><strong>Leave Type:</strong> {leave_application.leave_type.value}</p>
            <p><strong>Dates:</strong> {leave_application.start_date}</p>
            <p><strong>Total Days:</strong> {leave_application.total_days or 'N/A'}</p>
            <p><strong>Reason:</strong> {leave_application.reason}</p>
            <p><strong>Date Filed:</strong> {leave_application.date_filed.strftime('%B %d, %Y')}</p>
            
            <p><a href="{management_url}" style="background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Review Leave Request</a></p>
            
            <p style="font-size: 12px; color: #666;">Employee Scheduling System - Automated Notification</p>
            """
            
            return EmailService.send_email(approver_email, subject, body, html_body)
            
        except Exception as e:
            print(f"DEBUG: Error sending leave request notification: {str(e)}")
            return False
    
    @staticmethod
    def send_leave_status_notification(leave_application, new_status):
        """Send notification to employee when leave status changes"""
        try:
            from app.models import EmailSettings
            settings = EmailSettings.get_settings()
            if not settings.notify_leave_requests:
                print("DEBUG: Leave request notifications are disabled")
                return False
            
            employee_email = leave_application.employee_email
            if not employee_email:
                print(f"DEBUG: No employee email for leave request {leave_application.reference_code}")
                return False
            
            status_word = "Approved" if new_status == "approved" else "Disapproved"
            subject = f"Leave Request {status_word} - {leave_application.reference_code}"
            
            # Get app URL for links
            app_url = EmailService.get_app_url()
            my_applications_url = f"{app_url.rstrip('/')}/leave/my-applications"
            
            comments_text = ""
            if leave_application.reviewer_comments:
                comments_text = f"\nComments: {leave_application.reviewer_comments}"
            
            body = f"""
Your Leave Request Has Been {status_word}

Reference Code: {leave_application.reference_code}
Leave Type: {leave_application.leave_type.value}
Dates: {leave_application.start_date}
Status: {status_word}
Reviewed By: {leave_application.approver_name}
Review Date: {leave_application.date_reviewed.strftime('%B %d, %Y %I:%M %p') if leave_application.date_reviewed else 'N/A'}{comments_text}

To view your leave application details, please visit:
{my_applications_url}

---
Employee Scheduling System - Automated Notification
            """.strip()
            
            # Create simple HTML version
            status_color = "#28a745" if new_status == "approved" else "#dc3545"
            html_body = f"""
            <h2 style="color: {status_color};">Your Leave Request Has Been {status_word}</h2>
            <p><strong>Reference Code:</strong> {leave_application.reference_code}</p>
            <p><strong>Leave Type:</strong> {leave_application.leave_type.value}</p>
            <p><strong>Dates:</strong> {leave_application.start_date}</p>
            <p><strong>Status:</strong> <span style="color: {status_color};">{status_word}</span></p>
            <p><strong>Reviewed By:</strong> {leave_application.approver_name}</p>
            <p><strong>Review Date:</strong> {leave_application.date_reviewed.strftime('%B %d, %Y %I:%M %p') if leave_application.date_reviewed else 'N/A'}</p>
            {f'<p><strong>Comments:</strong> {leave_application.reviewer_comments}</p>' if leave_application.reviewer_comments else ''}
            
            <p><a href="{my_applications_url}" style="background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View My Leave Applications</a></p>
            
            <p style="font-size: 12px; color: #666;">Employee Scheduling System - Automated Notification</p>
            """
            
            return EmailService.send_email(employee_email, subject, body, html_body)
            
        except Exception as e:
            print(f"DEBUG: Error sending leave status notification: {str(e)}")
            return False
    
    @staticmethod
    def send_test_email(to_email, app_url=None):
        """Send a test email to verify configuration"""
        try:
            app_url = app_url or EmailService.get_app_url()
            subject = "Test Email from Employee Scheduling System"
            
            body = f"""
Test Email from Employee Scheduling System

This is a test email to verify that your email configuration is working correctly.

Application URL: {app_url}
Sent at: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}

If you received this email, your SMTP settings are configured properly!

---
Employee Scheduling System - Email Configuration Test
            """.strip()
            
            html_body = f"""
            <h2>Test Email from Employee Scheduling System</h2>
            <p>This is a test email to verify that your email configuration is working correctly.</p>
            <p><strong>Application URL:</strong> <a href="{app_url}">{app_url}</a></p>
            <p><strong>Sent at:</strong> {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
            <p style="color: #28a745;"><strong>✅ If you received this email, your SMTP settings are configured properly!</strong></p>
            <p style="font-size: 12px; color: #666;">Employee Scheduling System - Email Configuration Test</p>
            """
            
            return EmailService.send_email(to_email, subject, body, html_body)
            
        except Exception as e:
            print(f"DEBUG: Error sending test email: {str(e)}")
            return False