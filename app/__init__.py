# Update your app/__init__.py to include template context

from flask import Flask
from flask_login import LoginManager
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
    
    # IMPORTANT: Add template context processor to make models available in templates
    @app.context_processor
    def inject_template_globals():
        from app.models import LeaveStatus, LeaveType, ShiftStatus
        return {
            'LeaveStatus': LeaveStatus,
            'LeaveType': LeaveType,
            'ShiftStatus': ShiftStatus
        }
    
    # Register blueprints (ADD this after your existing blueprint registrations)
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
    
    # NEW: Add this line after your existing blueprint registrations
    from app.backup import bp as backup_bp
    app.register_blueprint(backup_bp, url_prefix='/admin/backup')
    
    # Create tables and default data
    with app.app_context():
        try:
            # Create all tables
            db.create_all()
            print("✅ Database tables created successfully!")
            
            # NEW: Add backup_settings column if it doesn't exist
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS backup_settings TEXT"))
                    conn.commit()
                print("✅ Backup settings column added successfully!")
            except Exception as e:
                print(f"⚠️  Backup settings column may already exist: {e}")
            
            # ... rest of your existing initialization code ...
            
        except Exception as e:
            print(f"⚠️  Database initialization warning: {e}")
            # Try to rollback any pending transaction
            try:
                db.session.rollback()
            except:
                pass
            # Continue anyway - the app should still work
    
    return app