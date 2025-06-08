from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta, timezone
from enum import Enum
import uuid
import json
import pyotp
import secrets
import hashlib
import qrcode
import io
import base64
from cryptography.fernet import Fernet
import os
from sqlalchemy import text



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

class TwoFactorMethod(Enum):
    TOTP = "totp"
    SMS = "sms"
    EMAIL = "email"

class TwoFactorStatus(Enum):
    DISABLED = "disabled"
    PENDING_SETUP = "pending_setup"
    ENABLED = "enabled"
    GRACE_PERIOD = "grace_period"

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
    #User.requires_2fa_setup = requires_2fa_setup
    #User.is_2fa_enabled = is_2fa_enabled
    #User.can_skip_2fa = can_skip_2fa
    
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
    two_factor = db.relationship('UserTwoFactor', back_populates='user', uselist=False, cascade='all, delete-orphan')
    trusted_devices = db.relationship('TrustedDevice', back_populates='user', cascade='all, delete-orphan')
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
    
    def get_or_create_2fa(self):
        if not self.two_factor:
            self.two_factor = UserTwoFactor(user_id=self.id)
            db.session.add(self.two_factor)
        return self.two_factor
    
    def can_skip_2fa(self, device_token):
        if not device_token:
            return False
        
        settings = TwoFactorSettings.get_settings()
        if not settings.remember_device_enabled:
            return False
        
        device = TrustedDevice.query.filter_by(
            user_id=self.id,
            device_token=device_token
        ).first()
        
        if device and device.is_valid():
            device.refresh()
            return True
        
        return False
    
    def cleanup_expired_devices(self):
        TrustedDevice.query.filter(
            TrustedDevice.user_id == self.id,
            TrustedDevice.expires_at < datetime.utcnow().replace(tzinfo=timezone.utc)
        ).delete()

    def requires_2fa_setup(self):
        """Check if user requires 2FA setup"""
        # Import here to avoid circular imports
        from app.models import TwoFactorSettings, TwoFactorStatus
        
        if not hasattr(self, 'two_factor') or not self.two_factor:
            # Create 2FA record if it doesn't exist
            settings = TwoFactorSettings.get_settings()
            
            if settings.is_2fa_required_for_user(self):
                from app.models import UserTwoFactor
                two_factor = UserTwoFactor(user_id=self.id)
                two_factor.start_grace_period()
                db.session.add(two_factor)
                db.session.commit()
                return True
            return False
        
        return self.two_factor.is_setup_required()

    def is_2fa_enabled(self):
        """Check if user has 2FA enabled"""
        from app.models import TwoFactorStatus
        return (hasattr(self, 'two_factor') and 
                self.two_factor and 
                self.two_factor.status == TwoFactorStatus.ENABLED)
        
    def can_skip_2fa(self, device_token=None):
        """Check if user can skip 2FA verification"""
        from app.models import TwoFactorSettings, TrustedDevice
        
        settings = TwoFactorSettings.get_settings()
        
        # Check if remember device is enabled and device is trusted
        if (settings.remember_device_enabled and 
            device_token and 
            TrustedDevice.is_trusted_device(self, device_token)):
            return True
        
        return False

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
    
    # --- USER DELETION

    def safe_delete(self):
        """
        Safely delete a user by handling all foreign key relationships
        """
        from app.models import LeaveApplication, WorkExtension
        
        # Handle leave applications where this user is the approver
        leave_apps_as_approver = LeaveApplication.query.filter_by(approver_id=self.id).all()
        
        for leave_app in leave_apps_as_approver:
            # Option 1: Set approver_id to None (requires NULL constraint removal)
            leave_app.approver_id = None
            leave_app.approver_name = f"{self.full_name} (Deleted User)"
            
            # Option 2: Reassign to another approver in the same organizational unit
            # new_approver = self.find_replacement_approver()
            # if new_approver:
            #     leave_app.approver_id = new_approver.id
            #     leave_app.approver_name = new_approver.full_name
            #     leave_app.approver_email = new_approver.email
        
        # Handle work extensions where this user is the approver
        work_extensions_as_approver = WorkExtension.query.filter_by(approver_id=self.id).all()
        
        for work_ext in work_extensions_as_approver:
            work_ext.approver_id = None
            work_ext.approver_name = f"{self.full_name} (Deleted User)"
        
        # Clean up uploaded files
        import os
        from flask import current_app
        
        if self.avatar and self.avatar != 'default_avatar.png':
            try:
                avatar_path = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars', self.avatar)
                if os.path.exists(avatar_path):
                    os.remove(avatar_path)
            except Exception as e:
                current_app.logger.warning(f"Could not delete avatar file: {e}")
        
        if self.signature:
            try:
                signature_path = os.path.join(current_app.root_path, 'static', 'uploads', 'signatures', self.signature)
                if os.path.exists(signature_path):
                    os.remove(signature_path)
            except Exception as e:
                current_app.logger.warning(f"Could not delete signature file: {e}")
        
        # Remove the user
        db.session.delete(self)

    def find_replacement_approver(self):
        """
        Find a suitable replacement approver in the same organizational unit
        """
        # Look for other approvers in the same section
        if self.section_id:
            replacement = User.query.filter(
                User.section_id == self.section_id,
                User.is_section_approver == True,
                User.is_active == True,
                User.id != self.id
            ).first()
            
            if replacement:
                return replacement
        
        # Look for unit approvers in the same unit
        if self.unit_id:
            replacement = User.query.filter(
                User.unit_id == self.unit_id,
                User.is_unit_approver == True,
                User.is_active == True,
                User.id != self.id
            ).first()
            
            if replacement:
                return replacement
        
        # Look for managers/admins in the same section
        if self.section_id:
            replacement = User.query.filter(
                User.section_id == self.section_id,
                User.role.in_([UserRole.MANAGER, UserRole.ADMINISTRATOR]),
                User.is_active == True,
                User.id != self.id
            ).first()
            
            if replacement:
                return replacement
        
        return None

    # ----- ENHANCED FORCE DELETE METHOD ----

    def force_delete_all_data(self):
        """
        PERMANENTLY delete user and ALL associated data
        This is irreversible and removes all traces from the database
        """
        deletion_summary = {
            'user_id': self.id,
            'username': self.username,
            'full_name': self.full_name,
            'deleted_records': {},
            'files_deleted': [],
            'warnings': [],
            'approver_impact': []  # Initialize this list
        }
        
        try:
            # Import required models with error handling
            try:
                from app.models import (Shift, LeaveApplication, WorkExtension, 
                                      ScheduleTemplateV2, DateRemark, UserTwoFactor, 
                                      TrustedDevice)
            except ImportError as e:
                deletion_summary['warnings'].append(f"Could not import some models: {str(e)}")
            
            # 1. DELETE SHIFTS
            try:
                shifts = Shift.query.filter_by(employee_id=self.id).all()
                shift_count = len(shifts)
                for shift in shifts:
                    db.session.delete(shift)
                deletion_summary['deleted_records']['shifts'] = shift_count
            except Exception as e:
                deletion_summary['warnings'].append(f"Error deleting shifts: {str(e)}")
                deletion_summary['deleted_records']['shifts'] = 0
            
            # 2. DELETE LEAVE APPLICATIONS (as employee)
            try:
                leave_apps_as_employee = LeaveApplication.query.filter_by(employee_id=self.id).all()
                leave_employee_count = len(leave_apps_as_employee)
                for leave_app in leave_apps_as_employee:
                    db.session.delete(leave_app)
                deletion_summary['deleted_records']['leave_applications_as_employee'] = leave_employee_count
            except Exception as e:
                deletion_summary['warnings'].append(f"Error deleting leave applications as employee: {str(e)}")
                deletion_summary['deleted_records']['leave_applications_as_employee'] = 0
            
            # 3. UPDATE LEAVE APPLICATIONS (as approver) - Set to NULL
            try:
                leave_apps_as_approver = LeaveApplication.query.filter_by(approver_id=self.id).all()
                leave_approver_count = len(leave_apps_as_approver)
                for leave_app in leave_apps_as_approver:
                    leave_app.approver_id = None
                    leave_app.approver_name = f"{self.full_name} (Deleted User)"
                    leave_app.approver_email = 'deleted@system.placeholder'
                deletion_summary['deleted_records']['leave_applications_updated_as_approver'] = leave_approver_count
            except Exception as e:
                deletion_summary['warnings'].append(f"Error updating leave applications as approver: {str(e)}")
                deletion_summary['deleted_records']['leave_applications_updated_as_approver'] = 0
            
            # 4. DELETE WORK EXTENSIONS (as employee)
            try:
                work_exts_as_employee = WorkExtension.query.filter_by(employee_id=self.id).all()
                work_ext_employee_count = len(work_exts_as_employee)
                for work_ext in work_exts_as_employee:
                    db.session.delete(work_ext)
                deletion_summary['deleted_records']['work_extensions_as_employee'] = work_ext_employee_count
            except Exception as e:
                deletion_summary['warnings'].append(f"Error deleting work extensions as employee: {str(e)}")
                deletion_summary['deleted_records']['work_extensions_as_employee'] = 0
            
            # 5. UPDATE WORK EXTENSIONS (as approver)
            try:
                work_exts_as_approver = WorkExtension.query.filter_by(approver_id=self.id).all()
                work_ext_approver_count = len(work_exts_as_approver)
                for work_ext in work_exts_as_approver:
                    work_ext.approver_id = None
                    work_ext.approver_name = f"{self.full_name} (Deleted User)"
                    work_ext.approver_email = 'deleted@system.placeholder'
                deletion_summary['deleted_records']['work_extensions_updated_as_approver'] = work_ext_approver_count
            except Exception as e:
                deletion_summary['warnings'].append(f"Error updating work extensions as approver: {str(e)}")
                deletion_summary['deleted_records']['work_extensions_updated_as_approver'] = 0
            
            # 6. DELETE SCHEDULE TEMPLATES
            try:
                templates = ScheduleTemplateV2.query.filter_by(created_by_id=self.id).all()
                template_count = len(templates)
                for template in templates:
                    db.session.delete(template)
                deletion_summary['deleted_records']['schedule_templates'] = template_count
            except Exception as e:
                deletion_summary['warnings'].append(f"Error deleting schedule templates: {str(e)}")
                deletion_summary['deleted_records']['schedule_templates'] = 0
            
            # 7. DELETE DATE REMARKS created by user
            try:
                date_remarks = DateRemark.query.filter_by(created_by_id=self.id).all()
                remark_count = len(date_remarks)
                for remark in date_remarks:
                    db.session.delete(remark)
                deletion_summary['deleted_records']['date_remarks'] = remark_count
            except Exception as e:
                deletion_summary['warnings'].append(f"Error deleting date remarks: {str(e)}")
                deletion_summary['deleted_records']['date_remarks'] = 0
            
            # 8. DELETE 2FA DATA
            try:
                if hasattr(self, 'two_factor') and self.two_factor:
                    db.session.delete(self.two_factor)
                    deletion_summary['deleted_records']['two_factor_data'] = 1
                else:
                    deletion_summary['deleted_records']['two_factor_data'] = 0
            except Exception as e:
                deletion_summary['warnings'].append(f"Error deleting 2FA data: {str(e)}")
                deletion_summary['deleted_records']['two_factor_data'] = 0
            
            # 9. DELETE TRUSTED DEVICES
            try:
                trusted_devices = TrustedDevice.query.filter_by(user_id=self.id).all()
                device_count = len(trusted_devices)
                for device in trusted_devices:
                    db.session.delete(device)
                deletion_summary['deleted_records']['trusted_devices'] = device_count
            except Exception as e:
                deletion_summary['warnings'].append(f"Error deleting trusted devices: {str(e)}")
                deletion_summary['deleted_records']['trusted_devices'] = 0
            
            # 10. DELETE UPLOADED FILES
            self._force_delete_user_files(deletion_summary)
            
            # 11. RESET ORGANIZATIONAL APPROVER SETTINGS
            self._reset_organizational_approvers(deletion_summary)
            
            # 12. FINALLY DELETE THE USER RECORD
            db.session.delete(self)
            deletion_summary['deleted_records']['user_account'] = 1
            
            return deletion_summary
            
        except Exception as e:
            db.session.rollback()
            deletion_summary['warnings'].append(f"Error during force deletion: {str(e)}")
            raise e


    def get_deletion_preview(self):
        """
        Get a preview of what data will be deleted for this user
        """
        preview = {
            'user_info': {
                'id': self.id,
                'username': self.username,
                'full_name': self.full_name,
                'email': self.email,
                'role': self.role.value,
                'is_active': self.is_active
            },
            'data_to_delete': {},
            'data_to_update': {},
            'files_to_delete': [],
            'warnings': []
        }
        
        try:
            # Import models with error handling
            from app.models import (Shift, LeaveApplication, WorkExtension, 
                                  ScheduleTemplateV2, DateRemark, TrustedDevice)
            
            # Count shifts
            shift_count = Shift.query.filter_by(employee_id=self.id).count()
            preview['data_to_delete']['shifts'] = shift_count
            
            # Count leave applications
            leave_as_employee = LeaveApplication.query.filter_by(employee_id=self.id).count()
            leave_as_approver = LeaveApplication.query.filter_by(approver_id=self.id).count()
            preview['data_to_delete']['leave_applications_as_employee'] = leave_as_employee
            preview['data_to_update']['leave_applications_as_approver'] = leave_as_approver
            
            # Count work extensions
            work_ext_as_employee = WorkExtension.query.filter_by(employee_id=self.id).count()
            work_ext_as_approver = WorkExtension.query.filter_by(approver_id=self.id).count()
            preview['data_to_delete']['work_extensions_as_employee'] = work_ext_as_employee
            preview['data_to_update']['work_extensions_as_approver'] = work_ext_as_approver
            
            # Count templates
            template_count = ScheduleTemplateV2.query.filter_by(created_by_id=self.id).count()
            preview['data_to_delete']['schedule_templates'] = template_count
            
            # Count date remarks
            remark_count = DateRemark.query.filter_by(created_by_id=self.id).count()
            preview['data_to_delete']['date_remarks'] = remark_count
            
            # Check for 2FA data
            if hasattr(self, 'two_factor') and self.two_factor:
                preview['data_to_delete']['two_factor_data'] = 1
            else:
                preview['data_to_delete']['two_factor_data'] = 0
            
            # Count trusted devices
            device_count = TrustedDevice.query.filter_by(user_id=self.id).count()
            preview['data_to_delete']['trusted_devices'] = device_count
            
        except ImportError as e:
            preview['warnings'].append(f"Some models not available: {str(e)}")
            # Set default values for missing models
            for key in ['shifts', 'leave_applications_as_employee', 'work_extensions_as_employee', 
                       'schedule_templates', 'date_remarks', 'two_factor_data', 'trusted_devices']:
                if key not in preview['data_to_delete']:
                    preview['data_to_delete'][key] = 0
            
            for key in ['leave_applications_as_approver', 'work_extensions_as_approver']:
                if key not in preview['data_to_update']:
                    preview['data_to_update'][key] = 0
        
        except Exception as e:
            preview['warnings'].append(f"Error getting deletion preview: {str(e)}")
        
        # Check for uploaded files
        if self.avatar and self.avatar != 'default_avatar.png':
            preview['files_to_delete'].append(f"Avatar: {self.avatar}")
        
        if self.signature:
            preview['files_to_delete'].append(f"Signature: {self.signature}")
        
        # Check if user is an approver
        try:
            if self.can_approve_leaves():
                approvable_employees = self.get_approvable_employees()
                preview['warnings'].append(f"User is an approver for {len(approvable_employees)} employees")
        except Exception as e:
            preview['warnings'].append(f"Could not check approver status: {str(e)}")
        
        # Calculate total records to be affected
        total_deletions = sum(preview['data_to_delete'].values())
        total_updates = sum(preview['data_to_update'].values())
        
        preview['summary'] = {
            'total_records_to_delete': total_deletions,
            'total_records_to_update': total_updates,
            'total_files_to_delete': len(preview['files_to_delete']),
            'is_safe_to_delete': total_deletions == 0 and total_updates == 0
        }
        
        return preview

    def _force_delete_user_files(self, deletion_summary):
        """Force delete all user files"""
        import os
        from flask import current_app
        
        files_deleted = []
        
        # Delete avatar
        if self.avatar and self.avatar != 'default_avatar.png':
            try:
                avatar_path = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars', self.avatar)
                if os.path.exists(avatar_path):
                    os.remove(avatar_path)
                    files_deleted.append(f"Avatar: {self.avatar}")
            except Exception as e:
                deletion_summary['warnings'].append(f"Could not delete avatar: {e}")
        
        # Delete signature
        if self.signature:
            try:
                signature_path = os.path.join(current_app.root_path, 'static', 'uploads', 'signatures', self.signature)
                if os.path.exists(signature_path):
                    os.remove(signature_path)
                    files_deleted.append(f"Signature: {self.signature}")
            except Exception as e:
                deletion_summary['warnings'].append(f"Could not delete signature: {e}")
        
        deletion_summary['files_deleted'] = files_deleted

    def _reset_organizational_approvers(self, deletion_summary):
        """Reset approver settings if this user was an approver"""
        approver_resets = []
        
        try:
            # Check section approver impact
            if hasattr(self, 'is_section_approver') and self.is_section_approver and self.section_id:
                # Check if there are other section approvers
                other_section_approvers = User.query.filter(
                    User.section_id == self.section_id,
                    User.is_section_approver == True,
                    User.id != self.id,
                    User.is_active == True
                ).count()
                
                if other_section_approvers == 0:
                    section_name = self.section.name if hasattr(self, 'section') and self.section else 'Unknown'
                    approver_resets.append(f"Section {section_name} will have no approvers")
            
            # Check unit approver impact
            if hasattr(self, 'is_unit_approver') and self.is_unit_approver and self.unit_id:
                other_unit_approvers = User.query.filter(
                    User.unit_id == self.unit_id,
                    User.is_unit_approver == True,
                    User.id != self.id,
                    User.is_active == True
                ).count()
                
                if other_unit_approvers == 0:
                    unit_name = self.unit.name if hasattr(self, 'unit') and self.unit else 'Unknown'
                    approver_resets.append(f"Unit {unit_name} will have no approvers")
            
            # Check department approver impact (if 4-level hierarchy exists)
            if hasattr(self, 'is_department_approver') and self.is_department_approver and hasattr(self, 'department_id') and self.department_id:
                other_dept_approvers = User.query.filter(
                    User.department_id == self.department_id,
                    User.is_department_approver == True,
                    User.id != self.id,
                    User.is_active == True
                ).count()
                
                if other_dept_approvers == 0:
                    dept_name = self.department.name if hasattr(self, 'department') and self.department else 'Unknown'
                    approver_resets.append(f"Department {dept_name} will have no approvers")
            
            # Check division approver impact (if 4-level hierarchy exists)
            if hasattr(self, 'is_division_approver') and self.is_division_approver and hasattr(self, 'division_id') and self.division_id:
                other_div_approvers = User.query.filter(
                    User.division_id == self.division_id,
                    User.is_division_approver == True,
                    User.id != self.id,
                    User.is_active == True
                ).count()
                
                if other_div_approvers == 0:
                    div_name = self.division.name if hasattr(self, 'division') and self.division else 'Unknown'
                    approver_resets.append(f"Division {div_name} will have no approvers")
        
        except Exception as e:
            deletion_summary['warnings'].append(f"Error checking approver impact: {str(e)}")
        
        deletion_summary['approver_impact'] = approver_resets


