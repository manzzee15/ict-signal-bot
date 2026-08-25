# ICT Signal Scanner — Versi Gratis (Tanpa TradingView)

Versi ini **tidak butuh TradingView sama sekali**. Data candle forex diambil
langsung dari API gratis, semua logika ICT (Sweep, FVG, Momentum, Zone,
rating A+/A/B/C) dihitung di Python, lalu hasilnya dikirim ke Telegram.

Karena tidak ada webhook yang harus "menerima" data dari luar, **tidak perlu
VPS, domain, atau HTTPS**. Script ini cukup dijalankan berkala (tiap 15
menit, misalnya) — bisa lewat GitHub Actions yang gratis.

## Kenapa lebih murah dari versi TradingView

| Kebutuhan versi TradingView | Di versi ini |
|---|---|
| Paket TradingView berbayar (webhook) | ❌ Tidak perlu |
| VPS 24/7 | ❌ Tidak perlu (opsional kalau mau) |
| Domain + HTTPS (nginx, certbot) | ❌ Tidak perlu |
| Data harga | Twelve Data (**gratis**, 800 request/hari) |
| Menjalankan scanner | GitHub Actions (**gratis** untuk repo publik; ada kuota untuk repo privat) |
| Telegram | Gratis seperti biasa |

## 1. Daftar API key data gratis (Twelve Data)

1. Buka https://twelvedata.com → Sign Up (gratis, cukup email).
2. Di dashboard, copy **API Key**.
3. Free tier: **800 request/hari, 8 request/menit** — cukup untuk beberapa
   pair dipantau tiap 15 menit (3 pair × 96 run/hari = 288 request/hari).

> Kalau butuh lebih banyak pair/frekuensi lebih cepat, alternatif lain yang
> juga punya free tier: Finnhub, atau akun demo OANDA (gratis, data forex
> asli dari broker, limit lebih longgar tapi proses daftar sedikit lebih ribet).

## 2. Buat bot Telegram (sama seperti sebelumnya)

1. Chat `@BotFather` → `/newbot` → simpan token.
2. Tambahkan bot ke channel/grup tujuan, jadikan admin kalau channel.
3. Ambil `chat_id` lewat `@userinfobot` atau endpoint `getUpdates`.

## 3. Jalankan — Opsi A: GitHub Actions (paling praktis, gratis)

1. Push folder ini ke repository GitHub (boleh publik atau privat).
2. Buka repo → **Settings → Secrets and variables → Actions**:
   - Tab **Secrets**, tambahkan:
     - `TWELVE_DATA_API_KEY`
     - `TELEGRAM_BOT_TOKEN`
     - `TELEGRAM_CHAT_ID`
   - Tab **Variables** (opsional, kalau mau override default):
     - `PAIRS` (misal `EUR/USD,GBP/USD`)
     - `TIMEFRAME` (misal `15min`)
     - `MIN_GRADE` (misal `A`)
3. Buka tab **Actions**, aktifkan workflow kalau diminta.
4. Workflow `ict-scan.yml` otomatis jalan tiap 15 menit sesuai jadwal cron.
   Bisa juga dites manual: tab Actions → pilih workflow → **Run workflow**.

**Catatan penting soal kuota GitHub Actions:**
- Repo **publik** → menit Actions gratis **tanpa batas**.
- Repo **privat** → gratis 2.000 menit/bulan. Kalau workflow jalan tiap 15
  menit (≈2.880 kali/bulan) dan tiap run makan ~1 menit, itu bisa mepet/lewat
  kuota gratis. Solusi: pakai repo publik (kode tidak masalah dilihat orang,
  karena semua kredensial ada di Secrets yang tetap rahasia), atau perlambat
  jadwal jadi tiap 30–60 menit.
- Timing cron GitHub Actions **tidak 100% presisi** (bisa delay beberapa
  menit saat sedang ramai) — cukup aman untuk timeframe 15m ke atas, kurang
  cocok untuk scalping M1.

## 3. Jalankan — Opsi B: VPS/komputer sendiri (kalau mau realtime lebih presisi)

Kalau kamu tetap punya VPS (termasuk yang gratis selamanya seperti **Oracle
Cloud Always Free**), bisa jalankan via cron biasa, tanpa perlu nginx/domain
sama sekali (karena tidak ada webhook masuk):

```bash
cd free-python-version
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # isi semua API key
python ict_scanner.py   # test manual sekali dulu
```

Kalau berhasil dan pesan masuk ke Telegram, jadwalkan lewat crontab:

```bash
crontab -e
```
```
*/15 * * * * cd /path/ke/free-python-version && /path/ke/venv/bin/python ict_scanner.py >> scanner.log 2>&1
```

## Tentang logika rating (sama seperti versi TradingView)

5 kriteria dengan bobot sama (1 poin masing-masing, maks 5):

1. **Sweep + Delivery** — ada liquidity sweep dalam `SWEEP_LOOKBACK` candle sebelum FVG terbentuk.
2. **Momentum** — pergerakan net 3 candle > ATR(14) × `DISP_MULTIPLIER`.
3. **Target** — ada swing high/low yang belum "dimakan" di arah trade.
4. **FVG Singular** — tidak ada FVG searah lain dalam `FVG_SINGULAR_GAP` candle terakhir.
5. **Premium/Discount** — long harus di discount (di bawah equilibrium), short di premium.

Grade: 5/5 = A+, 4/5 = A, 3/5 = B, 2/5 = C, 0-1/5 = D.
`MIN_GRADE` di `.env` menentukan ambang minimum yang dikirim ke Telegram.

**Catatan:** versi ini belum menghitung SMT Divergence (butuh data pair
pembanding + tambahan request API) untuk menjaga kesederhanaan dan hemat
kuota API gratis. Bisa ditambahkan kalau kamu mau.

## Disclaimer

Sinyal murni hasil deteksi pola teknikal otomatis — **bukan rekomendasi
finansial**. Selalu lakukan riset sendiri dan gunakan manajemen risiko.
