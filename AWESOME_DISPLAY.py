
 import sqlite3

 conn = sqlite3.connect("populate.db")
 cursor = conn.cursor()

 cursor.execute("SELECT * FROM scada_readings ORDER BY rowid DESC LIMIT 100")

 print(" | ".join(column[0] for column in cursor.description))
 print("-" * 100)

 for row in cursor.fetchall():
     print(" | ".join(str(value) for value in row))
conn.close()