# --------- SAFE DELETE (OLD)


    @classmethod
    def get_or_create_deleted_user_placeholder(cls):
        """
        Get or create a placeholder user for deleted user references
        """
        deleted_user = cls.query.filter_by(username='_deleted_user_').first()
        
        if not deleted_user:
            deleted_user = cls(
                username='_deleted_user_',
                email='deleted@system.placeholder',
                first_name='Deleted',
                last_name='User',
                role=UserRole.EMPLOYEE,
                is_active=False
            )
            deleted_user.set_password('_no_login_')
            db.session.add(deleted_user)
            db.session.commit()
        
        return deleted_user

    def safe_delete_with_placeholder(self):
        """
        Safely delete a user by reassigning references to a placeholder
        """
        from app.models import LeaveApplication, WorkExtension
        
        # Get or create the deleted user placeholder
        deleted_placeholder = User.get_or_create_deleted_user_placeholder()
        
        # Reassign leave applications where this user is the approver
        leave_apps_as_approver = LeaveApplication.query.filter_by(approver_id=self.id).all()
        for leave_app in leave_apps_as_approver:
            leave_app.approver_id = deleted_placeholder.id
            leave_app.approver_name = f"{self.full_name} (Deleted User)"
            leave_app.approver_email = 'deleted@system.placeholder'
        
        # Reassign work extensions where this user is the approver
        work_extensions_as_approver = WorkExtension.query.filter_by(approver_id=self.id).all()
        for work_ext in work_extensions_as_approver:
            work_ext.approver_id = deleted_placeholder.id
            work_ext.approver_name = f"{self.full_name} (Deleted User)"
            work_ext.approver_email = 'deleted@system.placeholder'
        
        # Clean up files (same as before)
        self._cleanup_user_files()
        
        # Delete the user
        db.session.delete(self)

    def _cleanup_user_files(self):
        """Clean up uploaded files for this user"""
        import os
        from flask import current_app
        
        if self.avatar and self.avatar != 'default_avatar.png':
            try:
                avatar_path = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars', self.avatar)
                if os.path.exists(avatar_path):
                    os.remove(avatar_path)
            except Exception as e:
                current_app.logger.warning(f"Could not delete avatar file: {e}")
        
        if self.signature:
            try:
                signature_path = os.path.join(current_app.root_path, 'static', 'uploads', 'signatures', self.signature)
                if os.path.exists(signature_path):
                    os.remove(signature_path)
            except Exception as e:
                current_app.logger.warning(f"Could not delete signature file: {e}")

    @property
    def approver_scope(self):
        """UPDATED: Get the scope of approval authority with 4-level hierarchy"""
        if self.can_admin():
            return "All Employees"
        
        scopes = []
        
        # Department level approver
        if self.is_department_approver and self.department:
            scopes.append(f"{self.department.name} Department")
        
        # Division level approver
        if self.is_division_approver and self.division:
            scopes.append(f"{self.division.name} Division")
        
        # Section level approver
        if self.is_section_approver and self.section:
            scopes.append(f"{self.section.name} Section")
        
        # Unit level approver
        if self.is_unit_approver and self.unit:
            scopes.append(f"{self.unit.name} Unit")
            
        # Manager role scope
        if self.role == UserRole.MANAGER:
            manager_scopes = []
            if self.department:
                manager_scopes.append(f"{self.department.name} Dept")
            if self.division:
                manager_scopes.append(f"{self.division.name} Div")
            if self.section:
                manager_scopes.append(f"{self.section.name} Sec")
            elif self.unit:
                manager_scopes.append(f"{self.unit.name} Unit")
            
            if manager_scopes:
                scopes.append(" > ".join(manager_scopes) + " (Manager)")
        
        if scopes:
            return " + ".join(scopes)
        else:
            return "None"
    
    def get_approvable_employees(self):
        """UPDATED: Get list of employees whose leave this user can approve with 4-level hierarchy"""
        if self.can_admin():
            # Administrators can approve for all active employees
            return User.query.filter_by(is_active=True).all()
        
        employees = set()  # Use set to avoid duplicates
        
        # Department approvers can approve for all employees in the same department
        if self.is_department_approver and self.department_id:
            dept_employees = User.query.filter_by(
                department_id=self.department_id, 
                is_active=True
            ).all()
            employees.update(dept_employees)
        
        # Division approvers can approve for employees in the same division
        if self.is_division_approver and self.division_id:
            div_employees = User.query.filter_by(
                division_id=self.division_id, 
                is_active=True
            ).all()
            employees.update(div_employees)
        
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
        
        # Managers can approve for employees in their organizational scope
        if self.role == UserRole.MANAGER:
            # Department managers can approve for entire department
            if self.department_id:
                manager_dept_employees = User.query.filter_by(
                    department_id=self.department_id,
                    is_active=True
                ).all()
                employees.update(manager_dept_employees)
            # Division managers can approve for entire division
            elif self.division_id:
                manager_div_employees = User.query.filter_by(
                    division_id=self.division_id,
                    is_active=True
                ).all()
                employees.update(manager_div_employees)
            # Section managers can approve for entire section
            elif self.section_id:
                manager_section_employees = User.query.filter_by(
                    section_id=self.section_id,
                    is_active=True
                ).all()
                employees.update(manager_section_employees)
            # Unit managers can approve for unit
            elif self.unit_id:
                manager_unit_employees = User.query.filter_by(
                    unit_id=self.unit_id,
                    is_active=True
                ).all()
                employees.update(manager_unit_employees)
        
        return list(employees)
    
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
            return (datetime.utcnow().replace(tzinfo=timezone.utc).date() - self.date_filed).days
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

