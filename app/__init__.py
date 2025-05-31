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
    
    # Register blueprints
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    
    from app.main import bp as main_bp
    app.register_blueprint(main_bp)
    
    from app.schedule import bp as schedule_bp
    app.register_blueprint(schedule_bp, url_prefix='/schedule')
    
    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')
    
    # Create tables and default data
    with app.app_context():
        try:
            # Create all tables
            db.create_all()
            print("✅ Database tables created successfully!")
            
            # Check if admin user exists
            admin_user = User.query.filter_by(username='admin').first()
            if not admin_user:
                print("👤 Creating default admin user...")
                admin_user = User(
                    username='admin',
                    email='admin@company.com',
                    first_name='System',
                    last_name='Administrator',
                    role=UserRole.ADMINISTRATOR
                )
                admin_user.set_password('admin123')
                db.session.add(admin_user)
                db.session.commit()
                print("✅ Default admin user created successfully!")
            else:
                print("👤 Admin user already exists, skipping creation.")
                
        except Exception as e:
            print(f"⚠️  Database initialization warning: {e}")
            # Try to rollback any pending transaction
            try:
                db.session.rollback()
            except:
                pass
            # Continue anyway - the app should still work
    
    return app
