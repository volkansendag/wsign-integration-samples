# W.Sign Entegrasyon Örnekleri

W.Sign ile e-imza entegrasyonunun **ne kadar basit** olduğunu gösteren resmi
örnek depo. Aynı senaryo üç dilde (.NET, PHP, Python) birebir uygulanır:
3D-Secure ödeme akışına benzeyen **redirect-session** modeli.

> **5 dakikada özet:** Oturum açarsınız, kullanıcıyı W.Sign'a yönlendirirsiniz,
> imza bitince W.Sign size HMAC imzalı bir callback gönderir. Entegratör
> tarafında yazmanız gereken tek şey budur — birkaç HTTP çağrısı.

## Akış (3D-Secure gibi)

```
 ┌────────────┐                                              ┌──────────────┐
 │ Kullanıcı  │                                              │  W.Sign      │
 │ (tarayıcı) │                                              │  Server      │
 └─────┬──────┘                                              └──────┬───────┘
       │ 1. Belge formu (GET /)                                     │
       ▼                                                            │
 ┌─────────────────────┐  2. POST /v1/redirect-sign/sessions       │
 │  Entegratör Backend │ ─────────────────────────────────────────►│
 │  (bu örnek depo)    │  X-WSign-Api-Key + {document, callbackUrl, │
 │                     │   successRedirectUrl, nonce}               │
 │                     │◄───────────────────────────────────────── │
 │                     │  201 {sessionId, redirectUrl}              │
 └─────────┬───────────┘                                            │
           │ 3. 302 → redirectUrl (sign.wsoft.tr/rs/{id})           │
 ┌─────────▼──────────┐                                             │
 │ Kullanıcı W.Sign'da│  (Desktop'ta sertifika seçer + PIN girer;   │
 │ belgeyi imzalar    │   belge kullanıcının PC'sine inmez)         │
 └─────────┬──────────┘                                             │
           │                                  4. POST callbackUrl   │
           │                          X-WSign-Signature: sha256=... │
 ┌─────────▼───────────┐◄──────────────────────────────────────────┤
 │  Entegratör Backend │  {sessionId, status, nonce,                │
 │  • HMAC doğrula     │   signedContentBase64, ...}                │
 │  • nonce doğrula    │                                            │
 │  • imzalı belgeyi   │  5. 302 → successRedirectUrl               │
 │    sakla            │ ◄──────────────────────────────────────────
 └─────────┬───────────┘                                            │
           │ 5. GET /imza/tamam → "İmza tamamlandı" + imzalı belge  │
           ▼                                                        │
```

Daha ayrıntılı diyagram: [`docs/sequence.md`](docs/sequence.md).

## Bu depo neyi içerir, neyi içermez

| İçerir | İçermez |
|---|---|
| İstemci/entegratör tarafı kod (.NET, PHP, Python) | W.Sign çekirdeği (CMS, kripto) |
| REST çağrıları + callback HMAC doğrulaması | W.Sign Server / oturum durum makinesi |
| Çalışan örnek web uygulaması (3 dil) | PKCS#11 / sertifika / Desktop kodu |

Bu kasıtlıdır: entegrasyon yalnızca **REST + HMAC** üzerinden yapılır; W.Sign'ın
içselleri kapalıdır. Entegratörün e-imza kütüphanesi kurmasına, sertifika veya
token yönetmesine gerek yoktur.

## Senaryo

Kurgusal **"Örnek Belediye"** bir belge metni üretir ve W.Sign ile imzalatır.
Üç örnek de tıpatıp aynı 5 adımı uygular:

1. Belge oluşturma formu (`GET /`).
2. "İmzala" → `POST /v1/redirect-sign/sessions` → `{sessionId, redirectUrl}`.
3. Kullanıcıyı `redirectUrl`'e 302 yönlendir.
4. `POST /wsign/callback` → **HMAC + nonce doğrula** → imzalı belgeyi sakla.
5. `GET /imza/tamam` → sonuç sayfası.

## Hızlı başlangıç

```bash
# 1) Yapılandırmayı hazırlayın
cp .env.example .env
#    .env içindeki değerleri doldurun (aşağıya bakın).

# 2) İstediğiniz dili çalıştırın
```

| Dil | Komut | Adres |
|---|---|---|
| .NET | `cd dotnet && dotnet run` | http://localhost:5000 |
| PHP | `cd php && php -S localhost:8080 index.php` | http://localhost:8080 |
| Python | `cd python && pip install -r requirements.txt && uvicorn main:app --port 5000` | http://localhost:5000 |

Her dilin kendi README'sinde ayrıntı vardır: [dotnet](dotnet/README.md) ·
[php](php/README.md) · [python](python/README.md).

## Yapılandırma (.env)

| Değişken | Açıklama | Varsayılan |
|---|---|---|
| `WSIGN_API_BASE` | Redirect-Session REST API kök adresi | `https://api.sign.wsoft.tr` |
| `WSIGN_API_KEY` | Entegratör API anahtarı (`X-WSign-Api-Key`) | `demo-...` (placeholder) |
| `WSIGN_CALLBACK_SECRET` | Callback HMAC secret'ı | `demo-...` (placeholder) |
| `PUBLIC_BASE_URL` | Bu örneğin dışarıdan erişilebilir kök adresi | `http://localhost:5000` |

> **Hosted demo:** Kurulumsuz denemek için bir **demo entegratör anahtarı yakında**
> yayınlanacaktır (`api.sign.wsoft.tr` üzerinde sandbox tenant). O zamana kadar
> kendi W.Sign Server adresinizi ve anahtarınızı `.env` ile verin.

> **callback erişimi:** W.Sign callback POST'unu `PUBLIC_BASE_URL` adresine
> gönderir. Yerel geliştirmede bu adres internetten erişilemez; `cloudflared`
> veya `ngrok` gibi bir tünel açıp tünel adresini `PUBLIC_BASE_URL` verin.

## Güvenlik — callback'i mutlaka doğrulayın

Callback endpoint'i internete açıktır. Her örnek iki bağımsız kontrol yapar:

1. **HMAC-SHA256** — `X-WSign-Signature: sha256=<hex>` başlığını **ham gövde**
   üzerinde, paylaşılan secret ile sabit-zamanlı karşılaştırır.
2. **nonce** — oturum açarken üretilen rastgele değerin callback'te aynen
   dönmesini doğrular (replay/CSRF koruması).

Her dilde doğrulama snippet'i: [`docs/hmac-verify.md`](docs/hmac-verify.md).
Tam REST sözleşmesi: [`docs/rest-contract.md`](docs/rest-contract.md).

## Lisans

Örnek kod [MIT](LICENSE) ile sunulur. W.Sign ürün ve sunucusu bu lisansın
kapsamı dışındadır.
