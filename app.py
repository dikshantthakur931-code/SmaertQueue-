from flask import Flask, request, jsonify, render_template
from datetime import datetime, timedelta
import pymysql
import random

app = Flask(__name__)

# ==========================================
# ⚙️ MYSQL DATABASE CONFIGURATION
# ==========================================
DB_HOST = 'localhost'
DB_USER = 'root'
DB_PASS = 'Dikshant@123' 
DB_NAME = 'smartqueue'

def get_db_connection():
    return pymysql.connect(
        host=DB_HOST, 
        user=DB_USER, 
        password=DB_PASS, 
        database=DB_NAME, 
        cursorclass=pymysql.cursors.DictCursor
    )

# ==========================================
# 🖥️ FRONTEND GUI ROUTES (The Portal)
# ==========================================
@app.route('/')
def portal():
    return render_template('portal.html')

@app.route('/doctor/<username>')
def doctor_view(username):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT users.user_id, users.full_name, hospitals.name as hospital_name 
        FROM users 
        JOIN hospitals ON users.hospital_id = hospitals.hospital_id 
        WHERE username = %s AND role = 'doctor'
    """, (username,))
    doc = cursor.fetchone()
    conn.close()

    if not doc:
        return f"<h1>Error: Doctor {username} not found! Try D1H1 or D2H1.</h1>", 404

    return render_template('index.html', doctor=doc)

@app.route('/patient')
def patient_view():
    return render_template('patient.html')

@app.route('/lab')
def lab_view():
    return render_template('lab.html')

# ==========================================
# 👨‍⚕️ DOCTOR MODULE: CORE ENGINE
# ==========================================
@app.route('/api/doctor/<int:doctor_id>/call_next', methods=['POST'])
def call_next_patient(doctor_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT visit_id, patient_name, priority_tier, status, updated_at 
            FROM visits 
            WHERE doctor_id = %s AND status IN ('waiting', 'in_transit')
            ORDER BY priority_tier ASC, updated_at ASC
        """, (doctor_id,))
        queue = cursor.fetchall()

        if not queue:
            return jsonify({"message": "Queue is empty. Take a break!"}), 200

        next_patient = None
        current_time = datetime.now()
        transit_buffer_minutes = 10 

        for patient in queue:
            if patient['status'] == 'in_transit':
                time_walking = (current_time - patient['updated_at']).total_seconds() / 60
                if time_walking < transit_buffer_minutes:
                    continue
                else:
                    next_patient = patient
                    break
            else:
                next_patient = patient
                break

        if not next_patient:
            return jsonify({
                "message": "Top priority patients are currently in transit. Waiting for arrival.",
                "transit_status": "active"
            }), 200

        cursor.execute("""
            UPDATE visits SET status = 'in_consult', updated_at = CURRENT_TIMESTAMP WHERE visit_id = %s
        """, (next_patient['visit_id'],))
        conn.commit()

        return jsonify({
            "message": f"Called {next_patient['patient_name']} successfully.",
            "visit_id": next_patient['visit_id'],
            "priority_tier": next_patient['priority_tier']
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/doctor/send_to_lab', methods=['POST'])
def send_to_lab():
    data = request.json
    visit_id = data.get('visit_id')
    doctor_id = data.get('doctor_id')
    lab_type = data.get('lab_type', 'Pathology') 

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE visits SET status = 'in_transit', updated_at = CURRENT_TIMESTAMP WHERE visit_id = %s", (visit_id,))
        cursor.execute("""
            INSERT INTO lab_orders (visit_id, ordered_by_id, lab_type, status, ordered_at)
            VALUES (%s, %s, %s, 'patient_in_transit', CURRENT_TIMESTAMP)
        """, (visit_id, doctor_id, lab_type))
        conn.commit()
        return jsonify({"message": f"Patient routed to {lab_type}. Transit buffer initiated."}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/doctor/<int:doctor_id>/queue', methods=['GET'])
def get_doctor_queue(doctor_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT visit_id, patient_name, priority_tier, status, updated_at 
            FROM visits 
            WHERE doctor_id = %s AND status IN ('waiting', 'in_transit')
            ORDER BY priority_tier ASC, updated_at ASC
        """, (doctor_id,))
        queue = cursor.fetchall()
        
        response = {
            "priority_1_labs": [p for p in queue if p['priority_tier'] == 1],
            "priority_2_referrals": [p for p in queue if p['priority_tier'] == 2],
            "priority_3_normal": [p for p in queue if p['priority_tier'] == 3]
        }
        return jsonify(response), 200
    finally:
        cursor.close()
        conn.close()

# ==========================================
# 📱 PATIENT MODULE: JOIN & TRACK
# ==========================================
@app.route('/api/patient/join', methods=['POST'])
def join_queue():
    data = request.json
    doc_username = data.get('doc_username', '').upper()
    patient_name = data.get('patient_name', 'Walk-in Patient')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id FROM users WHERE username = %s AND role = 'doctor'", (doc_username,))
        doc = cursor.fetchone()
        
        if not doc:
            return jsonify({"error": "Doctor ID not found. Please check and try again."}), 404

        cursor.execute("""
            INSERT INTO visits (doctor_id, patient_name, priority_tier, status) 
            VALUES (%s, %s, 3, 'waiting')
        """, (doc['user_id'], patient_name))
        conn.commit()
        
        return jsonify({"message": "Successfully joined the queue!", "visit_id": cursor.lastrowid}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/patient/<int:visit_id>/status', methods=['GET'])
def check_status(visit_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT doctor_id, priority_tier, updated_at, status FROM visits WHERE visit_id = %s", (visit_id,))
        patient = cursor.fetchone()
        
        if not patient:
            return jsonify({"error": "Visit not found"}), 404

        if patient['status'] == 'in_consult':
            return jsonify({"status": "in_consult", "message": "It's your turn! Please enter the doctor's room."})
        if patient['status'] == 'discharged':
            return jsonify({"status": "discharged", "message": "Visit complete. Hope you feel better!"})

        cursor.execute("""
            SELECT COUNT(*) as people_ahead FROM visits 
            WHERE doctor_id = %s AND status IN ('waiting', 'in_transit')
            AND (priority_tier < %s OR (priority_tier = %s AND updated_at < %s))
        """, (patient['doctor_id'], patient['priority_tier'], patient['priority_tier'], patient['updated_at']))
        
        position = cursor.fetchone()['people_ahead'] + 1 
        return jsonify({"status": patient['status'], "position": position, "eta_minutes": position * 10}), 200
    finally:
        cursor.close()
        conn.close()

# ==========================================
# 🔬 LAB MODULE: PATHOLOGY WORKFLOW
# ==========================================
@app.route('/api/lab/<string:lab_type>/queue', methods=['GET'])
def get_lab_queue(lab_type):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT order_id, visit_id, ordered_by_id, status, ordered_at 
            FROM lab_orders WHERE lab_type = %s AND status NOT IN ('completed') ORDER BY ordered_at ASC
        """, (lab_type,))
        return jsonify(cursor.fetchall()), 200
    finally:
        cursor.close()
        conn.close()

@app.route('/api/lab/update_status', methods=['POST'])
def update_lab_status():
    data = request.json
    order_id = data.get('order_id')
    visit_id = data.get('visit_id')
    new_status = data.get('status') 
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE lab_orders SET status = %s WHERE order_id = %s", (new_status, order_id))
        if new_status == 'completed':
            cursor.execute("""
                UPDATE visits SET priority_tier = 1, status = 'in_transit', updated_at = CURRENT_TIMESTAMP WHERE visit_id = %s
            """, (visit_id,))
        conn.commit()
        return jsonify({"message": f"Lab order updated to {new_status}!"}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# ==========================================
# 🚀 SYSTEM INITIALIZATION: MULTI-HOSPITAL
# ==========================================
@app.route('/api/setup', methods=['GET', 'POST'])
def setup_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DROP TABLE IF EXISTS lab_orders")
        cursor.execute("DROP TABLE IF EXISTS visits")
        cursor.execute("DROP TABLE IF EXISTS users")
        cursor.execute("DROP TABLE IF EXISTS hospitals")

        cursor.execute("CREATE TABLE hospitals (hospital_id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) NOT NULL)")
        cursor.execute("CREATE TABLE users (user_id INT AUTO_INCREMENT PRIMARY KEY, hospital_id INT, username VARCHAR(50), role VARCHAR(50), full_name VARCHAR(255))")
        cursor.execute("CREATE TABLE visits (visit_id INT AUTO_INCREMENT PRIMARY KEY, doctor_id INT, patient_name VARCHAR(255), priority_tier INT DEFAULT 3, status VARCHAR(50) DEFAULT 'waiting', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE lab_orders (order_id INT AUTO_INCREMENT PRIMARY KEY, visit_id INT, ordered_by_id INT, lab_type VARCHAR(100), status VARCHAR(50), ordered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

        first_names = ["James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", "William", "Elizabeth"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez"]

        for h in range(1, 11):
            cursor.execute("INSERT INTO hospitals (name) VALUES (%s)", (f"Hospital {h}",))
            hospital_id = cursor.lastrowid
            for d in range(1, 4):
                full_name = f"Dr. {random.choice(first_names)} {random.choice(last_names)}"
                cursor.execute("INSERT INTO users (hospital_id, username, role, full_name) VALUES (%s, %s, 'doctor', %s)", (hospital_id, f"D{d}H{h}", full_name))

        conn.commit()
        return jsonify({"message": "Successfully created 10 Hospitals and 30 Doctors with randomized names!"}), 200
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
