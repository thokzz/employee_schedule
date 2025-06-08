from flask import render_template, redirect, url_for, flash, request, session, jsonify, make_response, current_app
from flask_login import login_user, logout_user, current_user, login_required
from app.auth import bp
from app.models import User, db, TwoFactorSettings, UserTwoFactor, TrustedDevice, TwoFactorStatus, TwoFactorMethod
from app.auth.two_factor import TwoFactorManager, require_2fa_setup
from werkzeug.urls import url_parse
from datetime import datetime, timedelta
import pyotp
import re
import secrets
import time
import hashlib
import hmac

def _generate_csrf_token():
    """Generate CSRF token"""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']

def _validate_csrf_token(token):
    """Validate CSRF token"""
    if not token:
        return False
    stored_token = session.get('csrf_token')
    if not stored_token:
        return False
    return hmac.compare_digest(stored_token, token)

def _validate_input(value, input_type="text", max_length=None):
    """Validate and sanitize input"""
    if not value:
        return None
    
    value = str(value).strip()
    
    if input_type == "phone":
        # Remove all non-digit characters
        value = re.sub(r'[^\d+]', '', value)
        if not re.match(r'^\+?[1-9]\d{1,14}$', value):
            return None
    elif input_type == "code":
        # Only digits, exactly 6 characters
        value = re.sub(r'[^\d]', '', value)
        if len(value) != 6:
            return None
    elif input_type == "text":
        # Basic text sanitization
        if max_length and len(value) > max_length:
            value = value[:max_length]
    
    return value

def _check_account_locked(user):
    """Check if user account is temporarily locked"""
    if not user.two_factor:
        return False
    
    if hasattr(user.two_factor, 'locked_until') and user.two_factor.locked_until:
        if datetime.utcnow() < user.two_factor.locked_until:
            return True
        else:
            # Clear expired lock
            user.two_factor.locked_until = None
            db.session.commit()
    
    return False

def _validate_emergency_code(user, emergency_code):
    """Validate emergency access code"""
    if not user or not emergency_code:
        return False
    
    # Sanitize input
    emergency_code = _validate_input(emergency_code, "text", 50)
    if not emergency_code:
        return False
    
    # Check if user has valid backup codes
    if not user.two_factor:
        return False
    
    # Use backup code validation (more secure than separate emergency codes)
    return user.two_factor.use_backup_code(emergency_code)

def _is_2fa_verified():
    """Check if 2FA is verified in current session"""
    return TwoFactorManager._is_session_valid(current_user.id if current_user.is_authenticated else None)

# Add CSRF token to all templates
@bp.context_processor
def inject_csrf_token():
    return dict(csrf_token=_generate_csrf_token)

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # Check if user needs 2FA verification even if logged in
        if not _is_2fa_verified():
            return redirect(url_for('auth.verify_2fa'))
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        # Rate limiting check (without CSRF for login)
        session_id = session.get('session_id', secrets.token_urlsafe(32))
        session['session_id'] = session_id
        
        if not TwoFactorManager._check_rate_limit(session_id, 'login')[0]:
            flash('Too many login attempts. Please try again later.', 'error')
            return redirect(url_for('auth.login'))
        
        # Validate and sanitize inputs
        username = _validate_input(request.form.get('username'), "text", 100)
        password = request.form.get('password', '')
        remember_me = bool(request.form.get('remember_me'))
        emergency_code = _validate_input(request.form.get('emergency_code'), "text", 50)
        
        if not username or not password:
            flash('Username and password are required.', 'error')
            return redirect(url_for('auth.login'))
        
        user = User.query.filter_by(username=username).first()
        
        if user is None or not user.check_password(password):
            # Add delay to prevent timing attacks
            time.sleep(0.5)
            flash('Invalid username or password', 'danger')
            return redirect(url_for('auth.login'))
        
        if not user.is_active:
            flash('Your account has been deactivated. Please contact an administrator.', 'warning')
            return redirect(url_for('auth.login'))
        
        # Check if account is temporarily locked
        if _check_account_locked(user):
            flash('Account temporarily locked due to multiple failed attempts.', 'error')
            return redirect(url_for('auth.login'))
        
        # Handle emergency access code
        if emergency_code:
            if _validate_emergency_code(user, emergency_code):
                login_user(user, remember=remember_me)
                TwoFactorManager._set_verified_session(user.id)
                session['emergency_access'] = True
                flash('Emergency access granted. Please set up 2FA as soon as possible.', 'warning')
                return redirect(url_for('main.dashboard'))
            else:
                flash('Invalid emergency access code.', 'danger')
                return redirect(url_for('auth.login'))
        
        # Standard login process
        login_user(user, remember=remember_me)
        
        # Check 2FA requirements
        try:
            status_check = TwoFactorManager.check_2fa_status(user)
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
            if not session.get('2fa_reminder_shown'):
                flash('Please set up two-factor authentication for enhanced security.', 'info')
                session['2fa_reminder_shown'] = True
        
        # Mark 2FA as verified if not required or trusted device
        if status_check['action'] == 'proceed':
            TwoFactorManager._set_verified_session(user.id)
        
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('main.dashboard')
        return redirect(next_page)
    
    return render_template('auth/login.html')
