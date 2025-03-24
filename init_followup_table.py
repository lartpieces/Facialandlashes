import sqlite3

DB_PATH = 'spa_app_final_clean.db'  # adjust path if needed

def create_followup_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS follow_ups (
            client_id INTEGER PRIMARY KEY,
            followed_up_at TEXT,
            note TEXT,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        )
    ''')
    conn.commit()
    conn.close()
    print("✅ follow_ups table created successfully.")

if __name__ == "__main__":
    create_followup_table()
