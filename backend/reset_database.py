from pathlib import Path
from database import create_database
from config import DATABASE

print("Resetting database...")

# Delete old database
db = Path(DATABASE)

if db.exists():
    db.unlink()
    print("Old database deleted.")

# Create new database
create_database()

print("New database created successfully.")
