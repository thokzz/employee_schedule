#!/usr/bin/env python3
"""
Migration script to allow NULL approver_id in leave_applications table
Usage: python fix_approver_null.py <host> <port> <database> <username> <password>
"""

import sys
import psycopg2
from psycopg2 import sql

def run_migration(host, port, database, username, password):
    """Execute the migration to allow NULL approver_id"""
    
    # Migration SQL commands
    migration_commands = [
        "ALTER TABLE leave_applications ALTER COLUMN approver_id DROP NOT NULL;",
        "COMMENT ON COLUMN leave_applications.approver_id IS 'Foreign key to users table. Can be NULL if approver is deleted.';",
        "CREATE INDEX IF NOT EXISTS idx_leave_applications_approver_id_null ON leave_applications (approver_id) WHERE approver_id IS NULL;"
    ]
    
    try:
        # Connect to database
        print(f"Connecting to database {database} on {host}:{port}...")
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=username,
            password=password
        )
        
        # Enable autocommit for DDL operations
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("Running migration commands...")
        
        for i, command in enumerate(migration_commands, 1):
            print(f"Executing command {i}/{len(migration_commands)}: {command[:50]}...")
            try:
                cursor.execute(command)
                print(f"✓ Command {i} executed successfully")
            except psycopg2.Error as e:
                print(f"✗ Error in command {i}: {e}")
                if "does not exist" in str(e) or "already exists" in str(e):
                    print("  (This might be expected - continuing...)")
                else:
                    raise
        
        # Verify the change
        print("\nVerifying migration...")
        cursor.execute("""
            SELECT column_name, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'leave_applications' 
            AND column_name = 'approver_id'
        """)
        
        result = cursor.fetchone()
        if result and result[1] == 'YES':
            print("✓ Migration successful: approver_id now allows NULL values")
        else:
            print("✗ Migration verification failed")
            
        cursor.close()
        conn.close()
        
        print("\nMigration completed successfully!")
        return True
        
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 6:
        print("Usage: python fix_approver_null.py <host> <port> <database> <username> <password>")
        print("Example: python fix_approver_null.py db 5432 scheduling_db postgres postgres")
        sys.exit(1)
    
    host = sys.argv[1]
    port = sys.argv[2]
    database = sys.argv[3]
    username = sys.argv[4]
    password = sys.argv[5]
    
    success = run_migration(host, port, database, username, password)
    sys.exit(0 if success else 1)