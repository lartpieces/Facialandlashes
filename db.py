import sqlite3

DB_PATH = 'spa_app_final_clean.db'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_clients_with_last_visit():
    conn = get_db_connection()
    clients = conn.execute("""
        SELECT c.id, c.name, c.phone,
               MAX(v.visit_date) AS last_visit,
               (SELECT t.name FROM technicians t
                JOIN visit_services vs ON t.id = vs.technician_id
                WHERE vs.visit_id = v.id LIMIT 1) AS technician
        FROM clients c
        LEFT JOIN visits v ON c.id = v.client_id
        GROUP BY c.id
        ORDER BY c.name
    """).fetchall()
    conn.close()
    return clients
