"""Tugas Minggu 12 - Modul Presensi QR Code."""
import io
import os
import secrets
import sqlite3
import time
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

import jwt
import qrcode
from flask import Flask, g, jsonify, redirect, render_template, request, send_file, session, url_for
from openpyxl import Workbook
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
# Kunci disimpan agar login dan QR tetap valid setelah aplikasi dimulai ulang.
key_file = os.path.join(app.instance_path, 'secret.key')
os.makedirs(app.instance_path, exist_ok=True)
if not os.path.exists(key_file):
    with open(key_file, 'w') as f:
        f.write(secrets.token_hex(32))
with open(key_file) as f:
    app.secret_key = os.environ.get('SECRET_KEY') or f.read().strip()
app.config.update(DATABASE=os.path.join(app.instance_path, 'presensi.db'),
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  MAX_CONTENT_LENGTH=1024 * 1024)
WIB = ZoneInfo('Asia/Jakarta')
scan_attempts = defaultdict(deque)


def now():
    return datetime.now(WIB)


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    conn = g.pop('db', None)
    if conn is not None:
        conn.close()


def init_db():
    db().executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, name TEXT NOT NULL,
        password TEXT NOT NULL, role TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, lecturer TEXT NOT NULL REFERENCES users(id));
    CREATE TABLE IF NOT EXISTS enrollments (
        course_id INTEGER REFERENCES courses(id), nim TEXT REFERENCES users(id),
        PRIMARY KEY(course_id, nim));
    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id),
        starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, qr_jti TEXT);
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY, schedule_id INTEGER NOT NULL REFERENCES schedules(id),
        nim TEXT NOT NULL REFERENCES users(id), timestamp TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('hadir','terlambat')),
        UNIQUE(schedule_id, nim));
    ''')
    if db().execute('SELECT COUNT(*) FROM users').fetchone()[0]:
        return
    for uid, name, role in [('dosen', 'Pak Andi', 'dosen'), ('23001', 'Adi', 'mahasiswa'),
                            ('23002', 'Citra', 'mahasiswa'), ('23003', 'Budi', 'mahasiswa')]:
        db().execute('INSERT INTO users VALUES (?,?,?,?)',
                     (uid, name, generate_password_hash('belajar123'), role))
    db().executemany('INSERT INTO courses VALUES (?,?,?)',
                     [(1, 'Pemrograman Berorientasi Objek', 'dosen'), (2, 'Basis Data', 'dosen')])
    db().executemany('INSERT INTO enrollments VALUES (?,?)', [(1, '23001'), (1, '23002'), (2, '23003')])
    # Data contoh empat pertemuan sebelumnya, masing-masing seminggu sekali.
    start = now().replace(microsecond=0) - timedelta(minutes=5)
    for i in range(1, 6):
        t = start - timedelta(weeks=5-i)
        db().execute('INSERT INTO schedules VALUES (?,?,?,?,NULL)',
                     (i, 1, t.isoformat(), (t + timedelta(minutes=100)).isoformat()))
        if i <= 4:
            for nim in ['23001', '23002']:
                if (nim == '23001' and i in [1, 3]) or (nim == '23002' and i <= 3):
                    db().execute('INSERT INTO attendance(schedule_id,nim,timestamp,status) VALUES (?,?,?,?)',
                                 (i, nim, (t + timedelta(minutes=2)).isoformat(), 'hadir'))
    db().commit()


def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = db().execute('SELECT * FROM users WHERE id=?', (session.get('uid'),)).fetchone()
            if not user:
                if request.path.startswith('/attendance/') or request.path == '/insights':
                    return jsonify(error='Silakan login terlebih dahulu.'), 401
                return redirect(url_for('login'))
            if role and user['role'] != role:
                return jsonify(error='Akses tidak diizinkan.'), 403
            g.user = user
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@app.before_request
def check_csrf():
    session.setdefault('csrf', secrets.token_hex(24))
    if request.method == 'POST':
        supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf', '')
        if not secrets.compare_digest(session['csrf'], supplied):
            return jsonify(error='Form tidak valid. Muat ulang halaman.'), 403


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        user = db().execute('SELECT * FROM users WHERE id=?', (request.form.get('uid'),)).fetchone()
        if user and check_password_hash(user['password'], request.form.get('password', '')):
            session.clear()
            session.update(uid=user['id'], csrf=secrets.token_hex(24))
            return redirect(url_for('index'))
        error = 'ID atau password salah.'
    return render_template('login.html', error=error)


@app.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.get('/')
@login_required()
def index():
    if g.user['role'] == 'dosen':
        schedules = db().execute('''SELECT s.*, c.name FROM schedules s JOIN courses c ON c.id=s.course_id
                                  WHERE c.lecturer=? ORDER BY starts_at DESC''', (g.user['id'],)).fetchall()
    else:
        schedules = db().execute('''SELECT s.*, c.name FROM schedules s JOIN courses c ON c.id=s.course_id
            JOIN enrollments e ON e.course_id=c.id WHERE e.nim=? ORDER BY starts_at DESC''',
                                (g.user['id'],)).fetchall()
    courses = db().execute('SELECT * FROM courses WHERE lecturer=?', (g.user['id'],)).fetchall()
    return render_template('index.html', user=g.user, schedules=schedules, reports=report_rows(),
                           courses=courses, current_time=now().strftime('%Y-%m-%dT%H:%M'))


@app.post('/schedules')
@login_required('dosen')
def create_schedule():
    course = db().execute('SELECT id FROM courses WHERE id=? AND lecturer=?',
                          (request.form.get('course_id'), g.user['id'])).fetchone()
    if not course:
        return jsonify(error='Mata kuliah tidak ditemukan.'), 404
    try:
        start = datetime.strptime(request.form.get('starts_at', ''), '%Y-%m-%dT%H:%M').replace(tzinfo=WIB)
    except ValueError:
        return jsonify(error='Tanggal atau jam tidak valid.'), 400
    db().execute('INSERT INTO schedules(course_id,starts_at,ends_at) VALUES (?,?,?)',
                 (course['id'], start.isoformat(), (start + timedelta(minutes=100)).isoformat()))
    db().commit()
    return redirect(url_for('index'))


@app.get('/attendance/qr/<int:schedule_id>')
@login_required('dosen')
def attendance_qr(schedule_id):
    schedule = db().execute('''SELECT s.* FROM schedules s JOIN courses c ON c.id=s.course_id
                              WHERE s.id=? AND c.lecturer=?''', (schedule_id, g.user['id'])).fetchone()
    if not schedule:
        return jsonify(error='Jadwal tidak ditemukan.'), 404
    current = now()
    start, end = datetime.fromisoformat(schedule['starts_at']), datetime.fromisoformat(schedule['ends_at'])
    if not start <= current < min(end, start + timedelta(minutes=30)):
        return jsonify(error='QR hanya dapat dibuat pada 30 menit awal kuliah.'), 400
    expires = min(current + timedelta(minutes=15), end, start + timedelta(minutes=30))
    jti = secrets.token_hex(16)
    payload = dict(schedule_id=schedule_id, iat=current, exp=expires, jti=jti, purpose='attendance')
    token = jwt.encode(payload, app.secret_key, algorithm='HS256')
    db().execute('UPDATE schedules SET qr_jti=? WHERE id=?', (jti, schedule_id))
    db().commit()
    qr = io.BytesIO()
    qrcode.make(token).save(qr, format='PNG')
    qr.seek(0)
    response = send_file(qr, mimetype='image/png')
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-QR-Expires-At'] = expires.isoformat()
    return response


@app.post('/attendance/scan')
@login_required('mahasiswa')
def attendance_scan():
    # Maksimal 5 percobaan per 60 detik per akun, termasuk scan yang gagal.
    attempts = scan_attempts[g.user['id']]
    tick = time.monotonic()
    while attempts and tick - attempts[0] >= 60:
        attempts.popleft()
    if len(attempts) >= 5:
        return jsonify(error='Terlalu banyak scan. Tunggu 60 detik.'), 429
    attempts.append(tick)
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('token'), str):
        return jsonify(error='Token QR wajib diisi.'), 400
    # NIM harus sesuai akun login, sehingga mahasiswa tidak dapat menitipkan NIM lain.
    nim = g.user['id']
    if data.get('nim', nim) != nim:
        return jsonify(error='NIM tidak sesuai akun login.'), 403
    try:
        payload = jwt.decode(data['token'], app.secret_key, algorithms=['HS256'],
                             options={'require': ['exp', 'iat', 'jti', 'schedule_id', 'purpose']})
    except jwt.ExpiredSignatureError:
        return jsonify(error='QR kedaluwarsa. Minta dosen memperbarui QR.'), 400
    except jwt.InvalidTokenError:
        return jsonify(error='Token QR tidak valid.'), 400
    if payload['purpose'] != 'attendance' or type(payload['schedule_id']) is not int:
        return jsonify(error='Isi token tidak valid.'), 400
    schedule = db().execute('SELECT * FROM schedules WHERE id=?', (payload['schedule_id'],)).fetchone()
    if not schedule or schedule['qr_jti'] != payload['jti']:
        return jsonify(error='QR tidak aktif atau sudah diganti.'), 400
    current = now()
    start, end = datetime.fromisoformat(schedule['starts_at']), datetime.fromisoformat(schedule['ends_at'])
    if not start <= current < min(end, start + timedelta(minutes=30)):
        return jsonify(error='Di luar jadwal atau batas presensi 30 menit.'), 400
    enrollment = db().execute('SELECT 1 FROM enrollments WHERE course_id=? AND nim=?',
                              (schedule['course_id'], nim)).fetchone()
    if not enrollment:
        return jsonify(error='Mahasiswa tidak terdaftar pada mata kuliah ini.'), 403
    status = 'hadir' if current < start + timedelta(minutes=15) else 'terlambat'
    try:
        db().execute('INSERT INTO attendance(schedule_id,nim,timestamp,status) VALUES (?,?,?,?)',
                     (schedule['id'], nim, current.isoformat(), status))
        db().commit()
    except sqlite3.IntegrityError:
        db().rollback()
        return jsonify(error='Presensi pada pertemuan ini sudah tercatat.'), 409
    return jsonify(success=True, status=status, message='Presensi berhasil disimpan.', timestamp=current.isoformat())


def report_rows():
    # Pertemuan berjalan belum dimasukkan agar mahasiswa tidak langsung dianggap absen.
    rows = db().execute('''SELECT c.id course_id,c.name course,u.id nim,u.name,s.id schedule_id,
        s.starts_at,s.ends_at,a.status FROM enrollments e
        JOIN courses c ON c.id=e.course_id JOIN users u ON u.id=e.nim
        LEFT JOIN schedules s ON s.course_id=c.id
        LEFT JOIN attendance a ON a.schedule_id=s.id AND a.nim=u.id
        WHERE (c.lecturer=? OR u.id=?) ORDER BY c.id,u.id,s.starts_at''',
                        (g.user['id'], g.user['id'])).fetchall()
    grouped = {}
    for row in rows:
        key = (row['course_id'], row['nim'])
        r = grouped.setdefault(key, dict(course_id=row['course_id'], course=row['course'], nim=row['nim'],
            name=row['name'], total=0, hadir=0, terlambat=0, absen=0, missed=[]))
        if row['schedule_id'] and datetime.fromisoformat(row['ends_at']) <= now():
            r['total'] += 1
            if row['status']:
                r[row['status']] += 1
            else:
                r['absen'] += 1
                r['missed'].append(row['starts_at'])
    for r in grouped.values():
        r['percentage'] = round((r['hadir'] + r['terlambat']) / r['total'] * 100, 2) if r['total'] else None
        r['warning'] = r['total'] > 0 and (r['hadir'] + r['terlambat']) * 4 < r['total'] * 3
    return list(grouped.values())


@app.get('/attendance/report')
@login_required()
def attendance_report():
    return jsonify(reports=report_rows())


@app.get('/attendance/export')
@login_required('dosen')
def export_excel():
    book = Workbook()
    sheet = book.active
    sheet.title = 'Ringkasan'
    sheet.append(['Mata kuliah', 'NIM', 'Nama', 'Pertemuan selesai', 'Hadir', 'Terlambat', 'Absen', 'Persentase', 'Peringatan'])
    for r in report_rows():
        sheet.append([r['course'], r['nim'], r['name'], r['total'], r['hadir'], r['terlambat'], r['absen'],
                      r['percentage'], 'Di bawah 75%' if r['warning'] else ''])
    detail = book.create_sheet('Detail presensi')
    detail.append(['Mata kuliah', 'Pertemuan', 'NIM', 'Nama', 'Waktu scan WIB', 'Status'])
    for row in db().execute('''SELECT c.name,s.id,a.nim,u.name,a.timestamp,a.status FROM attendance a
        JOIN schedules s ON s.id=a.schedule_id JOIN courses c ON c.id=s.course_id
        JOIN users u ON u.id=a.nim WHERE c.lecturer=? ORDER BY s.id,a.nim''', (g.user['id'],)):
        detail.append(list(row))
    for ws in book:
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        for column in ws.columns:
            ws.column_dimensions[column[0].column_letter].width = min(45, max(len(str(c.value or '')) for c in column) + 3)
    output = io.BytesIO()
    book.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name='laporan_presensi.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.get('/insights')
@login_required('dosen')
def insights():
    # Analisis aturan sederhana, belum memakai model machine learning atau API AI.
    warnings, patterns, actions = [], [], []
    weekdays = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
    for r in report_rows():
        if r['warning']:
            warnings.append(dict(nim=r['nim'], name=r['name'], course=r['course'], percentage=r['percentage']))
            actions.append(f"Hubungi {r['name']} untuk membahas kehadiran di {r['course']}.")
        counts = Counter(datetime.fromisoformat(t).weekday() for t in r['missed'])
        for day, count in counts.items():
            if count >= 2:
                patterns.append(f"{r['name']} absen {count} kali pada hari {weekdays[day]} di {r['course']}.")
    return jsonify(method='rule_based', at_risk_count=len({r['nim'] for r in warnings}),
                   warnings=warnings, insights=patterns, actions=actions)


if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(host='127.0.0.1', port=5000, debug=False)
