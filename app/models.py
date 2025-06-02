from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
from enum import Enum
import json

db = SQLAlchemy()

class UserRole(Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    ADMINISTRATOR = "administrator"

class EmployeeType(Enum):
    CONFIDENTIAL = "confidential"
    RANK_AND_FILE = "rank_and_file"
    CONTRACTUAL = "contractual"

class ScheduleFormat(Enum):
    EIGHT_HOUR = "8_hour_shift"
    NINE_HOUR = "9_hour_shift"
    OTHERS = "others"

class WorkArrangement(Enum):
    WFH = "wfh"
    ONSITE = "onsite"
    HYBRID = "hybrid"
    OB = "ob"  # Official Business

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
    __tablename__ = 'users'  # Explicit table name for PostgreSQL
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)  # Increased length for PostgreSQL
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.Enum(UserRole, name='user_role'), default=UserRole.EMPLOYEE, nullable=False)
    avatar = db.Column(db.String(200), default='default_avatar.png')
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # UPDATED: Additional user profile fields
    personnel_number = db.Column(db.String(50), unique=True, nullable=True, index=True)
    typecode = db.Column(db.String(20), nullable=True)
    id_number = db.Column(db.String(50), nullable=True)
    hiring_date = db.Column(db.Date, nullable=True)
    job_title = db.Column(db.String(100), nullable=True)
    rank = db.Column(db.String(50), nullable=True)
    
    # NEW: Employee type and schedule format
    employee_type = db.Column(db.Enum(EmployeeType, name='employee_type'), default=EmployeeType.RANK_AND_FILE, nullable=True)
    schedule_format = db.Column(db.Enum(ScheduleFormat, name='schedule_format'), default=ScheduleFormat.EIGHT_HOUR, nullable=True)
    
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships with foreign keys
    section_id = db.Column(db.Integer, db.ForeignKey('sections.id'), nullable=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=True)
    
    # Explicit relationships with foreign_keys
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
    
    def can_edit_schedule(self):
        return self.role in [UserRole.MANAGER, UserRole.ADMINISTRATOR]
    
    def can_admin(self):
        return self.role == UserRole.ADMINISTRATOR
    
    def get_break_duration_minutes(self):
        """Get break duration in minutes based on schedule format"""
        if self.schedule_format == ScheduleFormat.EIGHT_HOUR:
            return 30  # 30 minutes for 8-hour shift
        elif self.schedule_format == ScheduleFormat.NINE_HOUR:
            return 60  # 1 hour for 9-hour shift
        else:
            return 30  # Default to 30 minutes for 'others'
    
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
    
    # NEW: Work arrangement field
    work_arrangement = db.Column(db.Enum(WorkArrangement, name='work_arrangement'), default=WorkArrangement.ONSITE, nullable=True)
    
    # Add sequence/order for multiple shifts per day
    sequence = db.Column(db.Integer, default=1, nullable=False)
    
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Remove unique constraint, allow multiple shifts per day
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
            
            # Handle shifts that cross midnight
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

class LeaveRequest(db.Model):
    __tablename__ = 'leave_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    leave_type = db.Column(db.Enum(ShiftStatus, name='leave_type'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
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
    template_data = db.Column(db.JSON)  # PostgreSQL native JSON support
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    creator = db.relationship('User', backref='templates')
    
    def __repr__(self):
        return f'<ScheduleTemplate {self.name}>'