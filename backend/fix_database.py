"""
Force Fix Database - Rebuild Table with All Columns
This will preserve your data while fixing the schema
"""
import sys
from pathlib import Path
import sqlite3
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

print("\n" + "=" * 70)
print("FORCE DATABASE FIX: Rebuilding Table Schema")
print("=" * 70 + "\n")

DB_PATH = Path("data/database/feedback.db")

if not DB_PATH.exists():
    print("❌ Database file doesn't exist!")
    sys.exit(1)

print(f"✅ Found database: {DB_PATH}")

try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Step 1: Check current schema
    print("\n📋 Checking current schema...")
    cursor.execute("PRAGMA table_info(feedback_interactions)")
    columns = {row[1]: row for row in cursor.fetchall()}
    
    print(f"   Current columns: {', '.join(columns.keys())}")
    
    # Step 2: Check if we need to fix
    missing_columns = []
    if 'message_timestamp' not in columns:
        missing_columns.append('message_timestamp')
    if 'context_window_id' not in columns:
        missing_columns.append('context_window_id')
    if 'is_in_context' not in columns:
        missing_columns.append('is_in_context')
    
    if not missing_columns:
        print("\n✅ All columns exist! No fix needed.")
        conn.close()
        sys.exit(0)
    
    print(f"\n⚠️  Missing columns: {', '.join(missing_columns)}")
    print("\n🔧 Rebuilding table with correct schema...")
    
    # Step 3: Create new table with correct schema
    print("   Creating new table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback_interactions_new (
            id VARCHAR PRIMARY KEY NOT NULL,
            user_id VARCHAR NOT NULL,
            session_id VARCHAR NOT NULL,
            message_id VARCHAR NOT NULL UNIQUE,
            timestamp DATETIME NOT NULL,
            message_timestamp DATETIME NOT NULL,
            context_window_id VARCHAR,
            is_in_context BOOLEAN DEFAULT 1,
            question TEXT NOT NULL,
            response TEXT NOT NULL,
            provider_used VARCHAR,
            tokens_used INTEGER,
            feedback_type VARCHAR,
            feedback_comment TEXT,
            feedback_timestamp DATETIME
        )
    """)
    print("   ✅ New table created")
    
    # Step 4: Copy data from old table
    print("\n🔧 Copying data from old table...")
    
    # Get all data from old table
    cursor.execute("SELECT * FROM feedback_interactions")
    old_rows = cursor.fetchall()
    
    print(f"   Found {len(old_rows)} rows to copy")
    
    # Get column names from old table
    old_columns = [col[1] for col in columns.values()]
    
    # Insert into new table
    copied = 0
    for row in old_rows:
        # Create a dictionary of old values
        old_data = dict(zip(old_columns, row))
        
        # Prepare values for new table
        values = (
            old_data.get('id'),
            old_data.get('user_id'),
            old_data.get('session_id'),
            old_data.get('message_id'),
            old_data.get('timestamp'),
            old_data.get('message_timestamp') or old_data.get('timestamp'),  # Use timestamp if missing
            old_data.get('context_window_id'),
            old_data.get('is_in_context', 1),  # Default to True
            old_data.get('question'),
            old_data.get('response'),
            old_data.get('provider_used'),
            old_data.get('tokens_used'),
            old_data.get('feedback_type'),
            old_data.get('feedback_comment'),
            old_data.get('feedback_timestamp')
        )
        
        try:
            cursor.execute("""
                INSERT INTO feedback_interactions_new 
                (id, user_id, session_id, message_id, timestamp, message_timestamp, 
                 context_window_id, is_in_context, question, response, provider_used, 
                 tokens_used, feedback_type, feedback_comment, feedback_timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, values)
            copied += 1
        except Exception as e:
            print(f"   ⚠️  Error copying row {old_data.get('id')}: {e}")
    
    print(f"   ✅ Copied {copied} rows successfully")
    
    # Step 5: Drop old table and rename new table
    print("\n🔧 Replacing old table...")
    cursor.execute("DROP TABLE feedback_interactions")
    cursor.execute("ALTER TABLE feedback_interactions_new RENAME TO feedback_interactions")
    print("   ✅ Table replaced")
    
    # Step 6: Create indexes
    print("\n🔧 Creating indexes...")
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_user_id ON feedback_interactions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_session_id ON feedback_interactions(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_message_id ON feedback_interactions(message_id)",
        "CREATE INDEX IF NOT EXISTS idx_message_timestamp ON feedback_interactions(message_timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_is_in_context ON feedback_interactions(is_in_context)",
        "CREATE INDEX IF NOT EXISTS idx_session_context ON feedback_interactions(session_id, is_in_context)"
    ]
    
    for idx_sql in indexes:
        cursor.execute(idx_sql)
        print(f"   ✅ Index created")
    
    # Step 7: Commit all changes
    conn.commit()
    print("\n✅ All changes committed")
    
    # Step 8: Verify new schema
    print("\n📊 Verifying new schema...")
    cursor.execute("PRAGMA table_info(feedback_interactions)")
    new_columns = cursor.fetchall()
    
    print("\n   Final columns:")
    for col in new_columns:
        col_id, name, type_, notnull, default, pk = col
        nullable = "NOT NULL" if notnull else "NULL"
        print(f"   ✅ {name:25} {type_:15} {nullable}")
    
    # Verify data count
    cursor.execute("SELECT COUNT(*) FROM feedback_interactions")
    count = cursor.fetchone()[0]
    print(f"\n   Total rows in new table: {count}")
    
    conn.close()
    
    print("\n" + "=" * 70)
    print("✅ DATABASE FIX COMPLETE!")
    print("=" * 70)
    print("\n📋 Next steps:")
    print("   1. RESTART your backend server:")
    print("      Press Ctrl+C to stop the current server")
    print("      Then run: python main.py")
    print("   2. Test the chat functionality")
    print("   3. The timer should now work perfectly!")
    print("\n")

except Exception as e:
    print(f"\n❌ Fix failed: {e}")
    import traceback
    traceback.print_exc()
    
    # Try to rollback
    try:
        conn.rollback()
        print("\n🔄 Changes rolled back")
    except:
        pass
    
    print("\n⚠️  If the fix failed, try the complete reset:")
    print("   python reset_database.py")
    
    sys.exit(1)