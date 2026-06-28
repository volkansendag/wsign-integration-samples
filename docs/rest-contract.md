# W.Sign Redirect-Session — REST Sözleşmesi (Entegratör Görünümü)

> Bu belge, bir **entegratörün** W.Sign ile e-imza akışı kurmak için bilmesi
> gereken **dilden bağımsız** REST sözleşmesidir. 3D-Secure ödeme akışına
> benzer: siz bir oturum açarsınız, kullanıcıyı W.Sign'a yönlendirirsiniz,
> imza bitince W.Sign size bir callback gönderir.
>
> Bu örneklerde yalnızca **istemci/entegratör tarafı** vardır. W.Sign
> çekirdeği (CMS üretimi, PKCS#11, sertifika doğrulama, oturum durum makinesi)
> sunucu tarafında kapalıdır — entegrasyon yalnızca **REST + HMAC** üzerinden
> yapılır.

## Adresler

| Amaç | Adres |
|---|---|
| Server-to-server API | `https://api.sign.wsoft.tr` |
| Tarayıcı imzalama sayfası | `https://sign.wsoft.tr/rs/{sessionId}` |

Tüm çağrılar HTTPS zorunludur.

## Entegratörün kullandığı 2 endpoint

Entegratör backend'i yalnızca iki endpoint çağırır. Geri kalan endpoint'leri
(`/prepare`, `/complete`) W.Sign Desktop kullanır; entegratör bunları görmez.

### 1. Oturum oluştur — `POST /v1/redirect-sign/sessions`

İstek başlığı: `X-WSign-Api-Key: <api-key>` (zorunlu), `Content-Type: application/json`.

```jsonc
{
  "documentBase64":     "<base64 belge>",                    // zorunlu
  "documentName":       "Sozlesme_2026.pdf",                  // ops; Desktop diyaloğunda gösterilir
  "signatureProfile":   "CAdES-BES",                          // CAdES-BES | CAdES-T | XAdES-B-B | PAdES-B-B
  "digestAlgorithm":    "SHA256",                             // ops: SHA256 | SHA384 | SHA512
  "callbackUrl":        "https://acme.example/wsign/callback",// zorunlu; host allowlist'te olmalı
  "successRedirectUrl": "https://acme.example/imza/tamam",    // zorunlu; host allowlist'te olmalı
  "cancelRedirectUrl":  "https://acme.example/imza/iptal",    // ops
  "nonce":              "<base64 >= 16 byte>",                // zorunlu; callback'te aynen döner
  "ttlMinutes":         15,                                   // ops [1,60], vsy 15
  "metadata":           { "talepNo": "A-123" }                // ops; opak; callback'te aynen döner
}
```

Yanıt `201`:

```jsonc
{
  "sessionId":   "550e8400-e29b-41d4-a716-446655440000-a3f9c12b",
  "redirectUrl": "https://sign.wsoft.tr/rs/550e8400-...-a3f9c12b",
  "expiresAt":   "2026-06-27T14:32:11Z",
  "status":      "pending"
}
```

Hatalar: `401 UNAUTHORIZED`, `400 INVALID_BODY|INVALID_NONCE|INVALID_PROFILE`,
`403 CALLBACK_NOT_ALLOWED|REDIRECT_NOT_ALLOWED`, `413 PAYLOAD_TOO_LARGE`.

Entegratör `redirectUrl`'i alır ve kullanıcıyı **302** ile oraya yönlendirir.

### 2. (Opsiyonel) Durum sorgula — `GET /v1/redirect-sign/sessions/{id}`

Auth yok; `sessionId` taşıyıcıdır. Hassas veri (belge / dataToSign) DÖNMEZ.

```jsonc
{
  "sessionId":    "...",
  "status":       "pending|awaitingSignature|signing|completed|expired|cancelled",
  "documentName": "Sozlesme_2026.pdf",
  "origin":       "https://acme.example",
  "expiresAt":    "..."
}
```

Callback başarısız olursa entegratör bu endpoint ile sonucu yoklayabilir.

## Callback — W.Sign → Entegratör

İmza tamamlanınca (veya iptal/expiry'de) W.Sign, oturumda verdiğiniz
`callbackUrl`'e **POST** gönderir.

- Başlık: `X-WSign-Signature: sha256=<hex>` — gövdenin tamamı üzerinde
  HMAC-SHA256, **entegratörün `hmacSecret`'ı** ile hesaplanır.
- Entegratör bu imzayı **ve** `nonce`'u doğrulamalıdır.

```jsonc
{
  "sessionId":               "550e8400-...-a3f9c12b",
  "status":                  "completed",          // completed | cancelled | expired
  "nonce":                   "<istekteki nonce aynen>",
  "metadata":                { "talepNo": "A-123" },
  "signedContentBase64":     "<DER CMS — yalnızca completed>",
  "signerCertificateBase64": "<DER cert — yalnızca completed>",
  "completedAt":             "2026-06-27T14:32:11Z",
  "errorReason":             null
}
```

Entegratör doğrulama sonrası `200` döndürmelidir. Faz 0'da teslimat best-effort
tek denemedir (Faz 2: 5s/30s/120s retry). Bu yüzden `GET /sessions/{id}` ile
yoklama her zaman güvenli bir yedektir.

## Desktop endpoint'leri (entegratörü ilgilendirmez)

Eksiksizlik için: `POST /sessions/{id}/prepare` ve
`POST /sessions/{id}/complete` W.Sign Desktop tarafından çağrılır. Kullanıcı
sertifikasını imza anında Desktop'ta seçer (deferred prepare); belge hiçbir
zaman tarayıcıya/istemciye inmez. Entegratör bu uçları doğrudan kullanmaz.

## Güvenlik özeti

- **API key** yalnızca `POST /sessions` ve `DELETE /sessions/{id}` için.
- **sessionId** tahmin edilemez (`{uuid}-{hmac8}`), tek kullanımlık, TTL'li.
- **nonce** callback'i W.Sign'a bağlar (CSRF/replay koruması).
- **callbackUrl / successRedirectUrl** host'ları entegratör kaydındaki
  allowlist ile sınırlıdır (open-redirect / SSRF önlemi).
- **HMAC** callback gövdesinin gerçekten W.Sign'dan geldiğini kanıtlar.

Kaynak sözleşme: W.Sign ADR-0006 "Endpoint Sözleşmesi v1 (Locked — 2026-06-27)".
