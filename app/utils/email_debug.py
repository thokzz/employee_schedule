# Create new file: app/utils/email_debug.py

from flask import current_app
from app.models import EmailSettings, AppSettings, User
from app.utils.email_service import EmailService
import traceback

class EmailDebug:
    """Utility class for debugging email configuration and delivery issues"""
    
    @staticmethod
    def check_email_configuration():
        """
        Comprehensive check of email configuration
        
        Returns:
            dict: Configuration status and issues
        """
        issues = []
        warnings = []
        status = "OK"
        
        try:
            # Check if EmailSettings exist
            email_settings = EmailSettings.get_settings()
            app_settings = AppSettings.get_settings()
            
            # Check basic SMTP configuration
            if not email_settings.mail_server:
                issues.append("SMTP server not configured")
                
            if not email_settings.mail_username:
                issues.append("SMTP username not configured")
                
            if not email_settings.mail_password:
                issues.append("SMTP password not configured")
                
            if email_settings.mail_port not in [25, 465, 587, 993, 995]:
                warnings.append(f"Unusual SMTP port: {email_settings.mail_port}")
            
            # Check external URL configuration
            if not app_settings.external_url:
                warnings.append("External URL not configured - email links may not work")
            
            # Check notification settings
            if not email_settings.notify_leave_requests:
                warnings.append("Leave request notifications are disabled")
            
            # Check if there are any approvers who can receive emails
            approvers = User.query.filter(
                db.or_(
                    User.is_section_approver == True,
                    User.is_unit_approver == True,
                    User.role.in_([UserRole.MANAGER, UserRole.ADMINISTRATOR])
                ),
                User.is_active == True,
                User.email != None
            ).count()
            
            if approvers == 0:
                issues.append("No active approvers with email addresses found")
            
            if issues:
                status = "ERROR"
            elif warnings:
                status = "WARNING"
                
        except Exception as e:
            issues.append(f"Error checking configuration: {str(e)}")
            status = "ERROR"
        
        return {
            'status': status,
            'issues': issues,
            'warnings': warnings,
            'smtp_configured': bool(email_settings.mail_server and email_settings.mail_username),
            'notifications_enabled': email_settings.notify_leave_requests,
            'external_url_configured': bool(app_settings.external_url)
        }
    
    @staticmethod
    def test_smtp_connection():
        """
        Test SMTP connection without sending email
        
        Returns:
            dict: Connection test results
        """
        try:
            config = EmailService.get_smtp_config()
            
            if not config:
                return {
                    'success': False,
                    'message': 'SMTP configuration not found or incomplete'
                }
            
            import smtplib
            
            # Test connection
            if config['use_tls']:
                server = smtplib.SMTP(config['server'], config['port'])
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP(config['server'], config['port'])
                server.ehlo()
            
            # Test authentication
            if config['password']:
                server.login(config['username'], config['password'])
            
            server.quit()
            
            return {
                'success': True,
                'message': 'SMTP connection and authentication successful'
            }
            
        except smtplib.SMTPAuthenticationError as e:
            return {
                'success': False,
                'message': f'Authentication failed: {str(e)}. Check username/password.'
            }
        except smtplib.SMTPConnectError as e:
            return {
                'success': False,
                'message': f'Connection failed: {str(e)}. Check server/port.'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'SMTP test failed: {str(e)}'
            }
    
    @staticmethod
    def debug_leave_notification(leave_application_id):
        """
        Debug a specific leave application notification
        
        Args:
            leave_application_id (int): Leave application ID to debug
            
        Returns:
            dict: Debug information
        """
        try:
            from app.models import LeaveApplication
            
            leave_app = LeaveApplication.query.get(leave_application_id)
            if not leave_app:
                return {
                    'success': False,
                    'message': f'Leave application {leave_application_id} not found'
                }
            
            debug_info = {
                'leave_application': {
                    'id': leave_app.id,
                    'reference_code': leave_app.reference_code,
                    'employee_name': leave_app.employee_name,
                    'employee_email': leave_app.employee_email,
                    'approver_name': leave_app.approver_name,
                    'approver_email': leave_app.approver_email,
                    'status': leave_app.status.value
                },
                'configuration_check': EmailDebug.check_email_configuration(),
                'smtp_test': EmailDebug.test_smtp_connection()
            }
            
            # Check if approver email exists
            if not leave_app.approver_email:
                debug_info['issues'] = ['Approver email address is missing']
            
            return {
                'success': True,
                'debug_info': debug_info
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Debug failed: {str(e)}',
                'traceback': traceback.format_exc()
            }
    
    @staticmethod
    def send_debug_test_email(to_email):
        """
        Send a debug test email with detailed information
        
        Args:
            to_email (str): Email address to send test to
            
        Returns:
            dict: Test results
        """
        try:
            config_check = EmailDebug.check_email_configuration()
            smtp_test = EmailDebug.test_smtp_connection()
            
            # Create debug email content
            from app.utils.email_templates import EmailTemplates
            app_settings = EmailTemplates.get_app_settings()
            
            subject = f"[DEBUG] Email Test from {app_settings.app_name}"
            
            body = f"""
DEBUG EMAIL TEST

This email contains detailed debugging information about your email configuration.

SMTP Configuration Status: {config_check['status']}
SMTP Connection Test: {'PASSED' if smtp_test['success'] else 'FAILED'}
Notifications Enabled: {config_check['notifications_enabled']}
External URL Configured: {config_check['external_url_configured']}

Issues Found: {len(config_check['issues'])}
{chr(10).join('- ' + issue for issue in config_check['issues'])}

Warnings: {len(config_check['warnings'])}
{chr(10).join('- ' + warning for warning in config_check['warnings'])}

SMTP Test Result: {smtp_test['message']}

Application URL: {app_settings.get_full_url()}
Test Sent At: {EmailTemplates.get_app_settings().get_full_url()}

---
Email Debug Utility
{app_settings.app_name}
            """.strip()
            
            # Try to send the email
            send_result = EmailService.send_email(to_email, subject, body)
            
            return {
                'success': send_result,
                'configuration_status': config_check,
                'smtp_test': smtp_test,
                'message': 'Debug email sent successfully' if send_result else 'Failed to send debug email'
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Debug test failed: {str(e)}',
                'traceback': traceback.format_exc()
            }
    
    @staticmethod
    def get_email_statistics():
        """
        Get email-related statistics
        
        Returns:
            dict: Email statistics
        """
        try:
            from app.models import LeaveApplication, User, UserRole
            
            # Count users with email addresses
            total_users = User.query.filter_by(is_active=True).count()
            users_with_email = User.query.filter(
                User.is_active == True,
                User.email != None,
                User.email != ''
            ).count()
            
            # Count approvers with email addresses
            approvers_with_email = User.query.filter(
                db.or_(
                    User.is_section_approver == True,
                    User.is_unit_approver == True,
                    User.role.in_([UserRole.MANAGER, UserRole.ADMINISTRATOR])
                ),
                User.is_active == True,
                User.email != None,
                User.email != ''
            ).count()
            
            # Count recent leave applications
            from datetime import datetime, timedelta
            recent_applications = LeaveApplication.query.filter(
                LeaveApplication.created_at >= datetime.utcnow() - timedelta(days=30)
            ).count()
            
            pending_applications = LeaveApplication.query.filter_by(
                status=LeaveStatus.PENDING
            ).count()
            
            return {
                'total_active_users': total_users,
                'users_with_email': users_with_email,
                'users_without_email': total_users - users_with_email,
                'approvers_with_email': approvers_with_email,
                'recent_leave_applications_30_days': recent_applications,
                'pending_leave_applications': pending_applications,
                'email_coverage_percentage': round((users_with_email / max(total_users, 1)) * 100, 1)
            }
            
        except Exception as e:
            return {
                'error': f'Failed to get statistics: {str(e)}'
            }