@bp.route('/setup-2fa', methods=['GET', 'POST'])
@login_required
def setup_2fa():
    """2FA setup page for users"""
    user_2fa = current_user.two_factor
    if not user_2fa:
        user_2fa = UserTwoFactor(user_id=current_user.id)
        db.session.add(user_2fa)
        try:
            db.session.commit()
        except Exception as e:
            current_app.logger.error(f"Error creating 2FA record: {e}")
            db.session.rollback()
            flash('Setup error. Please try again.', 'error')
            return redirect(url_for('main.dashboard'))
    
    settings = TwoFactorSettings.get_settings()
    available_methods = settings.get_available_methods()
    
    if request.method == 'POST':
        if not _validate_csrf_token(request.form.get('csrf_token')):
            flash('Security token invalid. Please try again.', 'error')
            return redirect(url_for('auth.setup_2fa'))
        
        method = _validate_input(request.form.get('method'), "text", 20)
        
        if method == 'totp':
            return redirect(url_for('auth.setup_totp'))
        elif method == 'sms':
            return redirect(url_for('auth.setup_sms'))
        elif method == 'email':
            return redirect(url_for('auth.setup_email'))
        else:
            flash('Invalid 2FA method selected.', 'error')
    
    return render_template('auth/setup_2fa.html', 
                         available_methods=available_methods,
                         user_2fa=user_2fa)

@bp.route('/setup-2fa/totp', methods=['GET', 'POST'])
@login_required
def setup_totp():
    """TOTP setup page with enhanced security"""
    user_2fa = current_user.two_factor
    if not user_2fa:
        flash('2FA setup required.', 'error')
        return redirect(url_for('auth.setup_2fa'))
    
    if request.method == 'POST':
        if not _validate_csrf_token(request.form.get('csrf_token')):
            flash('Security token invalid. Please try again.', 'error')
            return redirect(url_for('auth.setup_totp'))
        
        # Rate limiting
        rate_ok, rate_msg = TwoFactorManager._check_rate_limit(current_user.id, 'totp_setup')
        if not rate_ok:
            flash(rate_msg, 'error')
            return redirect(url_for('auth.setup_totp'))
        
        verification_code = _validate_input(request.form.get('verification_code'), "code")
        
        if not verification_code:
            flash('Please enter a valid 6-digit code.', 'error')
            return redirect(url_for('auth.setup_totp'))
        
        if user_2fa.verify_totp_code(verification_code):
            user_2fa.totp_verified = True
            user_2fa.primary_method = TwoFactorMethod.TOTP
            user_2fa.status = TwoFactorStatus.ENABLED
            
            # Generate backup codes
            backup_codes = user_2fa.generate_backup_codes()
            
            try:
                db.session.commit()
                flash('TOTP authentication setup successfully!', 'success')
                TwoFactorManager._set_verified_session(current_user.id)
                session['new_backup_codes'] = backup_codes
                return redirect(url_for('auth.backup_codes'))
            except Exception as e:
                current_app.logger.error(f"Error saving TOTP setup: {e}")
                db.session.rollback()
                flash('Setup error. Please try again.', 'error')
        else:
            flash('Invalid verification code. Please try again.', 'error')
    
    # Generate TOTP secret if not exists
    if not user_2fa.get_totp_secret():
        user_2fa.generate_totp_secret()
        try:
            db.session.commit()
        except Exception as e:
            current_app.logger.error(f"Error generating TOTP secret: {e}")
            db.session.rollback()
            flash('Setup error. Please try again.', 'error')
            return redirect(url_for('auth.setup_2fa'))
    
    qr_code = user_2fa.generate_qr_code()
    secret = user_2fa.get_totp_secret()
    
    return render_template('auth/setup_totp.html', 
                         qr_code=qr_code, 
                         secret=secret)

