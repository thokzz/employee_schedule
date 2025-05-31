#!/usr/bin/env python3
import os
from app import create_app
from app.models import db, User, Section, Unit, Shift, UserRole
from flask_migrate import upgrade

app = create_app(os.getenv('FLASK_CONFIG') or 'default')

@app.shell_context_processor
def make_shell_context():
    return {'db': db, 'User': User, 'Section': Section, 'Unit': Unit, 'Shift': Shift}

@app.cli.command()
def deploy():
    """Run deployment tasks."""
    # Create database tables
    db.create_all()
    
    # Create default admin user
    admin = User.query.filter_by(username='admin').first()
    if admin is None:
        admin = User(
            username='admin',
            email='admin@company.com',
            first_name='System',
            last_name='Administrator',
            role=UserRole.ADMINISTRATOR
        )
        admin.set_password('admin123')
        db.session.add(admin)
    
    # Create sample sections and units
    section = Section.query.filter_by(name='Operations').first()
    if section is None:
        section = Section(
            name='Operations',
            description='Main operations department'
        )
        db.session.add(section)
        db.session.commit()
        
        # Create units under this section
        units = [
            Unit(name='Front Desk', description='Customer service front desk', section_id=section.id),
            Unit(name='Kitchen', description='Food preparation area', section_id=section.id),
            Unit(name='Housekeeping', description='Cleaning and maintenance', section_id=section.id)
        ]
        
        for unit in units:
            db.session.add(unit)
    
    # Create sample employees
    if User.query.filter_by(username='manager1').first() is None:
        manager = User(
            username='manager1',
            email='manager@company.com',
            first_name='Jane',
            last_name='Manager',
            role=UserRole.MANAGER,
            section_id=section.id
        )
        manager.set_password('manager123')
        db.session.add(manager)
    
    if User.query.filter_by(username='employee1').first() is None:
        employee = User(
            username='employee1',
            email='employee@company.com',
            first_name='John',
            last_name='Employee',
            role=UserRole.EMPLOYEE,
            section_id=section.id,
            unit_id=units[0].id if units else None
        )
        employee.set_password('employee123')
        db.session.add(employee)
    
    db.session.commit()
    print('Database initialized with sample data!')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
