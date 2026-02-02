import sqlite3
import os

db_path = os.path.join('instance', 'app.db')

if not os.path.exists(db_path):
    print(f"Database {db_path} not found. Skipping migration.")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if microsoft_id already exists
        cursor.execute("PRAGMA table_info(user);")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'microsoft_id' not in columns:
            print("Adding microsoft_id column to user table...")
            cursor.execute("ALTER TABLE user ADD COLUMN microsoft_id VARCHAR(100);")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_microsoft_id ON user(microsoft_id);")
            print("Column added.")
        else:
            print("microsoft_id column already exists.")
            
        # SQLite doesn't support ALTER TABLE ALTER COLUMN nullable easily.
        # But we can just make sure we handle it in our app logic.
        # In SQLite, ALL columns are nullable by default unless specified otherwise.
        # Let's check if google_id was NOT NULL before.
        
        # We also want to clean up any Microsoft IDs that might have been saved in google_id
        # Actually, let's just see if there are any that look like Microsoft IDs.
        # Microsoft IDs are often GUIDs or similar, while Google IDs are long strings of digits.
        # But it's safer to just let the user log in again to fix their record.
        
        conn.commit()
        print("Migration completed successfully.")
    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
    finally:
        conn.close()
