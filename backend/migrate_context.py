"""
Database Migration: Add 5-Minute Context Window Support
Run this once to update your existing database
"""
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path("data/database/feedback.db")

def migrate_add_context_support():
    """
    Add context window support to existing database
    
    What this does:
    1. Creates chat_sessions table
    2. Adds context tracking columns to feedback_interactions
    3. Creates indexes for performance
    """
    
    print("\n" + "=" * 80)
    print("DATABASE MIGRATION: Adding 5-Minute Context Support")
    print("=" * 80 + "\n")
    
    if not DB_PATH.exists():
        print("❌ Database not found. Run the backend first to create it.")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # ========================================================================
    # STEP 1: Create chat_sessions table
    # ========================================================================
    
    print("Step 1: Creating chat_sessions table...")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR NOT NULL,
            session_id VARCHAR NOT NULL UNIQUE,
            start_time DATETIME NOT NULL,
            context_window_start DATETIME NOT NULL,
            context_expires_at DATETIME NOT NULL,
            last_activity DATETIME NOT NULL,
            message_count INTEGER DEFAULT 0,
            context_resets INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    print("   ✅ chat_sessions table created")
    
    # ========================================================================
    # STEP 2: Add new columns to feedback_interactions
    # ========================================================================
    
    print("\nStep 2: Adding context columns to feedback_interactions...")
    
    # Check if columns already exist
    cursor.execute("PRAGMA table_info(feedback_interactions)")
    existing_columns = [col[1] for col in cursor.fetchall()]
    
    # Add message_timestamp
    if 'message_timestamp' not in existing_columns:
        cursor.execute("""
            ALTER TABLE feedback_interactions 
            ADD COLUMN message_timestamp DATETIME
        """)
        
        # Copy timestamp to message_timestamp for existing records
        cursor.execute("""
            UPDATE feedback_interactions 
            SET message_timestamp = timestamp 
            WHERE message_timestamp IS NULL
        """)
        print("   ✅ Added message_timestamp column")
    else:
        print("   ℹ️  message_timestamp already exists")
    
    # Add context_window_id
    if 'context_window_id' not in existing_columns:
        cursor.execute("""
            ALTER TABLE feedback_interactions 
            ADD COLUMN context_window_id VARCHAR
        """)
        
        # Set default context window for existing records
        cursor.execute("""
            UPDATE feedback_interactions 
            SET context_window_id = session_id || '_ctx_0'
            WHERE context_window_id IS NULL
        """)
        print("   ✅ Added context_window_id column")
    else:
        print("   ℹ️  context_window_id already exists")
    
    # Add is_in_context
    if 'is_in_context' not in existing_columns:
        cursor.execute("""
            ALTER TABLE feedback_interactions 
            ADD COLUMN is_in_context BOOLEAN DEFAULT 1
        """)
        
        # Mark all existing records as in context
        cursor.execute("""
            UPDATE feedback_interactions 
            SET is_in_context = 1
            WHERE is_in_context IS NULL
        """)
        print("   ✅ Added is_in_context column")
    else:
        print("   ℹ️  is_in_context already exists")
    
    # ========================================================================
    # STEP 3: Create indexes for performance
    # ========================================================================
    
    print("\nStep 3: Creating indexes...")
    
    # Indexes for chat_sessions
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_session_id 
        ON chat_sessions(session_id)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_user_id 
        ON chat_sessions(user_id)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_active 
        ON chat_sessions(is_active)
    """)
    
    # Indexes for feedback_interactions
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_message_timestamp 
        ON feedback_interactions(message_timestamp)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_context_window 
        ON feedback_interactions(context_window_id)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_in_context 
        ON feedback_interactions(is_in_context)
    """)
    
    print("   ✅ Indexes created")
    
    # ========================================================================
    # STEP 4: Commit changes
    # ========================================================================
    
    conn.commit()
    conn.close()
    
    print("\n" + "=" * 80)
    print("✅ MIGRATION COMPLETE!")
    print("=" * 80)
    print("\nYour database now supports 5-minute context windows!")
    print("\nNext steps:")
    print("1. Restart your backend server")
    print("2. The chat will now maintain context for 5 minutes")
    print("3. After 5 minutes, AI will forget previous conversations")
    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    migrate_add_context_support()