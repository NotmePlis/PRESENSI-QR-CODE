# Tugas Minggu 12 Modul Presensi QR

Aplikasi latihan menggunakan Python, Flask, SQLite, JWT, dan QR code. Ada halaman dosen dan mahasiswa. Tidak perlu membuat database secara manual.

## Cara menjalankan di Windows

1. Instal Python 3.10 atau lebih baru. Saat instalasi, centang **Add Python to PATH**.
2. Ekstrak ZIP, lalu buka folder `presensi_qr` di VS Code.
3. Buka Terminal, kemudian jalankan:

```text
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

4. Buka `http://127.0.0.1:5000` di browser. Terminal harus tetap menyala.
5. Untuk menghentikan aplikasi, tekan Ctrl+C pada terminal.
6. Untuk menjalankan lagi, cukup `.venv\Scripts\python app.py`.

Linux atau macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

## Akun contoh

| ID login | Nama | Peran | Kelas |
| --- | --- | --- | --- |
| dosen | Pak Andi | Dosen | Mengajar PBO dan Basis Data |
| 23001 | Adi | Mahasiswa | PBO |
| 23002 | Citra | Mahasiswa | PBO |
| 23003 | Budi | Mahasiswa | Basis Data |

Password seluruh akun contoh: **belajar123**. Nama dan NIM mahasiswa adalah data contoh.

## Urutan demonstrasi paling mudah

1. Login sebagai `dosen` melalui browser biasa.
2. Pada **Tambah pertemuan**, pilih PBO dan biarkan waktu mulai sesuai waktu sekarang, lalu simpan. Waktu memakai WIB. Durasi kuliah 100 menit.
3. Pilih pertemuan paling baru di bagian **QR pertemuan**, lalu klik **Buat atau perbarui QR**.
4. Simpan gambar QR dengan klik kanan pada gambar → Save image as.
5. Buka jendela Incognito/InPrivate agar sesi login terpisah. Login sebagai `23001`.
6. Unggah gambar QR tadi. Seharusnya status **hadir** tersimpan.
7. Unggah lagi untuk membuktikan scan ganda ditolak.
8. Login sebagai `23003` dan unggah QR PBO. Seharusnya ditolak karena Budi tidak terdaftar di PBO.
9. Kembali ke akun dosen, klik **Unduh Excel** dan **Lihat hasil analisis**.
10. Untuk mencoba terlambat tanpa menunggu, buat pertemuan baru dengan waktu mulai **20 menit sebelum waktu sekarang**, lalu buat QR baru dan scan sebagai mahasiswa terdaftar.

Jangan memperbarui QR sebelum semua mahasiswa yang memakainya selesai scan, karena QR lama langsung tidak aktif. Mahasiswa tetap boleh menggunakan QR yang sama secara bergantian selama aktif; tiap NIM hanya boleh tercatat sekali per pertemuan.

### Kamera

Kamera memakai pemindai jsQR yang sudah disertakan, sehingga tidak membutuhkan CDN saat aplikasi berjalan. Izinkan akses kamera pada browser. Kamera browser biasanya memerlukan localhost atau HTTPS. Aplikasi secara bawaan hanya diakses dari laptop yang menjalankannya. Untuk demo di satu laptop, gunakan fitur **unggah gambar QR**. Menjalankan server di laptop tidak otomatis membuatnya dapat diakses dari HP.

## Aturan waktu

- QR berlaku maksimal 15 menit sejak dibuat.
- QR juga berhenti berlaku pada akhir jendela presensi, yaitu menit ke-30 sejak kuliah dimulai.
- Hadir: dari waktu mulai sampai sebelum menit ke-15.
- Terlambat: mulai menit ke-15 sampai sebelum menit ke-30.
- Pada menit ke-30 atau setelah kuliah selesai: ditolak.
- Dosen dapat memperbarui QR pada jendela presensi. Contoh kuliah mulai 08.00, QR baru dibuat 08.20: QR tersebut hanya berlaku sampai 08.30.

## Laporan dan analisis

Persentase = (jumlah hadir + jumlah terlambat) / jumlah pertemuan **yang telah selesai** × 100%.

Pertemuan berjalan dan pertemuan mendatang tidak masuk pembagi. Tidak ada pertemuan selesai ditampilkan sebagai **Belum ada**, bukan 0%. Nilai kurang dari 75% diberi peringatan; tepat 75% tidak diberi peringatan. Angka dihitung per mata kuliah.

Data awal PBO: 4 pertemuan selesai. Adi hadir 2 kali = 50%; Citra hadir 3 kali = 75%. Ada satu jadwal contoh hari ini. Setelah jadwal itu selesai, jumlah pertemuan dan persentase akan ikut berubah.

Bagian **AI Attendance Insights** diimplementasikan sebagai analisis berbasis aturan sederhana, belum memakai model AI terlatih atau API AI. Sistem mengenali mahasiswa yang absen minimal dua kali pada hari yang sama dalam suatu mata kuliah, memberi peringatan di bawah 75%, dan menyarankan dosen menghubungi mahasiswa. Hasil berupa JSON dengan `insights` dan `actions` pada `/insights`. Tidak ada data yang dikirim ke layanan AI luar.

## Isi kode

- `app.py`: database, login, pembuatan QR, validasi scan, rekap, Excel, dan analisis.
- `templates/login.html`: halaman login.
- `templates/index.html`: halaman dosen dan mahasiswa, kamera, unggahan QR.
- `static/jsQR.js`: pemindai QR di browser beserta berkas lisensi.
- `requirements.txt`: library Python yang diperlukan.
- `test_app.py`: pengujian otomatis.
- `Laporan_Presensi_QR.docx`: laporan penjelasan tugas.

Database dan kunci aplikasi dibuat otomatis dalam folder `instance` saat aplikasi dijalankan. Password disimpan dalam bentuk hash. Jangan menghapus database jika ingin mempertahankan data presensi.

## Pengujian

```text
.venv\Scripts\python -m unittest -v
```

Ada 14 pengujian yang mencakup hadir, terlambat, scan ganda, kedaluwarsa, tanda tangan palsu, QR lama, waktu di luar jadwal, kelas lain, NIM lain, pembatasan percobaan, laporan, ekspor Excel, hak akses, CSRF, login, dan penambahan pertemuan. Beberapa kondisi diperiksa dalam satu pengujian.

## Batasan tugas

- Validasi lokasi belum diterapkan karena pada modul bersifat opsional. QR bisa dibagikan selama masih aktif; tanpa lokasi, sistem belum membuktikan mahasiswa benar-benar berada di kelas.
- Belum ada menu kelola mahasiswa, pendaftaran mata kuliah, atau kalender akademik lengkap. Data awal dibuat untuk demonstrasi.
- Keterlambatan tetap dihitung hadir pada persentase, tetapi jumlahnya dipisahkan di laporan.
- Pembatasan 5 scan per akun per 60 detik disimpan di memori satu proses, dan hilang jika server dimulai ulang.
- Aplikasi menggunakan server pengembangan Flask untuk tugas lokal. Akun demo dan konfigurasi ini perlu disesuaikan sebelum dipakai sebagai layanan kampus.
