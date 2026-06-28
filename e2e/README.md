# W.Sign redirect-session — E2E test rehberi

Redirect-session akışı iki seviyede test edilir.

## 1) Otomatik sunucu-akışı testi (`smoke-e2e.ps1`) — token GEREKMEZ

Sunucu protokolünün tamamını doğrular: `create → info → prepare → (yerel imza) → complete → result (pull) → callback`.
İmzayı, private key'ini scriptin kendisinin tuttuğu **geçici self-signed sertifikayla** üretir; böylece gerçek
USB token / Desktop / tarayıcı olmadan `/prepare`'in döndürdüğü `DataToSign` imzalanıp `/complete` sürülür.
`result (pull)` adımı entegratörün birincil akışını (sonucu authed GET ile çekme) **tünelsiz** doğrular —
`signedContentBase64` dolu mu, `nonce` eşleşiyor mu kontrol eder.

**Kapsar:** API sözleşmesi, auth, deferred prepare, CMS montajı, pull (result) + HMAC callback teslimi.
**Kapsamaz:** nitelikli (QES) USB token, Desktop `wsign://` UI, tarayıcı redirect — bunlar §2'de.

**Ön koşul:** demo tenant host'ta enable edilmiş + callback host'u entegratör allowlist'inde.
Public callback alıcısı olarak [webhook.site](https://webhook.site) pratik.

```powershell
$env:WSIGN_API_BASE     = "https://api.sign.wsoft.tr"
$env:WSIGN_API_KEY      = "wsign-demo-key"
$env:WSIGN_CALLBACK_URL = "https://webhook.site/<uuid>"   # allowlist'te olmalı
$env:WSIGN_RETURN_URL   = "https://webhook.site/<uuid>"
./smoke-e2e.ps1
```
Başarılıysa: `complete → completed` + webhook.site'da `X-WSign-Signature` header'lı, `nonce` eşleşen,
`signedContentBase64` dolu callback görünür.

## 2) Manuel nitelikli-kart testi (gerçek QES) — insan gerektirir

Otomatik test edilemez: fiziksel USB token + PIN + W.Sign Desktop kurulumu insan etkileşimi ister.

**Ön koşul:**
- W.Sign Desktop'ın `wsign://session/{id}` handler'lı sürümü kurulu (Faz 0c — yeni installer build gerekir).
- Demo tenant enable + **public erişilebilir** bir entegratör örneği (prod sunucu callback'i localhost'a POST EDEMEZ — örneği bir yere deploy et veya tünelle).

**Adımlar:**
1. Entegratör örneğinde belge oluştur → "İmzala" → backend `POST /sessions` → tarayıcı `sign.wsoft.tr/rs/{id}`'ye yönlenir.
2. Sayfada "İmzala" → `wsign://session/{id}` → W.Sign Desktop açılır.
3. Desktop'ta sertifika seç + PIN gir → Desktop `/prepare` + `/complete` çağırır.
4. Tarayıcı `successRedirectUrl`'e döner; entegratör **pull** ile (`GET /sessions/{id}/result`, `X-WSign-Api-Key`) imzalı CMS'i çeker (nonce doğrula). Opsiyonel callback de `callbackUrl`'e gelir (HMAC + nonce).
5. İmzalı çıktıyı `POST /v1/verify` ile doğrula (isValid + signer CN).

Bu, daha önceki W.Sign kart testlerindeki gibi Volkan tarafından elle yürütülür.
