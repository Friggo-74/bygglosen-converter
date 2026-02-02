from app import app, db
from sqlalchemy import text, inspect

def migrate():
    with app.app_context():
        # Get inspector to check current schema
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('user')]
        
        if 'microsoft_id' not in columns:
            print("Adding microsoft_id column to user table...")
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE user ADD COLUMN microsoft_id VARCHAR(100)"))
                # Try to add index (syntax varies slightly but this is standard)
                try:
                    conn.execute(text("CREATE UNIQUE INDEX idx_user_microsoft_id ON user(microsoft_id)"))
                except Exception as e:
                    print(f"Index creation skipped or already exists: {e}")
                conn.commit()
            print("Column added successfully.")
        else:
            print("microsoft_id column already exists.")

if __name__ == "__main__":
    try:
        migrate()
        print("Migration process finished.")
    except Exception as e:
        print(f"Migration error: {e}")
