# Python örneği — W.Sign entegrasyonu (FastAPI)

Bütün entegrasyon tek dosyada: [`main.py`](main.py).

## Çalıştırma

```bash
# 1) Kök dizindeki .env.example'ı .env olarak kopyalayıp doldurun.
#    (.env git'e GİTMEZ — .gitignore'da. main.py kök .env'i otomatik yükler.)
cp .env.example .env

cd python
python -m venv .venv
# Windows:  .venv\Scripts\activate     |  Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 5000
```

Tarayıcıdan `http://localhost:5000` adresini açın → belge metnini girin →
"İmzala" → W.Sign imzalama sayfasına yönlendirilirsiniz.

## Gereksinimler

- Python 3.10+.
- **Yerel test (redirect + pull): tünel GEREKMEZ.** Sonuç, backend'in W.Sign'a
  yaptığı outbound GET ile çekilir. `localhost` host'unu entegratör kaydınızın
  redirect allowlist'ine ekleyin.
- **callback opsiyoneldir** (üretimde güvenlik ağı). Örnek, `callbackUrl`'i yalnızca
  `PUBLIC_BASE_URL` public bir host iken **ve** `WSIGN_RETURN_MODE` ≠ `post` iken
  gönderir; loopback (`localhost`/`127.x`/`::1`) veya `post` modunda hiç göndermez
  (callback allowlist gerekmez). Onu da denemek isterseniz `PUBLIC_BASE_URL`'i
  W.Sign'dan erişilebilir bir adrese ayarlayın — `cloudflared` / `ngrok` tüneli.

## Akış

`GET /` form → `POST /sign` (oturum aç + 302) → kullanıcı W.Sign'da imzalar →
kullanıcı `GET /imza/tamam`'e döner → **pull:** `GET /sessions/{id}/result`
(`X-WSign-Api-Key`, nonce doğrula, imzalı belgeyi sakla) → sonuç sayfası.
Opsiyonel: `POST /wsign/callback` (HMAC + nonce doğrula, aynı idempotent yol).

## Notlar

- Oturum durumu in-memory bir sözlükte tutulur; üretimde veritabanı kullanın.
  Pull ve callback aynı kaydı idempotent günceller.
- `main.py` yapılandırmayı ortam değişkenlerinden okur ve depo kökündeki `.env`
  dosyasını bağımlılıksız basit bir ayrıştırıcıyla otomatik yükler. Öncelik:
  **process env > `.env` > placeholder fallback** (kabukta verdiğiniz değişken
  `.env`'i ezer).