class TwoFactorSettings(db.Model):
    """System-wide 2FA configuration"""
    __tablename__ = 'two_factor_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # System 2FA Configuration
    system_2fa_enabled = db.Column(db.Boolean, default=False, nullable=False)
    grace_period_days = db.Column(db.Integer, default=7, nullable=False)
    remember_device_enabled = db.Column(db.Boolean, default=True, nullable=False)
    remember_device_days = db.Column(db.Integer, default=30, nullable=False)
    require_admin_2fa = db.Column(db.Boolean, default=True, nullable=False)
    
    # Available Methods
    totp_enabled = db.Column(db.Boolean, default=True, nullable=False)
    sms_enabled = db.Column(db.Boolean, default=False, nullable=False)
    email_enabled = db.Column(db.Boolean, default=False, nullable=False)
    
    # SMS Configuration (if using SMS)
    sms_provider = db.Column(db.String(50), nullable=True)
    sms_api_key = db.Column(db.Text, nullable=True)
    sms_api_secret = db.Column(db.Text, nullable=True)
    sms_from_number = db.Column(db.String(20), nullable=True)
    
    # Backup Codes Configuration
    backup_codes_enabled = db.Column(db.Boolean, default=True, nullable=False)
    backup_codes_count = db.Column(db.Integer, default=10, nullable=False)
    
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @classmethod
    def get_settings(cls):
        """Get current 2FA settings (create default if none exist)"""
        settings = cls.query.first()
        if not settings:
            settings = cls()
            db.session.add(settings)
            db.session.commit()
        return settings
    
    def is_2fa_required_for_user(self, user):
        """Check if 2FA is required for a specific user"""
        if not self.system_2fa_enabled:
            return False
        
        # Always require for admins if admin 2FA is enabled
        if self.require_admin_2fa and user.role == UserRole.ADMINISTRATOR:
            return True
        
        # Require for all users if system-wide is enabled
        return self.system_2fa_enabled
    
    def get_available_methods(self):
        """Get list of available 2FA methods"""
        methods = []
        if self.totp_enabled:
            methods.append(TwoFactorMethod.TOTP)
        if self.sms_enabled:
            methods.append(TwoFactorMethod.SMS)
        if self.email_enabled:
            methods.append(TwoFactorMethod.EMAIL)
        return methods
    
    def encrypt_field(self, value):
        """Encrypt sensitive configuration data"""
        if not value:
            return None
        key = self._get_encryption_key()
        f = Fernet(key)
        return f.encrypt(value.encode()).decode()
    
    def decrypt_field(self, encrypted_value):
        """Decrypt sensitive configuration data"""
        if not encrypted_value:
            return None
        key = self._get_encryption_key()
        f = Fernet(key)
        return f.decrypt(encrypted_value.encode()).decode()
    
    def _get_encryption_key(self):
        """Get or create encryption key for 2FA settings"""
        key_file = os.path.join(os.environ.get('INSTANCE_PATH', '.'), '2fa_key.key')
        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                return f.read()
        else:
            key = Fernet.generate_key()
            os.makedirs(os.path.dirname(key_file), exist_ok=True)
            with open(key_file, 'wb') as f:
                f.write(key)
            return key
    
    def to_dict(self):
        """Convert to dictionary for JSON responses"""
        return {
            'system_2fa_enabled': self.system_2fa_enabled,
            'grace_period_days': self.grace_period_days,
            'remember_device_enabled': self.remember_device_enabled,
            'remember_device_days': self.remember_device_days,
            'require_admin_2fa': self.require_admin_2fa,
            'totp_enabled': self.totp_enabled,
            'sms_enabled': self.sms_enabled,
            'email_enabled': self.email_enabled,
            'backup_codes_enabled': self.backup_codes_enabled,
            'backup_codes_count': self.backup_codes_count
        }

