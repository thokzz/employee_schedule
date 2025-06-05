from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from enum import Enum
import uuid
import json

db = SQLAlchemy()

class UserRole(Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    ADMINISTRATOR = "administrator"

class EmployeeType(Enum):
    RANK_AND_FILE = "rank_and_file"
    RANK_AND_FILE_PROBATIONARY = "rank_and_file_probationary"
    CONFIDENTIAL = "confidential"
    CONFIDENTIAL_PROBATIONARY = "confidential_probationary"
    CONTRACTUAL = "contractual"

class ScheduleFormat(Enum):
    EIGHT_HOUR = "8_hour_shift"
    NINE_HOUR = "9_hour_shift"
    OTHERS = "others"

class WorkArrangement(Enum):
    WFH = "wfh"
    ONSITE = "onsite"
    HYBRID = "hybrid"
    OB = "ob"

class ShiftStatus(Enum):
    SCHEDULED = "scheduled"
    REST_DAY = "rest_day"
    SICK_LEAVE = "sick_leave"
    PERSONAL_LEAVE = "personal_leave"
    EMERGENCY_LEAVE = "emergency_leave"
    ANNUAL_VACATION = "annual_vacation"
    HOLIDAY_OFF = "holiday_off"
    OFFSET = "offset"
    BEREAVEMENT_LEAVE = "bereavement_leave"
    PATERNITY_LEAVE = "paternity_leave"
    MATERNITY_LEAVE = "maternity_leave"
    UNION_LEAVE = "union_leave"
    FIRE_CALAMITY_LEAVE = "fire_calamity_leave"
    SOLO_PARENT_LEAVE = "solo_parent_leave"
    SPECIAL_LEAVE_WOMEN = "special_leave_women"
    VAWC_LEAVE = "vawc_leave"
    OTHER = "other"

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.Enum(UserRole, name='user_role'), default=UserRole.EMPLOYEE, nullable=False)
    avatar = db.Column(db.String(200), default='default_avatar.png')
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Employment fields
    personnel_number = db.Column(db.String(50), unique=True, nullable=True, index=True)
    typecode = db.Column(db.String(20), nullable=True)
    id_number = db.Column(db.String(50), nullable=True)
    hiring_date = db.Column(db.Date, nullable=True)
    job_title = db.Column(db.String(100), nullable=True)
    rank = db.Column(db.String(50), nullable=True)
    div_department = db.Column(db.String(100), nullable=True)
    signature = db.Column(db.String(255), nullable=True)
    
    # Employee type and schedule format
    employee_type = db.Column(db.Enum(EmployeeType, name='employee_type'), nullable=True)
    schedule_format = db.Column(db.Enum(ScheduleFormat, name='schedule_format'), nullable=True)
    
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships with foreign keys
    section_id = db.Column(db.Integer, db.ForeignKey('sections.id'), nullable=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=True)
  
    # FIXED: Approver fields
    is_section_approver = db.Column(db.Boolean, default=False, nullable=False)
    is_unit_approver = db.Column(db.Boolean, default=False, nullable=False)

    # 4-Level Hierarchy foreign keys
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    division_id = db.Column(db.Integer, db.ForeignKey('divisions.id'), nullable=True)
    
    # 4-Level Hierarchy approver fields
    is_department_approver = db.Column(db.Boolean, default=False, nullable=False)
    is_division_approver = db.Column(db.Boolean, default=False, nullable=False)
    
    contact_number = db.Column(db.String(50), nullable=True)

    # Relationships
    shifts = db.relationship('Shift', backref='employee', lazy='dynamic', 
                           foreign_keys='Shift.employee_id',
                           cascade='all, delete-orphan')
    leave_requests = db.relationship('LeaveRequest', backref='employee', lazy='dynamic',
                                   foreign_keys='LeaveRequest.employee_id',
                                   cascade='all, delete-orphan')
    reviewed_requests = db.relationship('LeaveRequest', backref='reviewer', lazy='dynamic',
                                      foreign_keys='LeaveRequest.reviewed_by')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def can_approve_leaves(self):
        """FIXED: Check if user can approve leave applications"""
        # Administrators can approve all leaves
        if self.role == UserRole.ADMINISTRATOR:
            return True
        
        # Managers can approve leaves
        if self.role == UserRole.MANAGER:
            return True
            
        # Section approvers can approve leaves
        if self.is_section_approver:
            return True
            
        # Unit approvers can approve leaves  
        if self.is_unit_approver:
            return True
            
        return False
    
    def get_approvable_employees(self):
        """FIXED: Get list of employees whose leave this user can approve"""
        if self.can_admin():
            # Administrators can approve for all active employees
            return User.query.filter_by(is_active=True).all()
        
        employees = set()  # Use set to avoid duplicates
        
        # Section approvers can approve for all employees in the same section
        if self.is_section_approver and self.section_id:
            section_employees = User.query.filter_by(
                section_id=self.section_id, 
                is_active=True
            ).all()
            employees.update(section_employees)
        
        # Unit approvers can approve for employees in the same unit
        if self.is_unit_approver and self.unit_id:
            unit_employees = User.query.filter_by(
                unit_id=self.unit_id, 
                is_active=True
            ).all()
            employees.update(unit_employees)
        
        # Managers can approve for employees in their section/unit
        if self.role == UserRole.MANAGER:
            if self.section_id:
                manager_section_employees = User.query.filter_by(
                    section_id=self.section_id,
                    is_active=True
                ).all()
                employees.update(manager_section_employees)
            elif self.unit_id:
                manager_unit_employees = User.query.filter_by(
                    unit_id=self.unit_id,
                    is_active=True
                ).all()
                employees.update(manager_unit_employees)
        
        return list(employees)
    
    @property
    def approver_scope(self):
        """FIXED: Get the scope of approval authority"""
        if self.can_admin():
            return "All Employees"
        
        scopes = []
        
        if self.is_section_approver and self.section:
            scopes.append(f"{self.section.name} Section")
        
        if self.is_unit_approver and self.unit:
            scopes.append(f"{self.unit.name} Unit")
            
        if self.role == UserRole.MANAGER:
            if self.section:
                scopes.append(f"{self.section.name} (Manager)")
            elif self.unit:
                scopes.append(f"{self.unit.name} (Manager)")
        
        if scopes:
            return " + ".join(scopes)
        else:
            return "None"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def initials(self):
        return f"{self.first_name[0]}{self.last_name[0]}".upper()
    
    @property
    def years_of_service(self):
        """Calculate years of service if hiring_date is set"""
        if self.hiring_date:
            today = date.today()
            return today.year - self.hiring_date.year - ((today.month, today.day) < (self.hiring_date.month, self.hiring_date.day))
        return None
    
    @property
    def is_probationary(self):
        """Check if employee is probationary based on employee_type or other criteria"""
        if self.employee_type and 'probationary' in self.employee_type.value.lower():
            return True
        
        if self.rank and 'probationary' in self.rank.lower():
            return True
        
        if self.hiring_date:
            months_employed = (date.today() - self.hiring_date).days / 30.44
            if months_employed < 6:
                return True
        
        if self.typecode and 'PROB' in self.typecode.upper():
            return True
            
        return False

    @property 
    def night_differential_start_hour(self):
        """Get the start hour for night differential based on employee status"""
        return 20 if not self.is_probationary else 22

    @property
    def night_differential_end_hour(self):
        """Get the end hour for night differential"""
        return 6

    def can_edit_schedule(self):
        return self.role in [UserRole.MANAGER, UserRole.ADMINISTRATOR]
    
    def can_file_work_extension(self):
        """Check if user can file work extensions (confidential employees only)"""
        return (self.employee_type in [EmployeeType.CONFIDENTIAL, EmployeeType.CONFIDENTIAL_PROBATIONARY] 
                and self.is_active)

    def can_admin(self):
        return self.role == UserRole.ADMINISTRATOR
    
    def get_break_duration_minutes(self):
        """Get break duration in minutes based on schedule format"""
        if self.schedule_format == ScheduleFormat.EIGHT_HOUR:
            return 30
        elif self.schedule_format == ScheduleFormat.NINE_HOUR:
            return 60
        else:
            return 30
    
    def __repr__(self):
        return f'<User {self.username}>'