@bp.route('/setup-2fa/sms', methods=['GET', 'POST'])
@login_required
def setup_sms():
    """SMS 2FA setup with enhanced security"""
    user_2fa = current_user.two_factor
    if not user_2fa:
        flash('2FA setup required.', 'error')
        return redirect(url_for('auth.setup_2fa'))
    
    if request.method == 'POST':
        if not _validate_csrf_token(request.form.get('csrf_token')):
            flash('Security token invalid. Please try again.', 'error')
            return redirect(url_for('auth.setup_sms'))
        
        if 'phone_number' in request.form:
            # Step 1: Save phone number and send verification
            phone_number = _validate_input(request.form.get('phone_number'), "phone")
            
            if not phone_number:
                flash('Please enter a valid phone number.', 'error')
                return redirect(url_for('auth.setup_sms'))
            
            user_2fa.phone_number = phone_number
            try:
                db.session.commit()
            except Exception as e:
                current_app.logger.error(f"Error saving phone number: {e}")
                db.session.rollback()
                flash('Error saving phone number. Please try again.', 'error')
                return redirect(url_for('auth.setup_sms'))
            
            # Send verification code
            success, message = TwoFactorManager.send_2fa_code(current_user, 'sms')
            if success:
                session['sms_verification_step'] = 'verify'
                flash('Verification code sent to your phone.', 'info')
            else:
                flash(f'Failed to send verification code: {message}', 'error')
        
        elif 'verification_code' in request.form:
            # Step 2: Verify SMS code using secure method
            verification_code = _validate_input(request.form.get('verification_code'), "code")
            
            if not verification_code:
                flash('Please enter a valid 6-digit code.', 'error')
                return redirect(url_for('auth.setup_sms'))
            
            # Use secure verification method
            success, message = TwoFactorManager.verify_2fa_code(current_user, verification_code)
            
            if success:
                user_2fa.phone_verified = True
                user_2fa.primary_method = TwoFactorMethod.SMS
                user_2fa.status = TwoFactorStatus.ENABLED
                
                # Generate backup codes
                backup_codes = user_2fa.generate_backup_codes()
                
                try:
                    db.session.commit()
                    # Clear session data
                    session.pop('sms_verification_step', None)
                    
                    flash('SMS authentication setup successfully!', 'success')
                    TwoFactorManager._set_verified_session(current_user.id)
                    session['new_backup_codes'] = backup_codes
                    
                    return redirect(url_for('auth.backup_codes'))
                except Exception as e:
                    current_app.logger.error(f"Error completing SMS setup: {e}")
                    db.session.rollback()
                    flash('Setup error. Please try again.', 'error')
            else:
                flash(message, 'error')
    
    verification_step = session.get('sms_verification_step', 'phone')
    return render_template('auth/setup_sms.html', 
                         verification_step=verification_step,
                         phone_number=user_2fa.phone_number)

@bp.route('/setup-2fa/email', methods=['GET', 'POST'])
@login_required
def setup_email():
    """Email 2FA setup with enhanced security"""
    user_2fa = current_user.two_factor
    if not user_2fa:
        flash('2FA setup required.', 'error')
        return redirect(url_for('auth.setup_2fa'))
    
    if request.method == 'POST':
        if not _validate_csrf_token(request.form.get('csrf_token')):
            flash('Security token invalid. Please try again.', 'error')
            return redirect(url_for('auth.setup_email'))
        
        if 'send_code' in request.form:
            # Send verification code
            success, message = TwoFactorManager.send_2fa_code(current_user, 'email')
            if success:
                session['email_verification_step'] = 'verify'
                flash('Verification code sent to your email.', 'info')
            else:
                flash(f'Failed to send verification code: {message}', 'error')
        
        elif 'verification_code' in request.form:
            # Verify email code using secure method
            verification_code = _validate_input(request.form.get('verification_code'), "code")
            
            if not verification_code:
                flash('Please enter a valid 6-digit code.', 'error')
                return redirect(url_for('auth.setup_email'))
            
            # Use secure verification method
            success, message = TwoFactorManager.verify_2fa_code(current_user, verification_code)
            
            if success:
                user_2fa.email_2fa_enabled = True
                user_2fa.primary_method = TwoFactorMethod.EMAIL
                user_2fa.status = TwoFactorStatus.ENABLED
                
                # Generate backup codes
                backup_codes = user_2fa.generate_backup_codes()
                
                try:
                    db.session.commit()
                    # Clear session data
                    session.pop('email_verification_step', None)
                    
                    flash('Email authentication setup successfully!', 'success')
                    TwoFactorManager._set_verified_session(current_user.id)
                    session['new_backup_codes'] = backup_codes
                    
                    return redirect(url_for('auth.backup_codes'))
                except Exception as e:
                    current_app.logger.error(f"Error completing email setup: {e}")
                    db.session.rollback()
                    flash('Setup error. Please try again.', 'error')
            else:
                flash(message, 'error')
    
    verification_step = session.get('email_verification_step', 'send')
    return render_template('auth/setup_email.html', 
                         verification_step=verification_step,
                         user_email=current_user.email)