class UserTwoFactor(db.Model):
    """Individual user 2FA configuration and data"""
    __tablename__ = 'user_two_factor'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # 2FA Status and Methods
    status = db.Column(db.Enum(TwoFactorStatus), default=TwoFactorStatus.DISABLED, nullable=False)
    primary_method = db.Column(db.Enum(TwoFactorMethod), nullable=True)
    
    # TOTP Configuration
    totp_secret = db.Column(db.Text, nullable=True)
    totp_verified = db.Column(db.Boolean, default=False, nullable=False)
    
    # SMS Configuration
    phone_number = db.Column(db.String(20), nullable=True)
    phone_verified = db.Column(db.Boolean, default=False, nullable=False)
    
    # Email 2FA
    email_2fa_enabled = db.Column(db.Boolean, default=False, nullable=False)
    
    # Backup Codes
    backup_codes = db.Column(db.Text, nullable=True)
    backup_codes_used = db.Column(db.Text, nullable=True)
    
    # Grace Period
    grace_period_start = db.Column(db.DateTime(timezone=True), nullable=True)
    grace_period_reminded = db.Column(db.Boolean, default=False, nullable=False)
    
    # Last verification tracking
    last_verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    verification_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime(timezone=True), nullable=True)
    
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = db.relationship('User', back_populates='two_factor')
        
    def generate_totp_secret(self):
        """Generate new TOTP secret for user"""
        secret = pyotp.random_base32()
        self.totp_secret = self._encrypt_data(secret)
        return secret
    
    def get_totp_secret(self):
        """Get decrypted TOTP secret with error handling"""
        if not self.totp_secret:
            return None
        
        try:
            return self._decrypt_data(self.totp_secret)
        except Exception as e:
            # If decryption fails, the key might have changed
            # Log the error and return None to trigger new secret generation
            from flask import current_app
            current_app.logger.warning(f"Failed to decrypt TOTP secret for user {self.user_id}: {e}")
            # Clear the corrupted secret
            self.totp_secret = None
            return None
    
    def verify_totp_code(self, code):
        """Verify TOTP code"""
        secret = self.get_totp_secret()
        if not secret:
            return False
        
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)
    
    def generate_qr_code(self, app_name="Employee Scheduling"):
        """Generate QR code for TOTP setup"""
        secret = self.get_totp_secret()
        if not secret:
            return None
        
        totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=self.user.email,
            issuer_name=app_name
        )
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        img_io = io.BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        
        img_b64 = base64.b64encode(img_io.getvalue()).decode()
        return f"data:image/png;base64,{img_b64}"
    
    def generate_backup_codes(self, count=10):
        """Generate new backup codes"""
        import secrets
        import string
        
        codes = []
        for _ in range(count):
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            formatted_code = f"{code[:4]}-{code[4:]}"
            codes.append(formatted_code)
        
        self.backup_codes = self._encrypt_data(json.dumps(codes))
        self.backup_codes_used = self._encrypt_data(json.dumps([]))
        return codes
    
    def get_backup_codes(self):
        """Get list of unused backup codes"""
        if not self.backup_codes:
            return []
        
        try:
            all_codes = json.loads(self._decrypt_data(self.backup_codes))
            used_codes = json.loads(self._decrypt_data(self.backup_codes_used) or "[]")
            return [code for code in all_codes if code not in used_codes]
        except Exception as e:
            from flask import current_app
            current_app.logger.warning(f"Failed to decrypt backup codes for user {self.user_id}: {e}")
            return []
    
    def use_backup_code(self, code):
        """Mark backup code as used"""
        if not self.backup_codes:
            return False
        
        try:
            all_codes = json.loads(self._decrypt_data(self.backup_codes))
            used_codes = json.loads(self._decrypt_data(self.backup_codes_used) or "[]")
            
            # Normalize code format
            normalized_code = code.upper().replace('-', '')
            if len(normalized_code) == 8:
                formatted_code = f"{normalized_code[:4]}-{normalized_code[4:]}"
            else:
                formatted_code = code.upper()
            
            if formatted_code in all_codes and formatted_code not in used_codes:
                used_codes.append(formatted_code)
                self.backup_codes_used = self._encrypt_data(json.dumps(used_codes))
                return True
            
            return False
        except Exception as e:
            from flask import current_app
            current_app.logger.warning(f"Failed to use backup code for user {self.user_id}: {e}")
            return False
    
    def is_in_grace_period(self):
        """Check if user is in grace period"""
        if not self.grace_period_start:
            return False
        
        settings = TwoFactorSettings.get_settings()
        grace_end = self.grace_period_start + timedelta(days=settings.grace_period_days)
        return datetime.utcnow().replace(tzinfo=timezone.utc) < grace_end
    
    def start_grace_period(self):
        """Start grace period for user"""
        self.grace_period_start = datetime.utcnow().replace(tzinfo=timezone.utc)
        self.status = TwoFactorStatus.GRACE_PERIOD
    
    def is_setup_required(self):
        """Check if user needs to set up 2FA"""
        settings = TwoFactorSettings.get_settings()
        
        if not settings.is_2fa_required_for_user(self.user):
            return False
        
        if self.status == TwoFactorStatus.ENABLED:
            return False
        
        if self.status == TwoFactorStatus.GRACE_PERIOD and self.is_in_grace_period():
            return False
        
        return True
    
    def _encrypt_data(self, data):
        """Encrypt sensitive user data with error handling"""
        if not data:
            return None
        
        try:
            settings = TwoFactorSettings.get_settings()
            key = settings._get_encryption_key()
            f = Fernet(key)
            return f.encrypt(data.encode()).decode()
        except Exception as e:
            from flask import current_app
            current_app.logger.error(f"Failed to encrypt data for user {self.user_id}: {e}")
            return None
    
    def _decrypt_data(self, encrypted_data):
        """Decrypt sensitive user data with error handling"""
        if not encrypted_data:
            return None
        
        try:
            settings = TwoFactorSettings.get_settings()
            key = settings._get_encryption_key()
            f = Fernet(key)
            return f.decrypt(encrypted_data.encode()).decode()
        except Exception as e:
            from flask import current_app
            current_app.logger.error(f"Failed to decrypt data for user {self.user_id}: {e}")
            # Re-raise the exception to be handled by calling methods
            raise