class Section(db.Model):
    __tablename__ = 'sections'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    units = db.relationship('Unit', backref='section', lazy='dynamic', cascade='all, delete-orphan')
    users = db.relationship('User', backref='section', lazy='dynamic')
    division_id = db.Column(db.Integer, db.ForeignKey('divisions.id'), nullable=True)
    
    def __repr__(self):
        return f'<Section {self.name}>'

class Unit(db.Model):
    __tablename__ = 'units'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    section_id = db.Column(db.Integer, db.ForeignKey('sections.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint for name within section
    __table_args__ = (db.UniqueConstraint('name', 'section_id', name='unique_unit_per_section'),)
    
    # Relationships
    users = db.relationship('User', backref='unit', lazy='dynamic')
    
    def __repr__(self):
        return f'<Unit {self.name}>'

# Include all other models (Shift, LeaveRequest, etc.) - keeping them the same
class Shift(db.Model):
    __tablename__ = 'shifts'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    role = db.Column(db.String(100), nullable=True)
    status = db.Column(db.Enum(ShiftStatus, name='shift_status'), default=ShiftStatus.SCHEDULED)
    notes = db.Column(db.Text)
    color = db.Column(db.String(7), default='#007bff')
    work_arrangement = db.Column(db.Enum(WorkArrangement, name='work_arrangement'), default=WorkArrangement.ONSITE, nullable=True)
    sequence = db.Column(db.Integer, default=1, nullable=False)
    
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        db.Index('idx_shifts_date_employee', 'date', 'employee_id'),
        db.Index('idx_shifts_employee_date_sequence', 'employee_id', 'date', 'sequence'),
    )
    
    @property
    def time_display(self):
        if self.start_time and self.end_time:
            return f"{self.start_time.strftime('%I:%M%p').lower()}-{self.end_time.strftime('%I:%M%p').lower()}"
        return "No time set"
    
    @property
    def duration_hours(self):
        """Calculate shift duration in hours"""
        if self.start_time and self.end_time:
            start_datetime = datetime.combine(date.today(), self.start_time)
            end_datetime = datetime.combine(date.today(), self.end_time)
            
            if end_datetime < start_datetime:
                end_datetime += timedelta(days=1)
            
            duration = end_datetime - start_datetime
            return duration.total_seconds() / 3600
        return 0
    
    @property
    def qualifies_for_break(self):
        """Check if shift qualifies for a break (minimum 4 hours)"""
        return self.duration_hours >= 4.0
    
    @property
    def status_color(self):
        color_map = {
            ShiftStatus.SCHEDULED: '#007bff',
            ShiftStatus.REST_DAY: '#6c757d',
            ShiftStatus.SICK_LEAVE: '#dc3545',
            ShiftStatus.PERSONAL_LEAVE: '#ffc107',
            ShiftStatus.EMERGENCY_LEAVE: '#fd7e14',
            ShiftStatus.ANNUAL_VACATION: '#20c997',
            ShiftStatus.HOLIDAY_OFF: '#6f42c1',
            ShiftStatus.OFFSET: '#e83e8c',
            ShiftStatus.BEREAVEMENT_LEAVE: '#495057',
            ShiftStatus.PATERNITY_LEAVE: '#0dcaf0',
            ShiftStatus.MATERNITY_LEAVE: '#f8d7da',
            ShiftStatus.UNION_LEAVE: '#d1ecf1',
            ShiftStatus.FIRE_CALAMITY_LEAVE: '#ff6b6b',
            ShiftStatus.SOLO_PARENT_LEAVE: '#4ecdc4',
            ShiftStatus.SPECIAL_LEAVE_WOMEN: '#ff9ff3',
            ShiftStatus.VAWC_LEAVE: '#a8e6cf',
            ShiftStatus.OTHER: '#dee2e6'
        }
        return color_map.get(self.status, '#007bff')
    
    def __repr__(self):
        return f'<Shift {self.employee.username} on {self.date} #{self.sequence}>'

class Department(db.Model):
    """Top-level organizational unit in 4-level hierarchy"""
    __tablename__ = 'departments'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    divisions = db.relationship('Division', backref='department', lazy='dynamic', cascade='all, delete-orphan')
    users = db.relationship('User', backref='department', lazy='dynamic')
    
    def __repr__(self):
        return f'<Department {self.name}>'

class Division(db.Model):
    """Second-level organizational unit in 4-level hierarchy"""
    __tablename__ = 'divisions'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint for name within department
    __table_args__ = (db.UniqueConstraint('name', 'department_id', name='unique_division_per_department'),)
    
    # Relationships
    sections = db.relationship('Section', backref='division', lazy='dynamic', cascade='all, delete-orphan')
    users = db.relationship('User', backref='division', lazy='dynamic')
    
    def __repr__(self):
        return f'<Division {self.name}>'

class LeaveRequest(db.Model):
    __tablename__ = 'leave_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    leave_type = db.Column(db.Enum(ShiftStatus, name='leave_type'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime(timezone=True))
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    def __repr__(self):
        return f'<LeaveRequest {self.employee.username} - {self.leave_type.value}>'

class ScheduleTemplate(db.Model):
    __tablename__ = 'schedule_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    template_data = db.Column(db.JSON)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    creator = db.relationship('User', backref='templates')
    
    def __repr__(self):
        return f'<ScheduleTemplate {self.name}>'

class EmailSettings(db.Model):
    __tablename__ = 'email_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    mail_server = db.Column(db.String(100), nullable=True)
    mail_port = db.Column(db.Integer, default=587)
    mail_use_tls = db.Column(db.Boolean, default=True)
    mail_username = db.Column(db.String(100), nullable=True)
    mail_password = db.Column(db.String(255), nullable=True)
    mail_default_sender = db.Column(db.String(100), nullable=True)
    
    notify_schedule_changes = db.Column(db.Boolean, default=True)
    notify_new_users = db.Column(db.Boolean, default=True)
    notify_leave_requests = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @classmethod
    def get_settings(cls):
        """Get the current email settings (create default if none exist)"""
        settings = cls.query.first()
        if not settings:
            settings = cls()
            db.session.add(settings)
            db.session.commit()
        return settings
    
    def to_dict(self):
        """Convert settings to dictionary for JSON response"""
        return {
            'mail_server': self.mail_server,
            'mail_port': self.mail_port,
            'mail_use_tls': self.mail_use_tls,
            'mail_username': self.mail_username,
            'mail_default_sender': self.mail_default_sender,
            'notify_schedule_changes': self.notify_schedule_changes,
            'notify_new_users': self.notify_new_users,
            'notify_leave_requests': self.notify_leave_requests
        }
    
    def __repr__(self):
        return f'<EmailSettings {self.mail_server}>'

class AppSettings(db.Model):
    """Application-wide settings model"""
    __tablename__ = 'app_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # External URL settings
    external_url = db.Column(db.String(255), nullable=True)
    app_name = db.Column(db.String(100), default='Employee Scheduling System')
    app_description = db.Column(db.Text, nullable=True)
    
    # Email template settings
    email_footer_text = db.Column(db.Text, nullable=True)
    company_name = db.Column(db.String(100), nullable=True)
    company_logo_url = db.Column(db.String(255), nullable=True)
    
    # Security settings
    session_timeout_minutes = db.Column(db.Integer, default=480)  # 8 hours
    max_login_attempts = db.Column(db.Integer, default=5)
    
    # Features toggles
    enable_leave_requests = db.Column(db.Boolean, default=True)
    enable_schedule_export = db.Column(db.Boolean, default=True)
    enable_user_registration = db.Column(db.Boolean, default=False)
    
    # NEW: Add this line to your existing AppSettings class
    backup_settings = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @classmethod
    def get_settings(cls):
        """Get the current app settings (create default if none exist)"""
        settings = cls.query.first()
        if not settings:
            settings = cls()
            db.session.add(settings)
            db.session.commit()
        return settings
    
    @property
    def base_url(self):
        """Get the base URL for the application"""
        if self.external_url:
            return self.external_url.rstrip('/')
        return 'http://localhost:5000'  # Fallback
    
    def get_full_url(self, path=''):
        """Get a full URL by combining base URL with path"""
        base = self.base_url
        if path:
            if not path.startswith('/'):
                path = '/' + path
            return base + path
        return base
    
    def to_dict(self):
        """Convert settings to dictionary for JSON response - UPDATE this method"""
        return {
            'external_url': self.external_url,
            'app_name': self.app_name,
            'app_description': self.app_description,
            'email_footer_text': self.email_footer_text,
            'company_name': self.company_name,
            'company_logo_url': self.company_logo_url,
            'session_timeout_minutes': self.session_timeout_minutes,
            'max_login_attempts': self.max_login_attempts,
            'enable_leave_requests': self.enable_leave_requests,
            'enable_schedule_export': self.enable_schedule_export,
            'enable_user_registration': self.enable_user_registration,
            'backup_settings': self.backup_settings  # ADD this line to existing to_dict method
        }
    
    def __repr__(self):
        return f'<AppSettings {self.app_name}>'

class DateRemarkType(Enum):
    HOLIDAY = "holiday"
    SPECIAL_DAY = "special_day"
    NOTICE = "notice"
    OTHER = "other"

class DateRemark(db.Model):
    """Model for storing remarks on specific dates (holidays, special days, etc.)"""
    __tablename__ = 'date_remarks'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True, index=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    remark_type = db.Column(db.Enum(DateRemarkType), nullable=False, default=DateRemarkType.HOLIDAY)
    color = db.Column(db.String(7), default='#dc3545')
    is_work_day = db.Column(db.Boolean, default=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    created_by = db.relationship('User', backref='date_remarks_created')
    
    def __repr__(self):
        return f'<DateRemark {self.date}: {self.title}>'
    
    @property
    def display_name(self):
        """Get display name for the remark"""
        return self.title
    
    @property
    def badge_class(self):
        """Get CSS class for badge display"""
        type_classes = {
            DateRemarkType.HOLIDAY: 'badge-danger',
            DateRemarkType.SPECIAL_DAY: 'badge-info',
            DateRemarkType.NOTICE: 'badge-warning',
            DateRemarkType.OTHER: 'badge-secondary'
        }
        return type_classes.get(self.remark_type, 'badge-secondary')
    
    @classmethod
    def get_remarks_for_period(cls, start_date, end_date):
        """Get all remarks for a date range"""
        return cls.query.filter(
            cls.date.between(start_date, end_date)
        ).all()
    
    @classmethod
    def get_remark_for_date(cls, date):
        """Get remark for a specific date"""
        return cls.query.filter_by(date=date).first()
    
    def to_dict(self):
        """Convert to dictionary for JSON responses"""
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'title': self.title,
            'description': self.description,
            'remark_type': self.remark_type.value,
            'color': self.color,
            'is_work_day': self.is_work_day,
            'display_name': self.display_name,
            'badge_class': self.badge_class
        }

class LeaveType(Enum):
    ANNUAL_VACATION = "Annual Vacation Leave"
    EMERGENCY_LEAVE = "Emergency Leave"
    PERSONAL_LEAVE = "Personal Leave"
    MATERNITY_LEAVE = "Maternity Leave"
    BEREAVEMENT_LEAVE = "Bereavement Leave"
    UNION_LEAVE = "Union Leave"
    SICK_LEAVE = "Sick Leave"
    PATERNITY_LEAVE = "Paternity Leave"
    FIRE_CALAMITY_LEAVE = "Fire/Calamity Leave"
    SOLO_PARENT_LEAVE = "Solo Parent Leave"
    VAWC_LEAVE = "VAWC Leave"
    OTHER = "Other"

class LeaveStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DISAPPROVED = "disapproved"
    CANCELLED = "cancelled"

class LeaveApplication(db.Model):
    """Leave Application Form (ALAF) Model"""
    __tablename__ = 'leave_applications'
    
    id = db.Column(db.Integer, primary_key=True)
    reference_code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    
    # Employee Information
    employee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    employee_name = db.Column(db.String(200), nullable=False)
    employee_idno = db.Column(db.String(50), nullable=True)
    employee_email = db.Column(db.String(120), nullable=True)
    employee_contact = db.Column(db.String(50), nullable=True)
    employee_unit = db.Column(db.String(100), nullable=True)
    employee_signature_path = db.Column(db.String(200), nullable=True)
    
    # Leave Details
    leave_type = db.Column(db.Enum(LeaveType), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    date_filed = db.Column(db.Date, nullable=False, default=date.today)
    
    # Leave Dates/Times
    start_date = db.Column(db.String(500), nullable=False)
    end_date = db.Column(db.String(500), nullable=True)
    total_days = db.Column(db.Float, nullable=True)
    is_hours_based = db.Column(db.Boolean, default=False, nullable=False)
    
    # Approver Information
    approver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    approver_name = db.Column(db.String(200), nullable=False)
    approver_email = db.Column(db.String(120), nullable=True)
    approver_signature_path = db.Column(db.String(200), nullable=True)
    
    # Status and Dates
    status = db.Column(db.Enum(LeaveStatus), default=LeaveStatus.PENDING, nullable=False)
    date_reviewed = db.Column(db.DateTime(timezone=True), nullable=True)
    reviewer_comments = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    employee = db.relationship('User', foreign_keys=[employee_id], backref='leave_applications_filed')
    approver = db.relationship('User', foreign_keys=[approver_id], backref='leave_applications_to_review')
    
    def __repr__(self):
        return f'<LeaveApplication {self.reference_code} - {self.employee_name}>'
    
    @property
    def status_color(self):
        color_map = {
            LeaveStatus.PENDING: '#ffc107',
            LeaveStatus.APPROVED: '#198754',
            LeaveStatus.DISAPPROVED: '#dc3545',
            LeaveStatus.CANCELLED: '#6c757d'
        }
        return color_map.get(self.status, '#6c757d')
    
    @property
    def days_pending(self):
        """Calculate days since application was filed"""
        if self.status == LeaveStatus.PENDING:
            return (datetime.utcnow().date() - self.date_filed).days
        return None
    
    @classmethod
    def generate_reference_code(cls):
        """Generate unique reference code"""
        import random
        import string
        
        while True:
            code = 'LV-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
            if not cls.query.filter_by(reference_code=code).first():
                return code
    
    def parse_leave_dates(self):
        """Parse the start_date field to extract individual dates"""
        dates = []
        start_date_str = self.start_date.strip()
        
        if self.is_hours_based:
            parts = start_date_str.split(' ')
            if len(parts) >= 1:
                date_part = parts[0]
                try:
                    parsed_date = datetime.strptime(date_part, '%m/%d/%Y').date()
                    dates.append(parsed_date)
                except ValueError:
                    pass
        elif '(' in start_date_str and ')' in start_date_str:
            date_parts = start_date_str.split(',')
            for part in date_parts:
                date_part = part.split('(')[0].strip()
                try:
                    parsed_date = datetime.strptime(date_part, '%m/%d/%Y').date()
                    dates.append(parsed_date)
                except ValueError:
                    continue
        else:
            try:
                parsed_date = datetime.strptime(start_date_str, '%m/%d/%Y').date()
                if self.total_days and self.total_days > 1:
                    for i in range(int(self.total_days)):
                        dates.append(parsed_date + timedelta(days=i))
                else:
                    dates.append(parsed_date)
            except ValueError:
                pass
        
        return dates
    
    def to_dict(self):
        """Convert to dictionary for JSON responses"""
        return {
            'id': self.id,
            'reference_code': self.reference_code,
            'employee_name': self.employee_name,
            'employee_email': self.employee_email,
            'leave_type': self.leave_type.value,
            'reason': self.reason,
            'start_date': self.start_date,
            'total_days': self.total_days,
            'is_hours_based': self.is_hours_based,
            'status': self.status.value,
            'status_color': self.status_color,
            'date_filed': self.date_filed.isoformat(),
            'date_reviewed': self.date_reviewed.isoformat() if self.date_reviewed else None,
            'days_pending': self.days_pending,
            'approver_name': self.approver_name,
            'reviewer_comments': self.reviewer_comments
        }

class WorkExtensionStatus(Enum):
    PENDING = 'pending'
    APPROVED = 'approved'
    DISAPPROVED = 'disapproved'

class WorkExtension(db.Model):
    """Work Extension model for confidential employees"""
    __tablename__ = 'work_extensions'
    
    id = db.Column(db.Integer, primary_key=True)
    reference_code = db.Column(db.String(20), unique=True, nullable=False)
    
    # Employee Information
    employee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    employee_name = db.Column(db.String(100), nullable=False)
    employee_email = db.Column(db.String(120))
    employee_contact = db.Column(db.String(20))
    employee_section = db.Column(db.String(100))
    employee_signature_path = db.Column(db.String(255))
    
    # Work Extension Details
    extension_date = db.Column(db.Date, nullable=False)
    shift_start = db.Column(db.Time)
    shift_end = db.Column(db.Time)
    actual_time_in = db.Column(db.Time)
    actual_time_out = db.Column(db.Time)
    extended_from = db.Column(db.Time)
    extended_to = db.Column(db.Time)
    extension_hours = db.Column(db.Float)  # Calculated extension hours
    reason = db.Column(db.Text, nullable=False)
    
    # Approver Information
    approver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    approver_name = db.Column(db.String(100), nullable=False)
    approver_email = db.Column(db.String(120))
    approver_signature_path = db.Column(db.String(255))
    
    # Status and Dates
    status = db.Column(db.Enum(WorkExtensionStatus), default=WorkExtensionStatus.PENDING)
    date_filed = db.Column(db.Date, default=date.today)
    date_reviewed = db.Column(db.DateTime)
    reviewer_comments = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    employee = db.relationship('User', foreign_keys=[employee_id], backref='work_extensions')
    approver = db.relationship('User', foreign_keys=[approver_id], backref='approved_work_extensions')
    
    @staticmethod
    def generate_reference_code():
        """Generate unique reference code for work extension"""
        return f"WE-{uuid.uuid4().hex[:8].upper()}"
    
    @property
    def status_color(self):
        """Return color for status badge"""
        colors = {
            WorkExtensionStatus.PENDING: '#ffc107',
            WorkExtensionStatus.APPROVED: '#198754',
            WorkExtensionStatus.DISAPPROVED: '#dc3545'
        }
        return colors.get(self.status, '#6c757d')
    
    @property
    def days_pending(self):
        """Calculate days since filing"""
        if self.status != WorkExtensionStatus.PENDING:
            return None
        return (date.today() - self.date_filed).days
    
    def calculate_extension_hours(self):
        """Calculate total extension hours"""
        if self.extended_from and self.extended_to:
            # Create datetime objects for calculation
            from_time = datetime.combine(date.today(), self.extended_from)
            to_time = datetime.combine(date.today(), self.extended_to)
            
            # Handle next day extension
            if to_time <= from_time:
                to_time = datetime.combine(date.today() + timedelta(days=1), self.extended_to)
            
            duration = (to_time - from_time).total_seconds() / 3600
            self.extension_hours = round(duration, 2)
            return self.extension_hours
        return 0
    
    def to_dict(self):
        """Convert to dictionary for JSON responses"""
        return {
            'id': self.id,
            'reference_code': self.reference_code,
            'employee_name': self.employee_name,
            'employee_email': self.employee_email,
            'employee_contact': self.employee_contact,
            'employee_section': self.employee_section,
            'extension_date': self.extension_date.isoformat() if self.extension_date else None,
            'shift_start': self.shift_start.strftime('%H:%M') if self.shift_start else None,
            'shift_end': self.shift_end.strftime('%H:%M') if self.shift_end else None,
            'actual_time_in': self.actual_time_in.strftime('%H:%M') if self.actual_time_in else None,
            'actual_time_out': self.actual_time_out.strftime('%H:%M') if self.actual_time_out else None,
            'extended_from': self.extended_from.strftime('%H:%M') if self.extended_from else None,
            'extended_to': self.extended_to.strftime('%H:%M') if self.extended_to else None,
            'extension_hours': self.extension_hours,
            'reason': self.reason,
            'approver_name': self.approver_name,
            'approver_email': self.approver_email,
            'status': self.status.value,
            'status_color': self.status_color,
            'date_filed': self.date_filed.isoformat() if self.date_filed else None,
            'date_reviewed': self.date_reviewed.isoformat() if self.date_reviewed else None,
            'reviewer_comments': self.reviewer_comments,
            'days_pending': self.days_pending
        }