@bp.route('/backup-codes')
@login_required
def backup_codes():
    """Show backup codes after 2FA setup"""
    backup_codes = session.pop('new_backup_codes', None)
    if not backup_codes:
        flash('No new backup codes to display.', 'info')
        return redirect(url_for('main.dashboard'))
    
    return render_template('auth/backup_codes.html', backup_codes=backup_codes)

@bp.route('/verify-2fa', methods=['GET', 'POST'])
@login_required
def verify_2fa():
    """2FA verification page with enhanced security"""
    user_2fa = current_user.two_factor
    if not user_2fa or user_2fa.status != TwoFactorStatus.ENABLED:
        flash('2FA verification not required.', 'info')
        return redirect(url_for('main.dashboard'))
    
    # Check if already verified in this session
    if _is_2fa_verified():
        return redirect(url_for('main.dashboard'))
    
    # Check if account is locked
    if _check_account_locked(current_user):
        flash('Account temporarily locked due to multiple failed attempts.', 'error')
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        if not _validate_csrf_token(request.form.get('csrf_token')):
            flash('Security token invalid. Please try again.', 'error')
            return redirect(url_for('auth.verify_2fa'))
        
        # Rate limiting
        rate_ok, rate_msg = TwoFactorManager._check_rate_limit(current_user.id, 'verify')
        if not rate_ok:
            flash(rate_msg, 'error')
            return redirect(url_for('auth.verify_2fa'))
        
        verification_code = _validate_input(request.form.get('verification_code'), "code")
        remember_device = bool(request.form.get('remember_device'))
        use_backup = bool(request.form.get('use_backup'))
        
        if not verification_code:
            flash('Please enter a valid 6-digit code.', 'error')
            return redirect(url_for('auth.verify_2fa'))
        
        verified = False
        
        if use_backup:
            # Verify backup code
            if user_2fa.use_backup_code(verification_code):
                verified = True
                try:
                    db.session.commit()
                    flash('Backup code used successfully.', 'info')
                except Exception as e:
                    current_app.logger.error(f"Error using backup code: {e}")
                    db.session.rollback()
        else:
            # Verify with primary method
            if user_2fa.primary_method == TwoFactorMethod.TOTP:
                verified = user_2fa.verify_totp_code(verification_code)
            else:
                # Use secure verification for SMS/Email
                success, message = TwoFactorManager.verify_2fa_code(current_user, verification_code)
                verified = success
                if not success and message:
                    flash(message, 'error')
        
        if verified:
            # Mark as verified in session
            TwoFactorManager._set_verified_session(current_user.id)
            
            # Update user's last verified timestamp
            user_2fa.last_verified_at = datetime.utcnow()
            user_2fa.verification_attempts = 0
            
            try:
                db.session.commit()
            except Exception as e:
                current_app.logger.error(f"Error updating verification: {e}")
                db.session.rollback()
            
            # Create trusted device if requested
            response = make_response(redirect(url_for('main.dashboard')))
            if remember_device:
                settings = TwoFactorSettings.get_settings()
                if settings.remember_device_enabled:
                    try:
                        device_token = TrustedDevice.create_for_user(
                            current_user, 
                            request, 
                            settings.remember_device_days
                        )
                        db.session.commit()
                        response.set_cookie(
                            'trusted_device', 
                            device_token, 
                            max_age=settings.remember_device_days * 24 * 60 * 60,
                            secure=True,
                            httponly=True,
                            samesite='Strict'
                        )
                    except Exception as e:
                        current_app.logger.error(f"Error creating trusted device: {e}")
                        db.session.rollback()
            
            flash('Two-factor authentication verified successfully.', 'success')
            return response
        else:
            # Increment failed attempts
            user_2fa.verification_attempts = getattr(user_2fa, 'verification_attempts', 0) + 1
            
            # Lock account after too many failed attempts
            if user_2fa.verification_attempts >= 5:
                user_2fa.locked_until = datetime.utcnow() + timedelta(minutes=15)
                flash('Too many failed attempts. Account locked for 15 minutes.', 'error')
            else:
                flash('Invalid verification code. Please try again.', 'error')
            
            try:
                db.session.commit()
            except Exception as e:
                current_app.logger.error(f"Error recording failed attempt: {e}")
                db.session.rollback()
    
    # Send code for SMS/Email methods
    if user_2fa.primary_method in [TwoFactorMethod.SMS, TwoFactorMethod.EMAIL]:
        method_name = user_2fa.primary_method.value.lower()
        # Only send if no recent code was sent
        if not session.get(f'2fa_code_hash_{current_user.id}'):
            TwoFactorManager.send_2fa_code(current_user, method_name)
    
    settings = TwoFactorSettings.get_settings()
    return render_template('auth/verify_2fa.html', 
                         user_2fa=user_2fa,
                         settings=settings)

