# app/backup/routes.py
import os
import subprocess
import gzip
import shutil
from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app, send_file
from flask_login import login_required, current_user
from app.backup import bp
from app.models import db, AppSettings
from functools import wraps
import json
import glob

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.can_admin():
            flash('Administrator access required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

class BackupSettings:
    """Backup configuration settings"""
    
    @staticmethod
    def get_default_settings():
        return {
            'backup_path': '/app/backups',  # CHANGED: Use /app/backups instead of /container-data/backups
            'date_format': '%Y%m%d_%H%M%S',
            'name_format': 'scheduling_db_backup_{date}',
            'rotation_days': 30,
            'compression_enabled': True,
            'auto_backup_enabled': False,
            'backup_schedule': 'daily',
            'backup_time': '02:00'
        }
    
    @staticmethod
    def get_settings():
        """Get backup settings from app settings or defaults"""
        try:
            app_settings = AppSettings.get_settings()
            
            # Try to get backup settings from app_settings JSON field or create new field
            if hasattr(app_settings, 'backup_settings') and app_settings.backup_settings:
                settings = json.loads(app_settings.backup_settings)
            else:
                settings = BackupSettings.get_default_settings()
                BackupSettings.save_settings(settings)
            
            return settings
        except:
            return BackupSettings.get_default_settings()
    
    @staticmethod
    def save_settings(settings):
        """Save backup settings to app settings"""
        try:
            app_settings = AppSettings.get_settings()
            
            # Add backup_settings field if it doesn't exist
            if not hasattr(app_settings, 'backup_settings'):
                # Add the column to the table
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS backup_settings TEXT"))
                    conn.commit()
            
            app_settings.backup_settings = json.dumps(settings)
            db.session.commit()
            return True
        except Exception as e:
            current_app.logger.error(f"Error saving backup settings: {str(e)}")
            return False

class DatabaseBackupManager:
    """Database backup manager for PostgreSQL"""
    
    def __init__(self):
        self.settings = BackupSettings.get_settings()
        
    def ensure_backup_directory(self):
        """Ensure backup directory exists"""
        backup_path = self.settings['backup_path']
        if not os.path.exists(backup_path):
            os.makedirs(backup_path, exist_ok=True)
        return backup_path
    
    def get_database_connection_info(self):
        """Extract database connection info from SQLAlchemy URI"""
        from urllib.parse import urlparse
        
        # Get database URL from config
        db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
        
        if not db_url:
            raise Exception("Database URL not configured")
        
        # Parse the URL
        parsed = urlparse(db_url)
        
        return {
            'host': parsed.hostname or 'localhost',
            'port': parsed.port or 5432,
            'database': parsed.path.lstrip('/') or 'scheduling_db',
            'username': parsed.username or 'postgres',
            'password': parsed.password or ''
        }
    
    def create_backup(self):
        """Create a database backup"""
        try:
            backup_path = self.ensure_backup_directory()
            db_info = self.get_database_connection_info()
            
            # Generate backup filename
            timestamp = datetime.now().strftime(self.settings['date_format'])
            backup_name = self.settings['name_format'].format(date=timestamp)
            backup_file = os.path.join(backup_path, f"{backup_name}.sql")
            
            # Set up environment for pg_dump
            env = os.environ.copy()
            if db_info['password']:
                env['PGPASSWORD'] = db_info['password']
            
            # Run pg_dump
            cmd = [
                'pg_dump',
                '-h', db_info['host'],
                '-p', str(db_info['port']),
                '-U', db_info['username'],
                '-d', db_info['database'],
                '--verbose',
                '--no-password',
                '-f', backup_file
            ]
            
            current_app.logger.info(f"Running backup command: {' '.join(cmd[:-2])} [password hidden]")
            
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                raise Exception(f"pg_dump failed: {result.stderr}")
            
            # Compress if enabled
            final_file = backup_file
            if self.settings['compression_enabled']:
                compressed_file = f"{backup_file}.gz"
                with open(backup_file, 'rb') as f_in:
                    with gzip.open(compressed_file, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                os.remove(backup_file)
                final_file = compressed_file
            
            # Create a copy as the latest backup
            latest_file = os.path.join(backup_path, 'asset_lookup.db')
            if self.settings['compression_enabled']:
                latest_file += '.gz'
            shutil.copy2(final_file, latest_file)
            
            current_app.logger.info(f"Backup created successfully: {final_file}")
            return True, f"Backup created: {os.path.basename(final_file)}"
            
        except subprocess.TimeoutExpired:
            return False, "Backup timed out after 5 minutes"
        except Exception as e:
            current_app.logger.error(f"Backup failed: {str(e)}")
            return False, f"Backup failed: {str(e)}"
    
    def restore_backup(self, backup_filename):
        """Restore database from backup"""
        try:
            backup_path = self.ensure_backup_directory()
            backup_file = os.path.join(backup_path, backup_filename)
            
            if not os.path.exists(backup_file):
                raise Exception(f"Backup file not found: {backup_filename}")
            
            # Create a backup of current database before restore
            current_backup_success, current_backup_msg = self.create_backup()
            if not current_backup_success:
                current_app.logger.warning(f"Could not create pre-restore backup: {current_backup_msg}")
            
            db_info = self.get_database_connection_info()
            
            # Prepare the backup file
            restore_file = backup_file
            temp_file = None
            
            if backup_file.endswith('.gz'):
                # Decompress to temporary file
                temp_file = backup_file.replace('.gz', '.tmp')
                with gzip.open(backup_file, 'rb') as f_in:
                    with open(temp_file, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                restore_file = temp_file
            
            # Set up environment
            env = os.environ.copy()
            if db_info['password']:
                env['PGPASSWORD'] = db_info['password']
            
            # Run psql to restore
            cmd = [
                'psql',
                '-h', db_info['host'],
                '-p', str(db_info['port']),
                '-U', db_info['username'],
                '-d', db_info['database'],
                '-f', restore_file
            ]
            
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
            
            # Clean up temp file
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            
            if result.returncode != 0:
                raise Exception(f"Database restore failed: {result.stderr}")
            
            current_app.logger.info(f"Database restored successfully from: {backup_filename}")
            return True, f"Database restored from {backup_filename}"
            
        except Exception as e:
            current_app.logger.error(f"Restore failed: {str(e)}")
            return False, f"Restore failed: {str(e)}"
    
    def get_backup_files(self):
        """Get list of backup files with metadata"""
        try:
            backup_path = self.ensure_backup_directory()
            pattern = os.path.join(backup_path, "*backup*.sql*")
            files = glob.glob(pattern)
            
            # Also include any .db files (for compatibility)
            db_pattern = os.path.join(backup_path, "*.db*")
            files.extend(glob.glob(db_pattern))
            
            backup_files = []
            
            for file_path in files:
                filename = os.path.basename(file_path)
                
                # Skip the latest backup symlink
                if filename in ['asset_lookup.db', 'asset_lookup.db.gz']:
                    continue
                
                try:
                    stat = os.stat(file_path)
                    size = stat.st_size
                    created = datetime.fromtimestamp(stat.st_mtime)
                    
                    # Format size
                    size_formatted = self.format_file_size(size)
                    
                    # Check if compressed
                    is_compressed = filename.endswith('.gz')
                    
                    backup_files.append({
                        'filename': filename,
                        'size': size,
                        'size_formatted': size_formatted,
                        'created': created,
                        'created_formatted': created.strftime('%Y-%m-%d %H:%M:%S'),
                        'is_compressed': is_compressed
                    })
                except OSError:
                    continue
            
            # Sort by creation time (newest first)
            backup_files.sort(key=lambda x: x['created'], reverse=True)
            
            return backup_files
            
        except Exception as e:
            current_app.logger.error(f"Error getting backup files: {str(e)}")
            return []
    
    def delete_backup(self, backup_filename):
        """Delete a backup file"""
        try:
            backup_path = self.ensure_backup_directory()
            backup_file = os.path.join(backup_path, backup_filename)
            
            if not os.path.exists(backup_file):
                raise Exception(f"Backup file not found: {backup_filename}")
            
            os.remove(backup_file)
            current_app.logger.info(f"Backup deleted: {backup_filename}")
            return True, f"Backup {backup_filename} deleted successfully"
            
        except Exception as e:
            current_app.logger.error(f"Error deleting backup: {str(e)}")
            return False, f"Error deleting backup: {str(e)}"
    
    def cleanup_old_backups(self):
        """Clean up old backup files based on rotation settings"""
        try:
            backup_files = self.get_backup_files()
            cutoff_date = datetime.now() - timedelta(days=self.settings['rotation_days'])
            
            deleted_count = 0
            errors = []
            
            for backup_file in backup_files:
                if backup_file['created'] < cutoff_date:
                    success, message = self.delete_backup(backup_file['filename'])
                    if success:
                        deleted_count += 1
                    else:
                        errors.append(message)
            
            if errors:
                return False, f"Cleanup completed with errors. Deleted {deleted_count} files. Errors: {'; '.join(errors)}"
            else:
                return True, f"Cleanup completed successfully. Deleted {deleted_count} old backup files."
                
        except Exception as e:
            current_app.logger.error(f"Cleanup failed: {str(e)}")
            return False, f"Cleanup failed: {str(e)}"
    
    def get_backup_statistics(self):
        """Get backup statistics"""
        try:
            backup_files = self.get_backup_files()
            
            total_backups = len(backup_files)
            total_size = sum(f['size'] for f in backup_files)
            total_size_formatted = self.format_file_size(total_size)
            
            newest_backup = None
            if backup_files:
                newest_backup = backup_files[0]['created_formatted']
            
            return {
                'total_backups': total_backups,
                'total_size': total_size,
                'total_size_formatted': total_size_formatted,
                'newest_backup': newest_backup
            }
            
        except Exception as e:
            current_app.logger.error(f"Error getting backup statistics: {str(e)}")
            return {
                'total_backups': 0,
                'total_size': 0,
                'total_size_formatted': '0 B',
                'newest_backup': None
            }
    
    @staticmethod
    def format_file_size(size_bytes):
        """Format file size in human readable format"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        import math
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"

# Routes
@bp.route('/')
@login_required
@admin_required
def backup_management():
    """Main backup management page"""
    backup_manager = DatabaseBackupManager()
    
    # Get backup statistics
    stats = backup_manager.get_backup_statistics()
    
    # Get recent backup files
    recent_backups = backup_manager.get_backup_files()[:10]  # Last 10 backups
    
    # Get backup settings
    settings = BackupSettings.get_settings()
    
    return render_template('admin/backup.html', 
                         stats=stats, 
                         recent_backups=recent_backups,
                         settings=settings)

@bp.route('/create', methods=['POST'])
@login_required
@admin_required
def create_backup():
    """Create a new backup"""
    try:
        backup_manager = DatabaseBackupManager()
        success, message = backup_manager.create_backup()
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'danger')
            
    except Exception as e:
        flash(f'Error creating backup: {str(e)}', 'danger')
        current_app.logger.error(f"Backup creation error: {str(e)}")
    
    return redirect(url_for('backup.backup_management'))

@bp.route('/restore', methods=['POST'])
@login_required
@admin_required
def restore_backup():
    """Restore from a backup"""
    backup_filename = request.form.get('backup_filename')
    
    if not backup_filename:
        flash('No backup file specified.', 'danger')
        return redirect(url_for('backup.backup_management'))
    
    try:
        backup_manager = DatabaseBackupManager()
        success, message = backup_manager.restore_backup(backup_filename)
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'danger')
            
    except Exception as e:
        flash(f'Error restoring backup: {str(e)}', 'danger')
        current_app.logger.error(f"Backup restore error: {str(e)}")
    
    return redirect(url_for('backup.backup_management'))

@bp.route('/delete', methods=['POST'])
@login_required
@admin_required
def delete_backup():
    """Delete a backup file"""
    backup_filename = request.form.get('backup_filename')
    
    if not backup_filename:
        flash('No backup file specified.', 'danger')
        return redirect(url_for('backup.backup_management'))
    
    try:
        backup_manager = DatabaseBackupManager()
        success, message = backup_manager.delete_backup(backup_filename)
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'danger')
            
    except Exception as e:
        flash(f'Error deleting backup: {str(e)}', 'danger')
        current_app.logger.error(f"Backup deletion error: {str(e)}")
    
    return redirect(url_for('backup.backup_management'))

@bp.route('/cleanup', methods=['POST'])
@login_required
@admin_required
def cleanup_backups():
    """Clean up old backup files"""
    try:
        backup_manager = DatabaseBackupManager()
        success, message = backup_manager.cleanup_old_backups()
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'warning')
            
    except Exception as e:
        flash(f'Error during cleanup: {str(e)}', 'danger')
        current_app.logger.error(f"Backup cleanup error: {str(e)}")
    
    return redirect(url_for('backup.backup_management'))

@bp.route('/settings', methods=['POST'])
@login_required
@admin_required
def update_backup_settings():
    """Update backup settings"""
    try:
        settings = {
            'backup_path': request.form.get('backup_path', '/app/backups'),  # FIXED: Changed from '/container-data/backups' to '/app/backups'
            'date_format': request.form.get('date_format', '%Y%m%d_%H%M%S'),
            'name_format': request.form.get('name_format', 'scheduling_db_backup_{date}'),
            'rotation_days': int(request.form.get('rotation_days', 30)),
            'compression_enabled': 'compression_enabled' in request.form,
            'auto_backup_enabled': 'auto_backup_enabled' in request.form,
            'backup_schedule': request.form.get('backup_schedule', 'daily'),
            'backup_time': request.form.get('backup_time', '02:00')
        }
        
        # Rest of the function remains the same...
        # Validate settings
        if settings['rotation_days'] < 1 or settings['rotation_days'] > 45:
            flash('Rotation period must be between 1 and 45 days.', 'danger')
            return redirect(url_for('backup.backup_management'))
        
        if BackupSettings.save_settings(settings):
            flash('Backup settings updated successfully!', 'success')
        else:
            flash('Error saving backup settings.', 'danger')
            
    except ValueError:
        flash('Invalid rotation period. Please enter a valid number.', 'danger')
    except Exception as e:
        flash(f'Error updating settings: {str(e)}', 'danger')
        current_app.logger.error(f"Backup settings update error: {str(e)}")
    
    return redirect(url_for('backup.backup_management'))
    
@bp.route('/status')
@login_required
@admin_required
def backup_status():
    """Get backup status as JSON"""
    try:
        backup_manager = DatabaseBackupManager()
        stats = backup_manager.get_backup_statistics()
        recent_backups = backup_manager.get_backup_files()[:10]
        
        return jsonify({
            'success': True,
            'stats': stats,
            'recent_backups': recent_backups
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/download/<filename>')
@login_required
@admin_required
def download_backup(filename):
    """Download a backup file"""
    try:
        backup_manager = DatabaseBackupManager()
        backup_path = backup_manager.ensure_backup_directory()
        file_path = os.path.join(backup_path, filename)
        
        if not os.path.exists(file_path):
            flash('Backup file not found.', 'danger')
            return redirect(url_for('backup.backup_management'))
        
        return send_file(file_path, as_attachment=True, download_name=filename)
        
    except Exception as e:
        flash(f'Error downloading backup: {str(e)}', 'danger')
        current_app.logger.error(f"Backup download error: {str(e)}")
        return redirect(url_for('backup.backup_management'))