class TrustedDevice(db.Model):
    """Track trusted devices for 2FA remember functionality"""
    __tablename__ = 'trusted_devices'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    device_token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    device_name = db.Column(db.String(100), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    user = db.relationship('User', back_populates='trusted_devices')

    
    @classmethod
    def create_for_user(cls, user, request_obj, remember_days=30):
        """Create a new trusted device for user"""
        import secrets
        
        device_token = secrets.token_urlsafe(32)
        # FIX: Use timezone-aware datetime
        expires_at = datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(days=remember_days)
        
        device = cls(
            user_id=user.id,
            device_token=device_token,
            user_agent=request_obj.headers.get('User-Agent', '')[:500],
            ip_address=request_obj.remote_addr,
            expires_at=expires_at
        )
        
        db.session.add(device)
        return device_token
    
    @classmethod
    def is_trusted_device(cls, user, device_token):
        """Check if device is trusted and not expired"""
        if not device_token:
            return False
        
        device = cls.query.filter_by(
            user_id=user.id,
            device_token=device_token
        ).first()
        
        if not device:
            return False
        
        # FIX: Use timezone-aware datetime for comparison
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        if device.expires_at < now:
            db.session.delete(device)
            return False
        
        # FIX: Use timezone-aware datetime
        device.last_used_at = datetime.utcnow().replace(tzinfo=timezone.utc)
        return True
    
    @classmethod
    def cleanup_expired(cls):
        """Remove expired trusted devices"""
        # FIX: Use timezone-aware datetime
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        expired = cls.query.filter(cls.expires_at < now).all()
        for device in expired:
            db.session.delete(device)
        return len(expired)
    
    def is_valid(self):
        """Check if device is still valid (not expired)"""
        # FIX: Use timezone-aware datetime
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        return self.expires_at > now
    
    def refresh(self):
        """Update last_used_at timestamp"""
        # FIX: Use timezone-aware datetime
        self.last_used_at = datetime.utcnow().replace(tzinfo=timezone.utc)

class TemplateType(Enum):
    WEEKLY = "weekly"
    CUSTOM = "custom"
    DEPARTMENT = "department"
    SECTION = "section"
    UNIT = "unit"

class ScheduleTemplateV2(db.Model):
    """Enhanced Schedule Template with snapshot capabilities"""
    __tablename__ = 'schedule_templates_v2'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    template_type = db.Column(db.Enum(TemplateType), nullable=False, default=TemplateType.WEEKLY)
    
    # Organizational scope
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    division_id = db.Column(db.Integer, db.ForeignKey('divisions.id'), nullable=True) 
    section_id = db.Column(db.Integer, db.ForeignKey('sections.id'), nullable=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=True)
    
    # Template metadata
    source_start_date = db.Column(db.Date, nullable=True)  # Original date range
    source_end_date = db.Column(db.Date, nullable=True)
    total_employees = db.Column(db.Integer, default=0)
    total_shifts = db.Column(db.Integer, default=0)
    
    # Template data - JSON structure with shifts and employee mappings
    template_data = db.Column(db.JSON, nullable=False)
    employee_mappings = db.Column(db.JSON, nullable=True)  # Maps roles/positions to employees
    
    # Access control
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_public = db.Column(db.Boolean, default=False)  # Can others use this template?
    usage_count = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    
    # Relationships
    created_by = db.relationship('User', backref='created_templates')
    department = db.relationship('Department', backref='templates')
    division = db.relationship('Division', backref='templates')
    section = db.relationship('Section', backref='templates')
    unit = db.relationship('Unit', backref='templates')
    
    def __repr__(self):
        return f'<ScheduleTemplateV2 {self.name}>'
    
    @property
    def scope_display(self):
        """Get human-readable scope of template"""
        if self.department:
            return f"Department: {self.department.name}"
        elif self.division:
            return f"Division: {self.division.name}"
        elif self.section:
            return f"Section: {self.section.name}"
        elif self.unit:
            return f"Unit: {self.unit.name}"
        else:
            return "Organization-wide"
    
    @property
    def duration_days(self):
        """Calculate duration of template in days"""
        if self.source_start_date and self.source_end_date:
            return (self.source_end_date - self.source_start_date).days + 1
        return 7  # Default to 7 days
    
    def increment_usage(self):
        """Increment usage counter and update last used timestamp"""
        self.usage_count += 1
        self.last_used_at = datetime.utcnow().replace(tzinfo=timezone.utc)
    
    def can_user_access(self, user):
        """Check if user can access this template"""
        # Creator can always access
        if self.created_by_id == user.id:
            return True
        
        # Public templates are accessible to all
        if self.is_public:
            return True
        
        # Check organizational scope access
        if user.can_edit_schedule():
            # Admins can access all templates
            if user.role == UserRole.ADMINISTRATOR:
                return True
            
            # Managers can access templates in their scope
            if self.department_id and user.department_id == self.department_id:
                return True
            if self.division_id and user.division_id == self.division_id:
                return True
            if self.section_id and user.section_id == self.section_id:
                return True
            if self.unit_id and user.unit_id == self.unit_id:
                return True
        
        return False
    
    def to_dict(self):
        """Convert template to dictionary for JSON responses"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'template_type': self.template_type.value,
            'scope_display': self.scope_display,
            'source_start_date': self.source_start_date.isoformat() if self.source_start_date else None,
            'source_end_date': self.source_end_date.isoformat() if self.source_end_date else None,
            'duration_days': self.duration_days,
            'total_employees': self.total_employees,
            'total_shifts': self.total_shifts,
            'usage_count': self.usage_count,
            'is_public': self.is_public,
            'created_by': self.created_by.full_name,
            'created_at': self.created_at.isoformat(),
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None
        }
    
    @classmethod
    def create_from_schedule(cls, user, name, description, start_date, end_date, 
                           section_id=None, unit_id=None, department_id=None, division_id=None,
                           is_public=False, template_type=TemplateType.WEEKLY):
        """Create a template from existing schedule data"""
        
        # Get shifts for the date range and organizational scope
        shifts_query = Shift.query.filter(
            Shift.date.between(start_date, end_date)
        )
        
        # Apply organizational filter
        if section_id:
            team_members = User.query.filter_by(section_id=section_id, is_active=True).all()
        elif unit_id:
            team_members = User.query.filter_by(unit_id=unit_id, is_active=True).all()
        elif department_id:
            team_members = User.query.filter_by(department_id=department_id, is_active=True).all()
        elif division_id:
            team_members = User.query.filter_by(division_id=division_id, is_active=True).all()
        else:
            team_members = User.query.filter_by(is_active=True).all()
        
        if not team_members:
            raise ValueError("No employees found in the specified organizational scope")
        
        # Get shifts for selected employees
        shifts = shifts_query.filter(
            Shift.employee_id.in_([tm.id for tm in team_members])
        ).order_by(Shift.employee_id, Shift.date, Shift.sequence).all()
        
        # Build template data structure
        template_data = {
            'shifts': [],
            'employees': {},
            'date_pattern': []
        }
        
        employee_mappings = {}
        
        # Calculate relative day offsets from start date
        total_days = (end_date - start_date).days + 1
        
        for shift in shifts:
            day_offset = (shift.date - start_date).days
            
            # Store employee info if not already stored
            if shift.employee_id not in template_data['employees']:
                employee = shift.employee
                template_data['employees'][shift.employee_id] = {
                    'personnel_number': employee.personnel_number,
                    'full_name': employee.full_name,
                    'job_title': employee.job_title,
                    'rank': employee.rank,
                    'section_name': employee.section.name if employee.section else None,
                    'unit_name': employee.unit.name if employee.unit else None,
                    'department_name': employee.department.name if employee.department else None,
                    'division_name': employee.division.name if employee.division else None,
                    'employee_type': employee.employee_type.value if employee.employee_type else None,
                    'schedule_format': employee.schedule_format.value if employee.schedule_format else None
                }
                
                # Create mapping key for role-based template application
                mapping_key = f"{employee.job_title or 'General'}_{employee.rank or 'Staff'}"
                if mapping_key not in employee_mappings:
                    employee_mappings[mapping_key] = []
                employee_mappings[mapping_key].append(shift.employee_id)
            
            # Store shift data with relative day offset
            shift_data = {
                'employee_id': shift.employee_id,
                'day_offset': day_offset,
                'start_time': shift.start_time.strftime('%H:%M') if shift.start_time else None,
                'end_time': shift.end_time.strftime('%H:%M') if shift.end_time else None,
                'role': shift.role,
                'status': shift.status.value,
                'notes': shift.notes,
                'color': shift.color,
                'work_arrangement': shift.work_arrangement.value if shift.work_arrangement else 'onsite',
                'sequence': shift.sequence
            }
            template_data['shifts'].append(shift_data)
        
        # Store date pattern for reference
        current_date = start_date
        while current_date <= end_date:
            template_data['date_pattern'].append({
                'offset': (current_date - start_date).days,
                'weekday': current_date.weekday(),
                'date_str': current_date.strftime('%Y-%m-%d')
            })
            current_date += timedelta(days=1)
        
        # Create the template
        template = cls(
            name=name,
            description=description,
            template_type=template_type,
            department_id=department_id,
            division_id=division_id,
            section_id=section_id,
            unit_id=unit_id,
            source_start_date=start_date,
            source_end_date=end_date,
            total_employees=len(template_data['employees']),
            total_shifts=len(template_data['shifts']),
            template_data=template_data,
            employee_mappings=employee_mappings,
            created_by_id=user.id,
            is_public=is_public
        )
        
        return template
    
    def apply_to_date_range(self, start_date, end_date, user, 
                          target_section_id=None, target_unit_id=None,
                          employee_mapping_overrides=None, replace_existing=False):
        """Apply template to a new date range"""
        
        # Validate date range matches template duration
        target_days = (end_date - start_date).days + 1
        template_days = self.duration_days
        
        if target_days != template_days:
            raise ValueError(f"Target date range ({target_days} days) must match template duration ({template_days} days)")
        
        # Get target employees
        if target_section_id:
            target_employees = User.query.filter_by(section_id=target_section_id, is_active=True).all()
        elif target_unit_id:
            target_employees = User.query.filter_by(unit_id=target_unit_id, is_active=True).all()
        elif self.section_id:
            target_employees = User.query.filter_by(section_id=self.section_id, is_active=True).all()
        elif self.unit_id:
            target_employees = User.query.filter_by(unit_id=self.unit_id, is_active=True).all()
        else:
            raise ValueError("No target organizational scope specified")
        
        if not target_employees:
            raise ValueError("No active employees found in target scope")
        
        # Create employee mapping
        employee_id_mapping = {}
        
        if employee_mapping_overrides:
            # Use provided mapping overrides
            employee_id_mapping = employee_mapping_overrides
        else:
            # Auto-map employees by role/position
            target_employee_by_role = {}
            for emp in target_employees:
                role_key = f"{emp.job_title or 'General'}_{emp.rank or 'Staff'}"
                if role_key not in target_employee_by_role:
                    target_employee_by_role[role_key] = []
                target_employee_by_role[role_key].append(emp)
            
            # Map template employees to target employees
            for template_emp_id, template_emp_data in self.template_data['employees'].items():
                template_role_key = f"{template_emp_data.get('job_title') or 'General'}_{template_emp_data.get('rank') or 'Staff'}"
                
                if template_role_key in target_employee_by_role and target_employee_by_role[template_role_key]:
                    # Map to first available employee with same role
                    target_emp = target_employee_by_role[template_role_key].pop(0)
                    employee_id_mapping[int(template_emp_id)] = target_emp.id
        
        # Remove existing shifts if replace_existing is True
        if replace_existing:
            existing_shifts = Shift.query.filter(
                Shift.date.between(start_date, end_date),
                Shift.employee_id.in_([emp.id for emp in target_employees])
            ).all()
            
            for shift in existing_shifts:
                db.session.delete(shift)
        
        # Create new shifts from template
        created_shifts = []
        skipped_shifts = []
        
        for shift_data in self.template_data['shifts']:
            template_employee_id = shift_data['employee_id']
            
            # Skip if no mapping for this employee
            if template_employee_id not in employee_id_mapping:
                skipped_shifts.append(f"No mapping for employee ID {template_employee_id}")
                continue
            
            target_employee_id = employee_id_mapping[template_employee_id]
            shift_date = start_date + timedelta(days=shift_data['day_offset'])
            
            # Check if shift already exists (if not replacing)
            if not replace_existing:
                existing = Shift.query.filter_by(
                    employee_id=target_employee_id,
                    date=shift_date,
                    sequence=shift_data['sequence']
                ).first()
                
                if existing:
                    skipped_shifts.append(f"Shift already exists for {existing.employee.full_name} on {shift_date}")
                    continue
            
            # Create new shift
            new_shift = Shift(
                employee_id=target_employee_id,
                date=shift_date,
                start_time=datetime.strptime(shift_data['start_time'], '%H:%M').time() if shift_data['start_time'] else None,
                end_time=datetime.strptime(shift_data['end_time'], '%H:%M').time() if shift_data['end_time'] else None,
                role=shift_data['role'],
                status=ShiftStatus(shift_data['status']),
                notes=shift_data['notes'],
                color=shift_data['color'],
                work_arrangement=WorkArrangement(shift_data['work_arrangement']),
                sequence=shift_data['sequence']
            )
            
            db.session.add(new_shift)
            created_shifts.append(new_shift)
        
        # Update template usage
        self.increment_usage()
        
        return {
            'created_shifts': len(created_shifts),
            'skipped_shifts': len(skipped_shifts),
            'skipped_details': skipped_shifts,
            'employee_mappings_used': len(employee_id_mapping),
            'unmapped_employees': len(self.template_data['employees']) - len(employee_id_mapping)
        }

