# Akış Diyagramı — Redirect-Session İmza (3D-Secure Tarzı)

Dört aktör vardır. Bu örnek depodaki kod **yalnızca "Entegratör"** sütununu
uygular. "W.Sign Server", "Kullanıcı Tarayıcısı" ve "Kullanıcı Desktop"
W.Sign tarafındadır (kapalı).

```
Entegratör Backend         W.Sign Server               Tarayıcı            Desktop
  (bu örnek)               (api.sign.wsoft.tr)         (kullanıcı)         (kullanıcı PC)
      │                          │                         │                   │
      │ 1) Belge formu doldurulur (GET /)                  │                   │
      │◄─────────────────────────────────────────────────►│                   │
      │                          │                         │                   │
      │ 2) POST /v1/redirect-sign/sessions                 │                   │
      │    X-WSign-Api-Key: ***                            │                   │
      │    { documentBase64, callbackUrl,                  │                   │
      │      successRedirectUrl, nonce, ... }              │                   │
      │ ────────────────────────►│                         │                   │
      │                          │ sessionId üret          │                   │
      │                          │ belgeyi sakla           │                   │
      │ ◄────────────────────────│                         │                   │
      │   201 { sessionId, redirectUrl }                   │                   │
      │   (nonce'u sessionId ile eşleştir, sakla)          │                   │
      │                          │                         │                   │
      │ 3) 302 → redirectUrl                               │                   │
      │ ──────────────────────────────────────────────────►                   │
      │                          │  GET /rs/{sessionId}    │                   │
      │                          │◄────────────────────────│                   │
      │                          │  Desktop kurulu mu? probe│                  │
      │                          │  wsign://session/{id}   │                   │
      │                          │ ─────────────────────────────────────────► │
      │                          │  GET .../prepare,       │                   │
      │                          │  POST .../complete      │                   │
      │                          │◄────────────────────────────────────────── │
      │                          │  (sertifika seçimi + PIN, belge PC'ye inmez)│
      │                          │                         │                   │
      │                          │  302 → successRedirectUrl│                  │
      │                          │ ────────────────────────►                   │
      │ 4) GET /imza/tamam?session={id}  (kullanıcı geri döner)                │
      │◄─────────────────────────────────────────────────►│                   │
      │                          │                         │                   │
      │ 4a) PULL (birincil): GET /v1/redirect-sign/sessions/{id}/result        │
      │     X-WSign-Api-Key: ***  │                        │                   │
      │ ────────────────────────►│                         │                   │
      │ ◄────────────────────────│                         │                   │
      │   200 { status: completed, signedContentBase64,    │                   │
      │         signerCertificateBase64, nonce, ... }      │                   │
      │   nonce doğrula → imzalı belgeyi sakla (idempotent)│                   │
      │   "İmza tamamlandı" + imzalı belge gösterilir      │                   │
      │                          │                         │                   │
      │ 4b) PUSH (opsiyonel güvenlik ağı): POST callbackUrl                    │
      │     X-WSign-Signature: sha256=<hex>                │                   │
      │ ◄────────────────────────│  { sessionId, status, nonce,               │
      │   HMAC + nonce doğrula →     signedContentBase64, ... }                │
      │   imzalı belgeyi sakla (AYNI idempotent yol)       │                   │
      │   200 OK                  │                         │                   │
      │                          │                         │                   │
```

> 4a (pull) ve 4b (push) **aynı oturum için ikisi birden** gerçekleşebilir;
> ikisi de aynı idempotent yardımcıyı çağırır, sorun olmaz. Pull birincildir ve
> tünelsiz çalışır; callback üretimde kullanıcı hiç dönmese bile teslimi
> garantiler. Ayrıntı: [`push-vs-pull.md`](push-vs-pull.md).

## Entegratörün sorumlulukları (özet)

1. **Oturum aç** — belgeyi base64'le, rastgele `nonce` üret, `POST /sessions`.
2. **Yönlendir** — dönen `redirectUrl`'e 302.
3. **Sonucu çek (pull)** — kullanıcı `successRedirectUrl`'e dönünce
   `GET /sessions/{id}/result`'ı `X-WSign-Api-Key` ile çağır; yanıttaki `nonce`'u
   beklenen değerle eşleştir.
4. **(Opsiyonel) Callback'i doğrula** — `X-WSign-Signature` HMAC'ini
   sabit-zamanlı karşılaştır, `nonce`'u eşleştir (üretimde güvenlik ağı).
5. **Sakla & göster** — `signedContentBase64`'ü (DER CMS) idempotent kaydet;
   sonuç sayfasında durumu ve imzalı belgeyi sun.

Adım 3'teki redirect'ten sonra W.Sign tarafında olan her şey (tarayıcı sayfası,
Desktop, sertifika, PIN, CMS montajı) entegratör kodunda yer almaz.
