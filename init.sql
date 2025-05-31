-- init.sql - PostgreSQL initialization script
-- This file will be executed when the PostgreSQL container starts

-- Create the database if it doesn't exist
-- (This is handled by POSTGRES_DB environment variable)

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Set timezone
SET timezone = 'UTC';

-- Create initial admin user will be handled by Flask app
