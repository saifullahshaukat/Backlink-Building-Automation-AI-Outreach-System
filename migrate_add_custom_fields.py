"""
Migration script to add custom_fields column to email_outreach table
"""
import sqlite3
import os

# Database path
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'merged_dashboard.db')

if not os.path.exists(db_path):
    print(f"Database not found at: {db_path}")
    exit(1)

print(f"Connecting to database: {db_path}")

# Connect to database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Check if column already exists
    cursor.execute("PRAGMA table_info(email_outreach)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'custom_fields' in columns:
        print("✓ Column 'custom_fields' already exists in email_outreach table")
    else:
        # Add the custom_fields column
        print("Adding 'custom_fields' column to email_outreach table...")
        cursor.execute("ALTER TABLE email_outreach ADD COLUMN custom_fields TEXT")
        conn.commit()
        print("✓ Successfully added 'custom_fields' column")
    
    # Verify the column was added
    cursor.execute("PRAGMA table_info(email_outreach)")
    columns = cursor.fetchall()
    
    print("\nCurrent email_outreach table structure:")
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")
    
    print("\n✓ Migration completed successfully!")
    
except Exception as e:
    print(f"✗ Error during migration: {e}")
    conn.rollback()
finally:
    conn.close()
