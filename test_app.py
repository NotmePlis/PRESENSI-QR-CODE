"""Pengujian aturan tugas dengan database sementara."""
import io
import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch
import jwt
from openpyxl import load_workbook
import app as module

class PresensiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        module.app.config.update(TESTING=True, DATABASE=os.path.join(self.tmp.name, 'test.db'))
        module.scan_attempts.clear()
        self.client = module.app.test_client()
        with module.app.app_context(): module.init_db()
        self.login('23001')

    def tearDown(self): self.tmp.cleanup()

    def login(self, uid):
        with self.client.session_transaction() as s: s.update(uid=uid, csrf='test-csrf')

    def scan(self, token, nim='23001'):
        return self.client.post('/attendance/scan', json={'token':token,'nim':nim}, headers={'X-CSRF-Token':'test-csrf'})

    def token(self, **overrides):
        current = module.now()
        payload = dict(schedule_id=5, iat=current, exp=current+timedelta(minutes=15), jti='test-jti', purpose='attendance')
        payload.update(overrides)
        with module.app.app_context():
            module.db().execute('UPDATE schedules SET qr_jti=? WHERE id=5', ('test-jti',))
            module.db().commit()
        return jwt.encode(payload, module.app.secret_key, algorithm='HS256')

    def test_hadir_dan_duplikat(self):
        token=self.token()
        self.assertEqual(self.scan(token).json['status'],'hadir')
        self.assertEqual(self.scan(token).status_code,409)

    def test_qr_kedaluwarsa(self):
        token=self.token(iat=module.now()-timedelta(minutes=20), exp=module.now()-timedelta(minutes=5))
        response=self.scan(token)
        self.assertEqual(response.status_code,400)
        self.assertIn('kedaluwarsa',response.json['error'])

    def test_tanda_tangan_palsu(self):
        payload=jwt.decode(self.token(),options={'verify_signature':False})
        forged=jwt.encode(payload,'kunci-palsu-yang-panjangnya-minimal-32-karakter',algorithm='HS256')
        self.assertEqual(self.scan(forged).status_code,400)

    def test_kelas_lain(self):
        self.login('23003')
        self.assertEqual(self.scan(self.token(),'23003').status_code,403)

    def test_titip_nim(self): self.assertEqual(self.scan(self.token(),'23002').status_code,403)

    def test_qr_diganti(self): self.assertEqual(self.scan(self.token(jti='lama')).status_code,400)

    def test_terlambat_dan_batas_30_menit(self):
        token=self.token()
        current=module.now()
        with module.app.app_context():
            module.db().execute('UPDATE schedules SET starts_at=? WHERE id=5',((current-timedelta(minutes=20)).isoformat(),))
            module.db().commit()
        self.assertEqual(self.scan(token).json['status'],'terlambat')
        self.login('23002')
        with patch.object(module,'now',return_value=current+timedelta(minutes=11)):
            self.assertEqual(self.scan(token,'23002').status_code,400)

    def test_sebelum_kuliah(self):
        token=self.token()
        with patch.object(module,'now',return_value=module.now()-timedelta(hours=1)):
            self.assertEqual(self.scan(token).status_code,400)

    def test_rate_limit(self):
        for _ in range(5): self.assertEqual(self.scan('salah').status_code,400)
        self.assertEqual(self.scan('salah').status_code,429)

    def test_rekap_dan_insights(self):
        self.login('dosen')
        rows=self.client.get('/attendance/report').json['reports']
        adi=next(r for r in rows if r['nim']=='23001')
        citra=next(r for r in rows if r['nim']=='23002')
        self.assertEqual((adi['total'],adi['percentage'],adi['warning']),(4,50.0,True))
        self.assertEqual((citra['percentage'],citra['warning']),(75.0,False))
        data=self.client.get('/insights').json
        self.assertEqual(data['at_risk_count'],1)
        self.assertTrue(data['insights'])

    def test_export_excel(self):
        self.login('dosen')
        response=self.client.get('/attendance/export')
        self.assertEqual(response.status_code,200)
        book=load_workbook(io.BytesIO(response.data))
        self.assertEqual(book.sheetnames,['Ringkasan','Detail presensi'])
        self.assertEqual(book['Detail presensi'].max_row,6)

    def test_hak_akses_csrf_dan_halaman(self):
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(self.client.get('/attendance/qr/5').status_code,403)
        self.assertEqual(self.client.get('/attendance/export').status_code,403)
        self.assertEqual(self.client.post('/attendance/scan',json={'token':'x'}).status_code,403)
        self.login('dosen')
        self.assertEqual(self.client.get('/').status_code,200)
        response=self.client.get('/attendance/qr/5')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.data.startswith(b'\x89PNG'))
        self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_tambah_pertemuan(self):
        self.login('dosen')
        response=self.client.post('/schedules',data={'csrf':'test-csrf','course_id':1,'starts_at':module.now().strftime('%Y-%m-%dT%H:%M')})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.client.get('/attendance/qr/6').status_code,200)

    def test_login_password(self):
        self.client.post('/logout',data={'csrf':'test-csrf'})
        with self.client.session_transaction() as s: csrf=s.setdefault('csrf','login-csrf')
        response=self.client.post('/login',data={'csrf':csrf,'uid':'dosen','password':'belajar123'})
        self.assertEqual(response.status_code,302)
        with self.client.session_transaction() as s: self.assertEqual(s['uid'],'dosen')

if __name__=='__main__': unittest.main(verbosity=2)
