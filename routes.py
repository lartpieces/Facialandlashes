from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask import send_file, render_template_string
from db import get_db_connection, fetch_clients_with_last_visit
import datetime
import pandas as pd
from io import BytesIO
from xhtml2pdf import pisa

main = Blueprint('main', __name__)

@main.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password')
        if password == '1107':  # Replace with your own secure password
            session['authenticated'] = True
            return redirect(url_for('main.revenue_report'))
        else:
            error = "Incorrect password"
    return render_template('login.html', error=error)

@main.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('main.home'))

@main.route('/')
def home():
    return render_template('home.html')

@main.route('/clients')
def clients_list():
    search = request.args.get('search', '').strip().lower()
    clients = fetch_clients_with_last_visit()
    if search:
        clients = [c for c in clients if search in c['name'].lower() or search in c['phone']]
    return render_template('clients_list.html', clients=clients, search=search)

@main.route('/add-client', methods=['GET', 'POST'])
def add_client():
    if request.method == 'POST':
        name = request.form['name'].strip()
        phone = request.form['phone'].strip()
        if name and phone:
            conn = get_db_connection()
            conn.execute("INSERT INTO clients (name, phone) VALUES (?, ?)", (name, phone))
            conn.commit()
            conn.close()
            return redirect(url_for('main.clients_list'))
    return render_template('add_client.html')

@main.route('/technicians')
def technicians():
    conn = get_db_connection()
    techs = conn.execute("SELECT * FROM technicians ORDER BY name").fetchall()
    conn.close()
    return render_template('technicians.html', technicians=techs)

@main.route('/add-technician', methods=['POST'])
def add_technician():
    name = request.form['name'].strip()
    if name:
        conn = get_db_connection()
        conn.execute("INSERT INTO technicians (name) VALUES (?)", (name,))
        conn.commit()
        conn.close()
    return redirect(url_for('main.technicians'))

@main.route('/edit-technician/<int:tech_id>', methods=['POST'])
def edit_technician(tech_id):
    name = request.form['name'].strip()
    if name:
        conn = get_db_connection()
        conn.execute("UPDATE technicians SET name = ? WHERE id = ?", (name, tech_id))
        conn.commit()
        conn.close()
    return redirect(url_for('main.technicians'))

