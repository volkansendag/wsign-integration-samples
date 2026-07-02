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

## İmza tipi seçimi

Formdaki "İmza tipi" açılır listesi `CAdES-BES` / `CAdES-T` / `CAdES-ESXLong` /
`XAdES-BES` / `XAdES-T` seçtirir ve create isteğine `signatureProfile` olarak geçer
(varsayılan `WSIGN_SIGNATURE_PROFILE`, vsy `CAdES-BES`). `CAdES-ESXLong` uzun
dönemli imzadır (zaman damgası + zincir + OCSP/CRL gömülü; EBYS/arşiv için).
Damgalı tipler (`-T` / `ESXLong`) için entegratörde
**Kamu SM TSA** tanımlı olmalı; değilse server `400` (`TSA_NOT_CONFIGURED`) döner
ve örnek bunu açıklar. İmzalı çıktının uzantısı profile göre değişir (CAdES →
`.p7s`, XAdES → `.xml`). Ayrıntı:
[`docs/signature-profiles.md`](../docs/signature-profiles.md).

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