@bp.route('/send-2fa-code', methods=['POST'])
@login_required
def send_2fa_code():
    """AJAX endpoint to send 2FA code with security"""
    if not _validate_csrf_token(request.headers.get('X-CSRFToken')):
        return jsonify({'success': False, 'message': 'Security token invalid'}), 400
    
    method = _validate_input(request.json.get('method'), "text", 20)
    
    if method not in ['sms', 'email']:
        return jsonify({'success': False, 'message': 'Invalid method'}), 400
    
    success, message = TwoFactorManager.send_2fa_code(current_user, method)
    if success:
        return jsonify({'success': True, 'message': f'Code sent via {method}'})
    else:
        return jsonify({'success': False, 'message': message}), 500

@bp.route('/logout')
def logout():
    # Clear all 2FA session data
    TwoFactorManager.clear_2fa_session()
    logout_user()
    return redirect(url_for('auth.login'))

# 2FA Management Routes for Users

@bp.route('/manage-2fa')
@login_required
@require_2fa_setup
def manage_2fa():
    """User's 2FA management page"""
    user_2fa = current_user.two_factor
    settings = TwoFactorSettings.get_settings()
    
    # Check if user can manage 2FA (not if it's system-required)
    can_disable = not settings.is_2fa_required_for_user(current_user)
    
    trusted_devices = current_user.trusted_devices
    
    return render_template('auth/manage_2fa.html', 
                         user_2fa=user_2fa,
                         settings=settings,
                         can_disable=can_disable,
                         trusted_devices=trusted_devices)

@bp.route('/regenerate-backup-codes', methods=['POST'])
@login_required
@require_2fa_setup
def regenerate_backup_codes():
    """Regenerate backup codes for user"""
    if not _validate_csrf_token(request.headers.get('X-CSRFToken')):
        return jsonify({'success': False, 'error': 'Security token invalid'}), 400
    
    user_2fa = current_user.two_factor
    if not user_2fa or user_2fa.status != TwoFactorStatus.ENABLED:
        return jsonify({'success': False, 'error': 'No active 2FA setup found'}), 400
    
    try:
        backup_codes = user_2fa.generate_backup_codes()
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'backup_codes': backup_codes,
            'message': 'Backup codes regenerated successfully'
        })
    except Exception as e:
        current_app.logger.error(f"Error regenerating backup codes: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to regenerate codes'}), 500

@bp.route('/remove-trusted-device/<int:device_id>', methods=['POST'])
@login_required
@require_2fa_setup
def remove_trusted_device(device_id):
    """Remove a trusted device"""
    if not _validate_csrf_token(request.form.get('csrf_token')):
        flash('Security token invalid. Please try again.', 'error')
        return redirect(url_for('auth.manage_2fa'))
    
    device = TrustedDevice.query.filter_by(
        id=device_id, 
        user_id=current_user.id
    ).first_or_404()
    
    try:
        db.session.delete(device)
        db.session.commit()
        flash('Trusted device removed successfully.', 'success')
    except Exception as e:
        current_app.logger.error(f"Error removing trusted device: {e}")
        db.session.rollback()
        flash('Error removing device. Please try again.', 'error')
    
    return redirect(url_for('auth.manage_2fa'))