# PHP örneği — W.Sign entegrasyonu (saf PHP, framework yok)

Bütün entegrasyon tek dosyada: [`index.php`](index.php). Yapılandırma
[`config.php`](config.php) ile ortam değişkenlerinden okunur.

## Çalıştırma

```bash
# 1) Kök dizindeki .env.example'ı .env olarak kopyalayıp doldurun.
#    (.env git'e GİTMEZ — .gitignore'da. config.php kök .env'i otomatik yükler.)
cp .env.example .env

cd php
php -S localhost:8080 index.php   # index.php "router script" olarak çalışır
```

Öncelik: **process env > `.env` > placeholder fallback** — kabukta `putenv`/
`getenv` ile verdiğiniz değişken `.env`'i ezer.

Tarayıcıdan `http://localhost:8080` adresini açın → belge metnini girin →
"İmzala" → W.Sign imzalama sayfasına yönlendirilirsiniz.

## Gereksinimler

- PHP 8.1+ ve `curl`, `json` eklentileri. (`composer` opsiyoneldir; harici
  bağımlılık yoktur.)
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

- Oturum durumu basit dosya deposunda (`php/storage/`, gitignore'lu) tutulur;
  üretimde veritabanı kullanın. Pull ve callback aynı kaydı idempotent günceller.
- `php -S` dahili sunucusu tüm istekleri `index.php`'ye yönlendirir (front
  controller); ek yapılandırma gerekmez.
