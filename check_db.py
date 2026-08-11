import sqlite3

conn = sqlite3.connect("telemetry.db")
rows = conn.execute("""
                    SELECT id, position, speed_kmh, gas, brake
                    FROM telemetry
                    ORDER BY id
                        LIMIT 100
                    """).fetchall()

for r in rows:
    print(r)

conn.close()