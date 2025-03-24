from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash, session
import sqlite3
import pandas as pd
from io import BytesIO
from xhtml2pdf import pisa
from flask import make_response
from jinja2 import Template

app = Flask(__name__)
app.secret_key = '1107'  # Replace with something secret
DB_PATH = 'spa_app_final_clean.db'

# --- Helper Functions ---
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_clients_with_last_visit():
    # Now also includes a 'loyal' field (True if visit_count >= 10)
    conn = get_db_connection()
    clients = conn.execute("""
        SELECT c.id, c.name, c.phone, c.notes,
               COUNT(v.id) AS visit_count,
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

    result = []
    for c in clients:
        client = dict(c)
        client['loyal'] = client['visit_count'] >= 10
        result.append(client)
    return result

# --- Routes ---
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/clients')
def clients_list():
    search = request.args.get('search', '').strip().lower()
    sort = request.args.get('sort', 'name')
    loyalty = request.args.get('loyalty', 'all')
    page = int(request.args.get('page', 1))
    per_page = 20

    clients = fetch_clients_with_last_visit()

    if search:
        clients = [c for c in clients if search in c['name'].lower() or search in c['phone']]

    if loyalty == 'loyal':
        clients = [c for c in clients if c['loyal']]
    elif loyalty == 'nonloyal':
        clients = [c for c in clients if not c['loyal']]

    if sort == 'last_visit':
        clients.sort(key=lambda c: c['last_visit'] or '', reverse=True)
    elif sort == 'visit_count':
        clients.sort(key=lambda c: c['visit_count'], reverse=True)
    else:
        clients.sort(key=lambda c: c[sort])

    total_clients = len(clients)
    total_pages = (total_clients + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    clients_paginated = clients[start:end]

    # Compute pagination range
    start_page = max(1, page - 2)
    end_page = min(total_pages, start_page + 4)

    return render_template(
        'clients_list.html',
        clients=clients_paginated,
        search=search,
        sort=sort,
        loyalty=loyalty,
        page=page,
        total_pages=total_pages,
        start_page=start_page,
        end_page=end_page
    )

@app.route('/client-log')
def client_log():
    return render_template('client_log.html')

@app.route('/api/clients')
def api_clients():
    clients = fetch_clients_with_last_visit()
    return jsonify(clients)

@app.route('/add-client', methods=['GET', 'POST'])
def add_client():
    if request.method == 'POST':
        name = request.form['name'].strip()
        phone = request.form['phone'].strip()
        notes = request.form.get('notes', '').strip()
        if name and phone:
            conn = get_db_connection()
            conn.execute("INSERT INTO clients (name, phone, notes) VALUES (?, ?, ?)", (name, phone, notes))
            conn.commit()
            conn.close()
            return redirect(url_for('clients_list'))
    return render_template('add_client.html')

@app.route('/edit-client/<int:client_id>', methods=['GET', 'POST'])
def edit_client(client_id):
    conn = get_db_connection()
    client = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    if request.method == 'POST':
        name = request.form['name'].strip()
        phone = request.form['phone'].strip()
        notes = request.form.get('notes', '').strip()
        conn.execute("UPDATE clients SET name = ?, phone = ?, notes = ? WHERE id = ?", (name, phone, notes, client_id))
        conn.commit()
        conn.close()
        return redirect(url_for('clients_list'))
    conn.close()
    return render_template('edit_client.html', client=client)

@app.route('/delete-client/<int:client_id>', methods=['POST'])
def delete_client(client_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('clients_list'))

@app.route('/export/clients/excel')
def export_clients_excel():
    """
    Exports the current client list including total visits and loyalty indicator.
    """
    clients = fetch_clients_with_last_visit()
    df = pd.DataFrame(clients, columns=["id", "name", "phone", "visit_count", "last_visit", "technician", "notes"])
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Clients')
    output.seek(0)
    return send_file(output, download_name="clients_list.xlsx", as_attachment=True)

@app.route('/export/clients/pdf')
def export_clients_pdf():
    clients = fetch_clients_with_last_visit()
    html = render_template('clients_pdf.html', clients=clients)
    output = BytesIO()
    pisa.CreatePDF(html, dest=output)
    output.seek(0)
    return send_file(output, download_name="clients_list.pdf", as_attachment=True)

@app.route('/api/client-log/<int:client_id>')
def api_client_log(client_id):
    conn = get_db_connection()
    query = """
        SELECT v.visit_date, c.name AS client_name, c.phone,
               t.name AS technician, s.category, s.name AS service,
               vs.invoice, vs.discount, vs.net_invoice, vs.tips,
               pm.name AS payment_method
        FROM visits v
        JOIN clients c ON v.client_id = c.id
        LEFT JOIN visit_services vs ON v.id = vs.visit_id
        LEFT JOIN services s ON vs.service_id = s.id
        LEFT JOIN technicians t ON vs.technician_id = t.id
        LEFT JOIN payment_methods pm ON v.payment_method_id = pm.id
        WHERE c.id = ?
        ORDER BY v.visit_date DESC
    """
    rows = conn.execute(query, (client_id,)).fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/visits-log')
def visits_log():
    client = request.args.get('client', '').strip().lower()
    technician = request.args.get('technician', '')
    category = request.args.get('category', '')
    service = request.args.get('service', '')
    payment = request.args.get('payment', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    page = int(request.args.get('page', 1))
    per_page = 20

    conn = get_db_connection()
    query = """
        SELECT v.id AS visit_id, v.visit_date, c.name AS client_name, c.phone,
               t.name AS technician, s.category, s.name AS service,
               vs.invoice, vs.discount, vs.net_invoice, vs.tips,
               pm.name AS payment_method
        FROM visits v
        JOIN clients c ON v.client_id = c.id
        LEFT JOIN visit_services vs ON v.id = vs.visit_id
        LEFT JOIN services s ON vs.service_id = s.id
        LEFT JOIN technicians t ON vs.technician_id = t.id
        LEFT JOIN payment_methods pm ON v.payment_method_id = pm.id
        WHERE 1=1
    """
    params = []

    if client:
        query += " AND (LOWER(c.name) LIKE ? OR c.phone LIKE ?)"
        params.extend([f"%{client}%", f"%{client}%"])
    if technician:
        query += " AND t.name = ?"
        params.append(technician)
    if category:
        query += " AND s.category = ?"
        params.append(category)
    if service:
        query += " AND s.name = ?"
        params.append(service)
    if payment:
        query += " AND pm.name = ?"
        params.append(payment)
    if start_date:
        query += " AND v.visit_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND v.visit_date <= ?"
        params.append(end_date)

    query += " ORDER BY v.visit_date DESC"
    all_visits = conn.execute(query, params).fetchall()

    # Pagination logic
    total_visits = len(all_visits)
    total_pages = (total_visits + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    visits = all_visits[start:end]

    start_page = max(1, page - 2)
    end_page = min(total_pages, start_page + 4)

    # Dropdowns
    technicians = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM technicians WHERE name IS NOT NULL").fetchall()]
    categories = [row['category'] for row in conn.execute("SELECT DISTINCT category FROM services WHERE category IS NOT NULL").fetchall()]
    services = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM services WHERE name IS NOT NULL").fetchall()]
    payments = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM payment_methods WHERE name IS NOT NULL").fetchall()]
    conn.close()

    return render_template(
        'visits_log.html',
        visits=visits,
        technicians=technicians,
        categories=categories,
        services=services,
        payments=payments,
        selected_technician=technician,
        selected_category=category,
        selected_service=service,
        selected_payment=payment,
        page=page,
        total_pages=total_pages,
        start_page=start_page,
        end_page=end_page
    )


@app.route('/export/visits/excel')
def export_visits_excel():
    client = request.args.get('client', '').strip().lower()
    technician = request.args.get('technician', '')
    category = request.args.get('category', '')
    service = request.args.get('service', '')
    payment = request.args.get('payment', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    conn = get_db_connection()
    query = """
        SELECT v.visit_date, c.name AS client_name, c.phone,
               t.name AS technician, s.category, s.name AS service,
               vs.invoice, vs.discount, vs.net_invoice, vs.tips,
               pm.name AS payment_method
        FROM visits v
        JOIN clients c ON v.client_id = c.id
        LEFT JOIN visit_services vs ON v.id = vs.visit_id
        LEFT JOIN services s ON vs.service_id = s.id
        LEFT JOIN technicians t ON vs.technician_id = t.id
        LEFT JOIN payment_methods pm ON v.payment_method_id = pm.id
        WHERE 1=1
    """
    params = []

    if client:
        query += " AND (LOWER(c.name) LIKE ? OR c.phone LIKE ?)"
        params.extend([f"%{client}%", f"%{client}%"])
    if technician:
        query += " AND t.name = ?"
        params.append(technician)
    if category:
        query += " AND s.category = ?"
        params.append(category)
    if service:
        query += " AND s.name = ?"
        params.append(service)
    if payment:
        query += " AND pm.name = ?"
        params.append(payment)
    if start_date:
        query += " AND v.visit_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND v.visit_date <= ?"
        params.append(end_date)

    query += " ORDER BY v.visit_date DESC"
    visits = conn.execute(query, params).fetchall()
    conn.close()

    df = pd.DataFrame(visits, columns=["visit_date", "client_name", "phone", "technician", "category", "service", "invoice", "discount", "net_invoice", "tips", "payment_method"])

    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Visits Log')
    output.seek(0)

    return send_file(output, download_name="visits_log.xlsx", as_attachment=True)

@app.route('/export/visits/pdf')
def export_visits_pdf():
    client = request.args.get('client', '').strip().lower()
    technician = request.args.get('technician', '')
    category = request.args.get('category', '')
    service = request.args.get('service', '')
    payment = request.args.get('payment', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    conn = get_db_connection()
    query = """
        SELECT v.visit_date, c.name AS client_name, c.phone,
               t.name AS technician, s.category, s.name AS service,
               vs.invoice, vs.discount, vs.net_invoice, vs.tips,
               pm.name AS payment_method
        FROM visits v
        JOIN clients c ON v.client_id = c.id
        LEFT JOIN visit_services vs ON v.id = vs.visit_id
        LEFT JOIN services s ON vs.service_id = s.id
        LEFT JOIN technicians t ON vs.technician_id = t.id
        LEFT JOIN payment_methods pm ON v.payment_method_id = pm.id
        WHERE 1=1
    """
    params = []

    if client:
        query += " AND (LOWER(c.name) LIKE ? OR c.phone LIKE ?)"
        params.extend([f"%{client}%", f"%{client}%"])
    if technician:
        query += " AND t.name = ?"
        params.append(technician)
    if category:
        query += " AND s.category = ?"
        params.append(category)
    if service:
        query += " AND s.name = ?"
        params.append(service)
    if payment:
        query += " AND pm.name = ?"
        params.append(payment)
    if start_date:
        query += " AND v.visit_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND v.visit_date <= ?"
        params.append(end_date)

    query += " ORDER BY v.visit_date DESC"
    visits = conn.execute(query, params).fetchall()
    conn.close()

    # Render HTML for PDF
    html = render_template('visits_pdf.html', visits=visits)
    output = BytesIO()
    pisa.CreatePDF(html, dest=output)
    output.seek(0)
    return send_file(output, download_name="visits_log.pdf", as_attachment=True)

@app.route('/add-visit', methods=['GET', 'POST'])
def add_visit():
    conn = get_db_connection()

    if request.method == 'POST':
        client_name = request.form.get('client').strip()
        visit_date = request.form.get('visit_date')
        payment_method_name = request.form.get('payment_method')

        # Get or create client
        client = conn.execute('SELECT id FROM clients WHERE name = ?', (client_name,)).fetchone()
        if client:
            client_id = client['id']
        else:
            conn.execute('INSERT INTO clients (name) VALUES (?)', (client_name,))
            client_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

        # Get payment method id
        payment_method_id = conn.execute('SELECT id FROM payment_methods WHERE name = ?', (payment_method_name,)).fetchone()
        if not payment_method_id:
            flash('Invalid payment method selected.', 'danger')
            return redirect(url_for('add_visit'))
        payment_method_id = payment_method_id['id']

        # Insert visit
        conn.execute('INSERT INTO visits (client_id, visit_date, payment_method_id) VALUES (?, ?, ?)',
                     (client_id, visit_date, payment_method_id))
        visit_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

        # Insert services
        i = 0
        while f'service_{i}' in request.form:
            category = request.form.get(f'category_{i}')
            service_name = request.form.get(f'service_{i}')
            technician_name = request.form.get(f'technician_{i}')
            invoice = float(request.form.get(f'invoice_{i}') or 0)
            discount = float(request.form.get(f'discount_{i}') or 0)
            net_invoice = float(request.form.get(f'net_invoice_{i}') or (invoice * (1 - discount / 100)))
            tips = float(request.form.get(f'tips_{i}') or 0)

            # Find technician ID
            technician = conn.execute('SELECT id FROM technicians WHERE name = ?', (technician_name,)).fetchone()
            if technician:
                technician_id = technician['id']
            else:
                flash(f'Technician {technician_name} not found.', 'danger')
                continue

            # Find service ID
            service = conn.execute('SELECT id FROM services WHERE name = ?', (service_name,)).fetchone()
            if service:
                service_id = service['id']
            else:
                flash(f'Service {service_name} not found.', 'danger')
                continue

            # Save to visit_services
            conn.execute('''
                INSERT INTO visit_services (visit_id, service_id, technician_id, invoice, discount, net_invoice, tips)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (visit_id, service_id, technician_id, invoice, discount, net_invoice, tips))
            i += 1

        conn.commit()
        conn.close()
        flash('Visit added successfully!', 'success')
        return redirect(url_for('visits_log'))

    # GET method: populate form
    categories = [row['category'] for row in conn.execute("SELECT DISTINCT category FROM services WHERE category IS NOT NULL").fetchall()]
    services = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM services WHERE name IS NOT NULL").fetchall()]
    technicians = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM technicians WHERE name IS NOT NULL").fetchall()]
    payments = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM payment_methods WHERE name IS NOT NULL").fetchall()]
    conn.close()

    return render_template('add_visit.html', categories=categories, services=services, technicians=technicians, payments=payments)



@app.route('/edit-visit/<int:visit_id>', methods=['GET', 'POST'])
def edit_visit(visit_id):
    conn = get_db_connection()

    if request.method == 'POST':
        visit_date = request.form['visit_date']
        client_id = request.form['client_id']
        payment_method_id = request.form['payment_method_id']
        service_id = request.form['service_id']
        technician_id = request.form['technician_id']
        invoice = request.form['invoice']
        discount = request.form['discount']
        net_invoice = request.form['net_invoice']
        tips = request.form['tips']

        conn.execute("""
            UPDATE visits SET visit_date = ?, client_id = ?, payment_method_id = ?
            WHERE id = ?
        """, (visit_date, client_id, payment_method_id, visit_id))

        conn.execute("""
            UPDATE visit_services SET service_id = ?, technician_id = ?, invoice = ?, discount = ?, net_invoice = ?, tips = ?
            WHERE visit_id = ?
        """, (service_id, technician_id, invoice, discount, net_invoice, tips, visit_id))

        conn.commit()
        conn.close()
        return redirect(url_for('visits_log'))

    visit = conn.execute("""
        SELECT v.id AS visit_id, v.visit_date, v.client_id, c.name AS client_name, v.payment_method_id,
               vs.service_id, s.name AS service_name, s.category AS category,
               vs.technician_id, t.name AS technician_name,
               vs.invoice, vs.discount, vs.net_invoice, vs.tips
        FROM visits v
        JOIN clients c ON v.client_id = c.id
        JOIN visit_services vs ON vs.visit_id = v.id
        JOIN services s ON vs.service_id = s.id
        JOIN technicians t ON vs.technician_id = t.id
        WHERE v.id = ?
    """, (visit_id,)).fetchone()

    clients = conn.execute("SELECT id, name FROM clients").fetchall()
    services = conn.execute("SELECT id, name FROM services").fetchall()
    technicians = conn.execute("SELECT id, name FROM technicians").fetchall()
    payments = conn.execute("SELECT id, name FROM payment_methods").fetchall()
    categories = conn.execute("SELECT DISTINCT category FROM services WHERE category IS NOT NULL").fetchall()

    conn.close()

    return render_template('edit_visit.html', visit=visit, clients=clients, services=services, technicians=technicians, payments=payments, categories=categories)
@app.route('/delete-visit/<int:visit_id>', methods=['POST'])
def delete_visit(visit_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM visit_services WHERE visit_id = ?", (visit_id,))
    conn.execute("DELETE FROM visits WHERE id = ?", (visit_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('visits_log'))


# --- Run App ---
from routes import main  # ✅ Import the blueprint
app.register_blueprint(main)  # ✅ Register it

if __name__ == '__main__':
    app.run(debug=True)
