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
      │ 4) POST callbackUrl       │                        │                   │
      │    X-WSign-Signature: sha256=<hex>                 │                   │
      │    { sessionId, status, nonce, signedContentBase64,│                   │
      │      signerCertificateBase64, ... }                │                   │
      │ ◄────────────────────────│                         │                   │
      │   HMAC + nonce doğrula → imzalı belgeyi sakla      │                   │
      │   200 OK                  │                         │                   │
      │                          │  302 → successRedirectUrl│                  │
      │                          │ ────────────────────────►                   │
      │ 5) GET /imza/tamam?session=...&status=completed    │                   │
      │◄─────────────────────────────────────────────────►│                   │
      │   "İmza tamamlandı" + imzalı belge gösterilir      │                   │
      │                          │                         │                   │
```

## Entegratörün sorumlulukları (özet)

1. **Oturum aç** — belgeyi base64'le, rastgele `nonce` üret, `POST /sessions`.
2. **Yönlendir** — dönen `redirectUrl`'e 302.
3. **Callback'i doğrula** — `X-WSign-Signature` HMAC'ini sabit-zamanlı
   karşılaştır, `nonce`'u beklenen değerle eşleştir.
4. **Sakla** — `signedContentBase64`'ü (DER CMS) kaydet.
5. **Sonucu göster** — `successRedirectUrl` sayfasında durumu ve imzalı belgeyi
   sun.

Adım 3'ten sonra olan her şey (tarayıcı sayfası, Desktop, sertifika, PIN, CMS
montajı) W.Sign tarafındadır ve entegratör kodunda yer almaz.
