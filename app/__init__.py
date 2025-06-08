from flask import Flask, session, request, redirect, url_for
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_mail import Mail
from app.models import db, User, UserRole

# Initialize extensions
migrate = Migrate()
login_manager = LoginManager()
mail = Mail()

def create_app(config_name='default'):
    from config import config
    
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)
    
    # Login manager configuration
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Template context processor to make models available in templates
    @app.context_processor
    def inject_template_globals():
        from app.models import LeaveStatus, LeaveType, ShiftStatus, TwoFactorSettings
        return {
            'LeaveStatus': LeaveStatus,
            'LeaveType': LeaveType,
            'ShiftStatus': ShiftStatus,
            'TwoFactorSettings': TwoFactorSettings
        }
    
    # 2FA Global Enforcement Middleware
    @app.before_request
    def enforce_2fa():
        """Global 2FA enforcement middleware"""
        # Skip 2FA checks for auth routes, static files, and API endpoints that don't need it
        exempt_endpoints = [
            'auth.login', 'auth.logout', 'auth.setup_2fa', 'auth.setup_totp', 
            'auth.setup_sms', 'auth.setup_email', 'auth.verify_2fa', 
            'auth.backup_codes', 'auth.send_2fa_code', 'static'
        ]
        
        # Skip for static files and exempt endpoints
        if (request.endpoint in exempt_endpoints or 
            request.endpoint is None or 
            request.endpoint.startswith('static')):
            return
        
        # Skip if user is not authenticated
        if not current_user.is_authenticated:
            return
        
        # Skip for admin emergency routes (allow admins to manage 2FA settings)
        if (current_user.can_admin() and 
            request.endpoint in ['admin.two_factor_settings', 'admin.emergency_2fa_action']):
            return
        
        # Check 2FA requirements
        try:
            from app.models import TwoFactorSettings, TwoFactorStatus
            settings = TwoFactorSettings.get_settings()
            
            # If 2FA is required for this user, enforce verification
            if settings.is_2fa_required_for_user(current_user):
                if not _is_2fa_verified_global():
                    user_2fa = current_user.two_factor
                    
                    # Redirect to setup if needed
                    if (not user_2fa or 
                        user_2fa.status in [TwoFactorStatus.DISABLED, TwoFactorStatus.PENDING_SETUP] or
                        (user_2fa.status == TwoFactorStatus.GRACE_PERIOD and not user_2fa.is_in_grace_period())):
                        return redirect(url_for('auth.setup_2fa'))
                    
                    # Redirect to verification if setup is complete but not verified
                    elif user_2fa.status == TwoFactorStatus.ENABLED:
                        return redirect(url_for('auth.verify_2fa'))
        except ImportError:
            # 2FA models not available yet (during migration)
            pass
        except Exception as e:
            app.logger.error(f"2FA enforcement error: {e}")
    
    def _is_2fa_verified_global():
        """Global helper to check 2FA verification status"""
        if not current_user.is_authenticated:
            return False
        
        # Check session verification
        if (session.get('2fa_verified') and 
            session.get('2fa_user_id') == current_user.id):
            return True
        
        # Check trusted device
        device_token = request.cookies.get('trusted_device')
        try:
            if current_user.can_skip_2fa(device_token):
                session['2fa_verified'] = True
                session['2fa_user_id'] = current_user.id
                return True
        except AttributeError:
            # Method doesn't exist yet (during migration)
            pass
        
        return False
    
    # Register blueprints
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    
    from app.main import bp as main_bp
    app.register_blueprint(main_bp)
    
    from app.work_extension import bp as work_extension_bp
    app.register_blueprint(work_extension_bp)

    from app.schedule import bp as schedule_bp
    app.register_blueprint(schedule_bp, url_prefix='/schedule')
    
    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')
    
    from app.leave import bp as leave_bp
    app.register_blueprint(leave_bp, url_prefix='/leave')
    
    from app.backup import bp as backup_bp
    app.register_blueprint(backup_bp, url_prefix='/admin/backup')
    
    from app.analytics import bp as analytics_bp
    app.register_blueprint(analytics_bp, url_prefix='/analytics')

    # Create tables and default data
    with app.app_context():
        try:
            # Create all tables
            db.create_all()
            print("✅ Database tables created successfully!")
            
            # Add backup_settings column if it doesn't exist
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS backup_settings TEXT"))
                    conn.commit()
                print("✅ Backup settings column added successfully!")
            except Exception as e:
                print(f"⚠️  Backup settings column may already exist: {e}")
            
            # Initialize 2FA settings if they don't exist
            try:
                from app.models import TwoFactorSettings
                if not TwoFactorSettings.query.first():
                    default_settings = TwoFactorSettings()
                    db.session.add(default_settings)
                    db.session.commit()
                    print("✅ Default 2FA settings created!")
            except Exception as e:
                print(f"⚠️  2FA settings initialization: {e}")
                
        except Exception as e:
            print(f"⚠️  Database initialization warning: {e}")
            try:
                db.session.rollback()
            except:
                pass
    
    return app