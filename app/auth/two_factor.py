from flask import session, request, redirect, url_for, flash, current_app
from flask_login import current_user
from functools import wraps
from app.models import TwoFactorSettings, UserTwoFactor, TrustedDevice, TwoFactorStatus, db
from datetime import datetime, timedelta, timezone
import secrets
import hashlib
import hmac
import time
import re

class TwoFactorManager:
    """Manager class for 2FA operations with enhanced security"""
    
    # Rate limiting constants
    MAX_ATTEMPTS_PER_HOUR = 5
    MAX_CODE_REQUESTS_PER_HOUR = 3
    CODE_EXPIRY_MINUTES = 5  # Reduced from 10
    SESSION_TIMEOUT_MINUTES = 30
    
    @staticmethod
    def is_2fa_required():
        """Check if 2FA is required system-wide"""
        settings = TwoFactorSettings.get_settings()
        return settings.system_2fa_enabled
    
    @staticmethod
    def is_user_2fa_required(user):
        """Check if 2FA is required for specific user"""
        if not user:
            return False
        settings = TwoFactorSettings.get_settings()
        return settings.is_2fa_required_for_user(user)
    
    @staticmethod
    def _get_session_fingerprint():
        """Generate session fingerprint for additional security"""
        user_agent = request.headers.get('User-Agent', '')
        ip_address = request.remote_addr or ''
        # Create a fingerprint without storing sensitive data
        fingerprint_data = f"{user_agent}{ip_address}"
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]
    
    @staticmethod
    def _is_session_valid(user_id):
        """Validate session integrity and timing"""
        # Check if session exists and matches user
        if not session.get('2fa_verified') or session.get('2fa_user_id') != user_id:
            return False
        
        # Check session fingerprint
        stored_fingerprint = session.get('2fa_fingerprint')
        current_fingerprint = TwoFactorManager._get_session_fingerprint()
        if not stored_fingerprint or not hmac.compare_digest(stored_fingerprint, current_fingerprint):
            return False
        
        # Check session timeout
        verified_at = session.get('2fa_verified_at')
        if not verified_at:
            return False
        
        try:
            verified_time = datetime.fromisoformat(verified_at)
            expiry_time = verified_time + timedelta(minutes=TwoFactorManager.SESSION_TIMEOUT_MINUTES)
            if datetime.utcnow() > expiry_time:
                return False
        except (ValueError, TypeError):
            return False
        
        return True
    
    @staticmethod
    def _validate_device_token(token):
        """Validate device token format and content"""
        if not token:
            return False
        
        # Basic format validation
        if not re.match(r'^[a-zA-Z0-9\-_]{32,128}$', token):
            return False
        
        # Additional entropy check
        if len(set(token)) < 10:  # Should have reasonable character diversity
            return False
        
        return True
    
    @staticmethod
    def _check_rate_limit(user_id, action_type):
        """Check rate limiting for various actions"""
        current_time = time.time()
        session_key = f'{action_type}_attempts_{user_id}'
        
        # Get existing attempts
        attempts = session.get(session_key, [])
        
        # Clean old attempts (older than 1 hour)
        attempts = [attempt for attempt in attempts if current_time - attempt < 3600]
        
        # Check limits
        max_attempts = {
            'verify': TwoFactorManager.MAX_ATTEMPTS_PER_HOUR,
            'code_request': TwoFactorManager.MAX_CODE_REQUESTS_PER_HOUR,
            'login': 10,  # Allow more login attempts
            'totp_setup': 10
        }.get(action_type, 5)
        
        if len(attempts) >= max_attempts:
            return False, f"Too many {action_type} attempts. Please try again later."
        
        # Add current attempt
        attempts.append(current_time)
        session[session_key] = attempts
        
        return True, None
    
    @staticmethod
    def check_2fa_status(user):
        """Check user's 2FA status and return appropriate action"""
        if not user:
            return {'status': 'error', 'action': 'login'}
        
        if not TwoFactorManager.is_user_2fa_required(user):
            return {'status': 'not_required', 'action': 'proceed'}
        
        # Get or create user 2FA record
        user_2fa = user.two_factor
        if not user_2fa:
            user_2fa = UserTwoFactor(user_id=user.id)
            user_2fa.start_grace_period()
            db.session.add(user_2fa)
            try:
                db.session.commit()
            except Exception as e:
                current_app.logger.error(f"Error creating 2FA record: {e}")
                db.session.rollback()
                return {'status': 'error', 'action': 'retry'}
        
        # Check if already verified in this session with enhanced validation
        if TwoFactorManager._is_session_valid(user.id):
            return {'status': 'verified', 'action': 'proceed'}
        
        # Check trusted device with validation
        device_token = request.cookies.get('trusted_device')
        if device_token and TwoFactorManager._validate_device_token(device_token):
            if user.can_skip_2fa(device_token):
                # Set secure session
                TwoFactorManager._set_verified_session(user.id)
                return {'status': 'trusted_device', 'action': 'proceed'}
        
        # Check if in grace period
        if user_2fa.is_in_grace_period():
            return {'status': 'grace_period', 'action': 'remind_setup'}
        
        # Check if setup is complete
        if user_2fa.status == TwoFactorStatus.ENABLED:
            return {'status': 'setup_complete', 'action': 'verify'}
        
        # Requires setup
        return {'status': 'setup_required', 'action': 'setup'}
    
    @staticmethod
    def _set_verified_session(user_id):
        """Set secure verified session"""
        session['2fa_verified'] = True
        session['2fa_user_id'] = user_id
        session['2fa_verified_at'] = datetime.utcnow().isoformat()
        session['2fa_fingerprint'] = TwoFactorManager._get_session_fingerprint()
    
    @staticmethod
    def _generate_secure_code():
        """Generate cryptographically secure 6-digit code"""
        # Use cryptographically secure random
        code = ''.join(secrets.choice('0123456789') for _ in range(6))
        
        # Ensure code doesn't start with 0 and has reasonable entropy
        while code.startswith('0') or len(set(code)) < 3:
            code = ''.join(secrets.choice('0123456789') for _ in range(6))
        
        return code
    
    @staticmethod
    def _hash_code(code, user_id):
        """Hash 2FA code for secure storage"""
        salt = str(user_id).encode() + current_app.secret_key.encode()
        return hashlib.pbkdf2_hmac('sha256', code.encode(), salt, 100000).hex()
    
    @staticmethod
    def send_2fa_code(user, method):
        """Send 2FA code via specified method with rate limiting"""
        if not user:
            return False, "Invalid user"
        
        # Validate method
        if method not in ['sms', 'email']:
            return False, "Invalid delivery method"
        
        # Check rate limiting
        rate_ok, rate_msg = TwoFactorManager._check_rate_limit(user.id, 'code_request')
        if not rate_ok:
            return False, rate_msg
        
        # Generate secure code
        code = TwoFactorManager._generate_secure_code()
        
        # Hash and store code securely
        code_hash = TwoFactorManager._hash_code(code, user.id)
        expiry_time = datetime.utcnow() + timedelta(minutes=TwoFactorManager.CODE_EXPIRY_MINUTES)
        
        session[f'2fa_code_hash_{user.id}'] = code_hash
        session[f'2fa_code_expires_{user.id}'] = expiry_time.isoformat()
        session[f'2fa_code_method_{user.id}'] = method
        
        # Send code
        if method == 'sms':
            return TwoFactorManager._send_sms_code(user, code)
        elif method == 'email':
            return TwoFactorManager._send_email_code(user, code)
        
        return False, "Unknown delivery method"
    
    @staticmethod
    def verify_2fa_code(user, submitted_code):
        """Verify 2FA code with enhanced security"""
        if not user or not submitted_code:
            return False, "Invalid input"
        
        # Sanitize input
        submitted_code = re.sub(r'[^0-9]', '', str(submitted_code))
        if len(submitted_code) != 6:
            return False, "Invalid code format"
        
        # Check rate limiting
        rate_ok, rate_msg = TwoFactorManager._check_rate_limit(user.id, 'verify')
        if not rate_ok:
            return False, rate_msg
        
        # Get stored code hash
        stored_hash = session.get(f'2fa_code_hash_{user.id}')
        expiry_str = session.get(f'2fa_code_expires_{user.id}')
        
        if not stored_hash or not expiry_str:
            return False, "No valid code found. Please request a new code."
        
        # Check expiry
        try:
            expiry_time = datetime.fromisoformat(expiry_str)
            if datetime.utcnow() > expiry_time:
                # Clean up expired code
                TwoFactorManager._cleanup_2fa_code(user.id)
                return False, "Code has expired. Please request a new code."
        except ValueError:
            return False, "Invalid code data"
        
        # Verify code using constant-time comparison
        submitted_hash = TwoFactorManager._hash_code(submitted_code, user.id)
        if not hmac.compare_digest(stored_hash, submitted_hash):
            return False, "Invalid code"
        
        # Success - clean up and set session
        TwoFactorManager._cleanup_2fa_code(user.id)
        TwoFactorManager._set_verified_session(user.id)
        
        return True, "Code verified successfully"
    
    @staticmethod
    def _cleanup_2fa_code(user_id):
        """Clean up 2FA code data from session"""
        keys_to_remove = [
            f'2fa_code_hash_{user_id}',
            f'2fa_code_expires_{user_id}',
            f'2fa_code_method_{user_id}'
        ]
        for key in keys_to_remove:
            session.pop(key, None)
    
    @staticmethod
    def clear_2fa_session():
        """Clear 2FA verification from session"""
        keys_to_clear = [
            '2fa_verified', '2fa_user_id', '2fa_verified_at', 
            '2fa_fingerprint', '2fa_reminder_shown'
        ]
        for key in keys_to_clear:
            session.pop(key, None)
    
    @staticmethod
    def _send_sms_code(user, code):
        """Send SMS 2FA code - implement based on your SMS provider"""
        try:
            # Validate phone number exists
            if not user.two_factor or not user.two_factor.phone_number:
                return False, "No phone number configured"
            
            # Log for development (remove in production)
            current_app.logger.info(f"SMS 2FA code would be sent to {user.two_factor.phone_number}")
            
            # TODO: Implement actual SMS sending
            # Example: send_sms(user.two_factor.phone_number, f"Your verification code is: {code}")
            
            return True, "SMS sent successfully"
        except Exception as e:
            current_app.logger.error(f"SMS sending failed: {e}")
            return False, "Failed to send SMS"
    
    @staticmethod
    def _send_email_code(user, code):
        """Send Email 2FA code"""
        try:
            # Validate email exists
            if not user.email:
                return False, "No email address available"
            
            # Log for development (remove in production)
            current_app.logger.info(f"Email 2FA code would be sent to {user.email}")
            
            # TODO: Implement actual email sending
            # Example: send_email(user.email, "2FA Verification Code", f"Your code is: {code}")
            
            return True, "Email sent successfully"
        except Exception as e:
            current_app.logger.error(f"Email sending failed: {e}")
            return False, "Failed to send email"

def require_2fa_setup(f):
    """Decorator to require 2FA setup before accessing protected routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        
        try:
            status_check = TwoFactorManager.check_2fa_status(current_user)
        except Exception as e:
            current_app.logger.error(f"2FA status check failed: {e}")
            flash('Authentication error. Please try again.', 'error')
            return redirect(url_for('auth.login'))
        
        if status_check['action'] == 'setup':
            flash('You must set up two-factor authentication to continue.', 'warning')
            return redirect(url_for('auth.setup_2fa'))
        elif status_check['action'] == 'verify':
            return redirect(url_for('auth.verify_2fa'))
        elif status_check['action'] == 'remind_setup':
            # Show reminder but allow access
            if not session.get('2fa_reminder_shown'):
                flash('Please set up two-factor authentication. Your grace period will expire soon.', 'info')
                session['2fa_reminder_shown'] = True
        elif status_check['action'] == 'retry':
            flash('System error. Please try again.', 'error')
            return redirect(url_for('auth.login'))
        
        return f(*args, **kwargs)
    
    return decorated_function