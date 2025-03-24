import sqlite3

conn = sqlite3.connect('spa_app_final_clean.db')
conn.execute("ALTER TABLE clients ADD COLUMN notes TEXT")
conn.commit()
conn.close()
