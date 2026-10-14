import sqlite3
import os

db_path = os.path.abspath("populate.db")

print("Database:", db_path)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
print("connected to database")

cursor.execute("""
SELECT name
FROM sqlite_master
WHERE type='table';
""")

print("\nTables:")
for table in cursor.fetchall():
    print(table[0])

print("\nData table structure:")

cursor.execute("PRAGMA table_info(users)")

for row in cursor.fetchall():
    print(row)

conn.close()
print("done")