@main.route('/delete-technician/<int:tech_id>', methods=['POST'])
def delete_technician(tech_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM technicians WHERE id = ?", (tech_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('main.technicians'))

@main.route('/performance')
def performance():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    query = """
        SELECT t.name AS technician, COUNT(vs.id) AS total_visits
        FROM technicians t
        LEFT JOIN visit_services vs ON t.id = vs.technician_id
        LEFT JOIN visits v ON v.id = vs.visit_id
        WHERE 1 = 1
    """
    params = []

    if start_date:
        query += " AND v.visit_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND v.visit_date <= ?"
        params.append(end_date)

    query += " GROUP BY t.id ORDER BY t.name"

    conn = get_db_connection()
    results = conn.execute(query, params).fetchall()
    conn.close()

    return render_template('performance.html', data=results, start_date=start_date, end_date=end_date)

@main.route('/follow-ups')
def follow_ups():
    conn = get_db_connection()
    selected_tech = request.args.get('technician', '')

    today = datetime.date.today()
    three_weeks_ago = today - datetime.timedelta(days=21)
    week_start = three_weeks_ago - datetime.timedelta(days=three_weeks_ago.weekday())
    week_end = week_start + datetime.timedelta(days=6)

    query = """
        SELECT c.id, c.name, c.phone,
               MAX(v.visit_date) AS last_visit,
               t.name AS technician,
               s.name AS service,
               f.followed_up_at,
               f.note
        FROM clients c
        JOIN visits v ON v.client_id = c.id
        LEFT JOIN visit_services vs ON vs.visit_id = v.id
        LEFT JOIN technicians t ON vs.technician_id = t.id
        LEFT JOIN services s ON vs.service_id = s.id
        LEFT JOIN follow_ups f ON f.client_id = c.id
        WHERE DATE(v.visit_date) BETWEEN ? AND ?
    """
    params = [week_start.isoformat(), week_end.isoformat()]

    if selected_tech:
        query += " AND t.name = ?"
        params.append(selected_tech)

    query += " GROUP BY c.id ORDER BY last_visit DESC"

    clients = conn.execute(query, params).fetchall()
    technicians = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM technicians WHERE name IS NOT NULL").fetchall()]
    conn.close()
    return render_template('follow_ups.html', clients=clients, week=week_start, selected_tech=selected_tech, technicians=technicians)

@main.route('/mark-followed-up', methods=['POST'])
def mark_followed_up_bulk():
    conn = get_db_connection()
    client_id = request.form.get('follow_up_id')
    action = request.form.get('action')
    note_field = f"note_{client_id}"
    note = request.form.get(note_field, '').strip()

    if action == 'mark':
        now = datetime.datetime.now().isoformat()
        existing = conn.execute("SELECT 1 FROM follow_ups WHERE client_id = ?", (client_id,)).fetchone()
        if existing:
            conn.execute("UPDATE follow_ups SET followed_up_at = ?, note = ? WHERE client_id = ?", (now, note, client_id))
        else:
            conn.execute("INSERT INTO follow_ups (client_id, followed_up_at, note) VALUES (?, ?, ?)", (client_id, now, note))
        flash("Follow-up marked successfully!", "success")

    elif action == 'unmark':
        conn.execute("UPDATE follow_ups SET followed_up_at = NULL, note = ? WHERE client_id = ?", (note, client_id))
        flash("Follow-up unmarked.", "info")

    conn.commit()
    conn.close()
    return redirect(url_for('main.follow_ups'))

@main.route('/visited-between', methods=['GET', 'POST'])
def visited_between():
    results = []
    start_date = end_date = selected_tech = ''

    conn = get_db_connection()
    technicians = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM technicians WHERE name IS NOT NULL").fetchall()]

    if request.method == 'POST':
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        selected_tech = request.form.get('technician', '')

        query = """
            SELECT DISTINCT c.id, c.name, c.phone,
                   MAX(v.visit_date) AS last_visit,
                   t.name AS technician,
                   s.name AS service
            FROM clients c
            JOIN visits v ON v.client_id = c.id
            LEFT JOIN visit_services vs ON vs.visit_id = v.id
            LEFT JOIN technicians t ON vs.technician_id = t.id
            LEFT JOIN services s ON vs.service_id = s.id
            WHERE DATE(v.visit_date) BETWEEN ? AND ?
        """
        params = [start_date, end_date]

        if selected_tech:
            query += " AND t.name = ?"
            params.append(selected_tech)

        query += " GROUP BY c.id ORDER BY last_visit DESC"
        results = conn.execute(query, params).fetchall()

    conn.close()
    return render_template('visited_between.html', clients=results, start_date=start_date, end_date=end_date, selected_tech=selected_tech, technicians=technicians)

@main.route('/last-visit-between', methods=['GET', 'POST'])
def last_visit_between():
    clients = []
    start_date = end_date = selected_tech = ''

    conn = get_db_connection()
    technicians = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM technicians WHERE name IS NOT NULL").fetchall()]

    if request.method == 'POST':
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        selected_tech = request.form.get('technician', '')

        query = """
            SELECT c.id, c.name, c.phone,
                   MAX(v.visit_date) AS last_visit,
                   t.name AS technician,
                   s.name AS service
            FROM clients c
            LEFT JOIN visits v ON c.id = v.client_id
            LEFT JOIN visit_services vs ON v.id = vs.visit_id
            LEFT JOIN technicians t ON vs.technician_id = t.id
            LEFT JOIN services s ON vs.service_id = s.id
            GROUP BY c.id
            HAVING DATE(last_visit) BETWEEN ? AND ?
        """
        params = [start_date, end_date]

        if selected_tech:
            query += " AND technician = ?"
            params.append(selected_tech)

        query += " ORDER BY last_visit DESC"
        clients = conn.execute(query, params).fetchall()

    conn.close()
    return render_template('last_visit_between.html', clients=clients, start_date=start_date, end_date=end_date, selected_tech=selected_tech, technicians=technicians)

@main.route('/followed-up-clients', methods=['GET'])
def followed_up_clients():
    selected_tech = request.args.get('technician', '')
    conn = get_db_connection()

    query = """
        SELECT c.id, c.name, c.phone,
               MAX(v.visit_date) AS last_visit,
               t.name AS technician,
               s.name AS service,
               f.followed_up_at,
               f.note
        FROM follow_ups f
        JOIN clients c ON c.id = f.client_id
        LEFT JOIN visits v ON v.client_id = c.id
        LEFT JOIN visit_services vs ON vs.visit_id = v.id
        LEFT JOIN technicians t ON vs.technician_id = t.id
        LEFT JOIN services s ON vs.service_id = s.id
        WHERE f.followed_up_at IS NOT NULL
    """

    params = []
    if selected_tech:
        query += " AND t.name = ?"
        params.append(selected_tech)

    query += " GROUP BY c.id ORDER BY f.followed_up_at DESC"

    clients = conn.execute(query, params).fetchall()
    technicians = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM technicians WHERE name IS NOT NULL").fetchall()]
    conn.close()
    return render_template('followed_up_clients.html', clients=clients, technicians=technicians, selected_tech=selected_tech)
@main.route('/services', methods=['GET', 'POST'])
def services():
    conn = get_db_connection()

    if request.method == 'POST':
        category = request.form.get('category', '').strip()
        service = request.form.get('service', '').strip()
        if category and service:
            conn.execute("INSERT INTO services (category, name) VALUES (?, ?)", (category, service))
            conn.commit()
            flash("Service added successfully!", "success")

    services_list = conn.execute("SELECT * FROM services ORDER BY category, name").fetchall()
    conn.close()
    return render_template('services.html', services=services_list)


@main.route('/edit-service/<int:service_id>', methods=['POST'])
def edit_service(service_id):
    category = request.form.get('edit_category', '').strip()
    name = request.form.get('edit_service', '').strip()

    if category and name:
        conn = get_db_connection()
        conn.execute("UPDATE services SET category = ?, name = ? WHERE id = ?", (category, name, service_id))
        conn.commit()
        conn.close()
        flash("Service updated successfully!", "success")
    return redirect(url_for('main.services'))


@main.route('/delete-service/<int:service_id>', methods=['POST'])
def delete_service(service_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM services WHERE id = ?", (service_id,))
    conn.commit()
    conn.close()
    flash("Service deleted successfully!", "info")
    return redirect(url_for('main.services'))

@main.route('/revenue-report')
def revenue_report():
    if not session.get('authenticated'):
        return redirect(url_for('main.login'))
    conn = get_db_connection()

    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    technician = request.args.get('technician', '')
    category = request.args.get('category', '')
    service = request.args.get('service', '')
    payment = request.args.get('payment', '')

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

    if start_date:
        query += " AND v.visit_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND v.visit_date <= ?"
        params.append(end_date)
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

    query += " ORDER BY v.visit_date DESC"

    visits = conn.execute(query, params).fetchall()

    # Totals calculation
    total_invoice = sum(row['invoice'] or 0 for row in visits)
    total_net_invoice = sum(row['net_invoice'] or 0 for row in visits)
    total_tips = sum(row['tips'] or 0 for row in visits)

    # Dropdown data
    technicians = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM technicians WHERE name IS NOT NULL").fetchall()]
    categories = [row['category'] for row in conn.execute("SELECT DISTINCT category FROM services WHERE category IS NOT NULL").fetchall()]
    services = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM services WHERE name IS NOT NULL").fetchall()]
    payments = [row['name'] for row in conn.execute("SELECT DISTINCT name FROM payment_methods WHERE name IS NOT NULL").fetchall()]

    conn.close()

    return render_template(
        'revenue_report.html',
        visits=visits,
        totals={
            'invoice': total_invoice,
            'net_invoice': total_net_invoice,
            'tips': total_tips
        },
        technicians=technicians,
        categories=categories,
        services=services,
        payments=payments,
        selected_tech=technician,
        selected_category=category,
        selected_service=service,
        selected_payment=payment,
        start_date=start_date,
        end_date=end_date
    )
@main.route('/export/revenue/excel')
def export_revenue_excel():
    conn = get_db_connection()

    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    technician = request.args.get('technician', '')
    category = request.args.get('category', '')
    service = request.args.get('service', '')
    payment = request.args.get('payment', '')

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

    if start_date:
        query += " AND v.visit_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND v.visit_date <= ?"
        params.append(end_date)
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

    query += " ORDER BY v.visit_date DESC"
    data = conn.execute(query, params).fetchall()
    conn.close()

    df = pd.DataFrame(data, columns=[
        "visit_date", "client_name", "phone", "technician", "category", "service",
        "invoice", "discount", "net_invoice", "tips", "payment_method"
    ])

    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name="Revenue")
    output.seek(0)

    return send_file(output, download_name="revenue_report.xlsx", as_attachment=True)

# ----------------------------------------

@main.route('/export/revenue/pdf')
def export_revenue_pdf():
    conn = get_db_connection()

    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    technician = request.args.get('technician', '')
    category = request.args.get('category', '')
    service = request.args.get('service', '')
    payment = request.args.get('payment', '')

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

    if start_date:
        query += " AND v.visit_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND v.visit_date <= ?"
        params.append(end_date)
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

    query += " ORDER BY v.visit_date DESC"
    visits = conn.execute(query, params).fetchall()
    conn.close()

    html = render_template_string("""
        <style>
        table {
            width: 100%;
            border-collapse: collapse;
            font-family: sans-serif;
            font-size: 10pt;
        }
        th, td {
            border: 1px solid #999;
            padding: 6px;
            text-align: left;
        }
        h2 {
            text-align: center;
        }
        </style>

        <h2>💵 Revenue Report</h2>
        <table>
            <thead>
                <tr>
                    <th>Date</th><th>Client</th><th>Phone</th><th>Technician</th>
                    <th>Category</th><th>Service</th><th>Invoice</th>
                    <th>Discount</th><th>Net</th><th>Tips</th><th>Payment</th>
                </tr>
            </thead>
            <tbody>
            {% for v in visits %}
                <tr>
                    <td>{{ v.visit_date }}</td>
                    <td>{{ v.client_name }}</td>
                    <td>{{ v.phone }}</td>
                    <td>{{ v.technician }}</td>
                    <td>{{ v.category }}</td>
                    <td>{{ v.service }}</td>
                    <td>{{ v.invoice }}</td>
                    <td>{{ v.discount }}</td>
                    <td>{{ v.net_invoice }}</td>
                    <td>{{ v.tips }}</td>
                    <td>{{ v.payment_method }}</td>
                </tr>
            {% endfor %}
            </tbody>
        </table>
    """, visits=visits)

    pdf_output = BytesIO()
    pisa.CreatePDF(html, dest=pdf_output)
    pdf_output.seek(0)

    return send_file(pdf_output, download_name="revenue_report.pdf", as_attachment=True)
@main.route('/technician-revenue', methods=['GET', 'POST'])
def technician_revenue():
    if not session.get('authenticated'):
        return redirect(url_for('main.login'))
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    conn = get_db_connection()
    params = []
    query = """
        SELECT t.name AS name,
               SUM(vs.invoice) AS invoice,
               SUM(vs.net_invoice) AS net_invoice,
               SUM(vs.tips) AS tips
        FROM visit_services vs
        JOIN technicians t ON vs.technician_id = t.id
        JOIN visits v ON vs.visit_id = v.id
        WHERE 1=1
    """

    if start_date:
        query += " AND v.visit_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND v.visit_date <= ?"
        params.append(end_date)

    query += " GROUP BY t.name ORDER BY t.name"

    technician_data = conn.execute(query, params).fetchall()
    conn.close()

    techs = [{
        'name': row['name'],
        'invoice': row['invoice'] or 0,
        'net_invoice': row['net_invoice'] or 0,
        'tips': row['tips'] or 0,
        'share': 50.0
    } for row in technician_data]

    return render_template('technician_revenue.html',
                           technician_data=techs,
                           start_date=start_date,
                           end_date=end_date)

@main.route('/export-technician-revenue', methods=['POST'])
def export_technician_revenue():
    format = request.form.get('format')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    conn = get_db_connection()
    query = """
        SELECT t.name, 
               SUM(vs.invoice) AS invoice, 
               SUM(vs.net_invoice) AS net_invoice, 
               SUM(vs.tips) AS tips
        FROM visit_services vs
        JOIN technicians t ON vs.technician_id = t.id
        JOIN visits v ON vs.visit_id = v.id
        WHERE (? IS NULL OR v.visit_date >= ?)
          AND (? IS NULL OR v.visit_date <= ?)
        GROUP BY t.name
    """
    params = [start_date, start_date, end_date, end_date]
    technician_data = conn.execute(query, params).fetchall()
    conn.close()

    rows = []
    for row in technician_data:
        share = float(request.form.get(f'share_{row["name"]}', 50))
        net = row["net_invoice"] or 0
        tips = row["tips"] or 0
        salary = round(net * (share / 100), 2)
        total_salary = salary + tips
        rows.append({
            'Technician': row["name"],
            '% Share': share,
            'Invoice': row["invoice"] or 0,
            'Net Invoice': net,
            'Tips': tips,
            'Salary': salary,
            'Total Salary': total_salary,
        })

    df = pd.DataFrame(rows)

    if format == 'excel':
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name="Technician Revenue")
        output.seek(0)
        return send_file(output, download_name="technician_revenue.xlsx", as_attachment=True)

    elif format == 'pdf':
        html = render_template_string("""
            <style>
                table { width: 100%; border-collapse: collapse; font-size: 10pt; }
                th, td { border: 1px solid #888; padding: 4px; }
                h2 { text-align: center; }
            </style>
            <h2>Technician Revenue Summary</h2>
            <table>
                <thead>
                    <tr>
                        <th>Technician</th><th>% Share</th><th>Invoice</th>
                        <th>Net Invoice</th><th>Tips</th><th>Salary</th><th>Total</th>
                    </tr>
                </thead>
                <tbody>
                {% for r in rows %}
                    <tr>
                        <td>{{ r['Technician'] }}</td>
                        <td>{{ r['% Share'] }}</td>
                        <td>{{ r['Invoice'] }}</td>
                        <td>{{ r['Net Invoice'] }}</td>
                        <td>{{ r['Tips'] }}</td>
                        <td>{{ r['Salary'] }}</td>
                        <td>{{ r['Total Salary'] }}</td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
        """, rows=rows)

        output = BytesIO()
        pisa.CreatePDF(html, dest=output)
        output.seek(0)
        return send_file(output, download_name="technician_revenue.pdf", as_attachment=True)

    return redirect(url_for('main.technician_revenue'))

