from faker import Faker
import sqlite3 #serverless, self-contained database engine that runs directly inside your application rather than as a separate #background proces

fake = Faker()

conn = sqlite3.connect("populate.db")
print("connected to database")
cursor = conn.cursor() #the method used to create a cursor object from an active database connection
print("database permisions gained")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
	id int primary key,
	pressure INT,
	flowrate INT,
	time INT)"""
)
print("tables created")

for i in range(100):
    cursor.execute("""
        INSERT INTO users (pressure, flowrate, time)
        VALUES (?, ?, ?)
    """, (
        fake.random_int(min=0, max=5),
        fake.random_int(min=50, max=200),
        fake.random_int(min=0, max=2359)
    ))

conn.commit()

print("100 fake rows created")
print("Showing top 10 rows of fake data:")

cursor.execute("SELECT COUNT(*) FROM users")
print("Total rows:", cursor.fetchone()[0])

cursor.execute("""
    SELECT pressure, flowrate, time
    FROM users
    LIMIT 10
""")

for row in cursor.fetchall():
    print(row)

conn.close()