# Push (callback) vs Pull (result) — İmza Sonucunu Almanın İki Yolu

Redirect-session imzasında belge imzalandıktan sonra entegratörün **imzalı
içeriği (`signedContentBase64`) alması** gerekir. Bunu yapmanın iki yolu vardır.
Bu örnek depo **ikisini birlikte** kullanır: pull birincil, callback güvenlik
ağı.

| | **Pull** (sonucu çek) | **Push** (callback / webhook) |
|---|---|---|
| Yön | Entegratör → W.Sign (outbound GET) | W.Sign → Entegratör (inbound POST) |
| Endpoint | `GET /v1/redirect-sign/sessions/{id}/result` | Sizin `callbackUrl`'iniz |
| Tetikleyen | Kullanıcı `successRedirectUrl`'e döner | İmza sunucuda tamamlanır |
| Yerel dev | **Tünelsiz çalışır** (NAT/localhost arkasından) | Public adres / tünel gerekir |
| Kimlik doğrulama | `X-WSign-Api-Key` + oturum sahipliği | Gövde üzerinde HMAC-SHA256 + nonce |
| UX | Senkron (kullanıcı sonuç sayfasında bekler) | Asenkron (kullanıcıdan bağımsız) |
| Güvenilirlik | Kullanıcı dönmezse sonuç çekilmez | Kullanıcı dönmese de teslim olur |

İkisi birbirini tamamlar. Hiçbiri tek başına her senaryoyu kapsamaz; bu yüzden
üretimde **ikisi birden** önerilir.

---

## Pull (birincil akış)

Kullanıcı imzayı bitirip `successRedirectUrl`'e (örn.
`localhost:5000/imza/tamam?session={id}`) döndüğünde, entegratör backend'i
sonucu doğrudan W.Sign'dan çeker:

```
GET {API_BASE}/v1/redirect-sign/sessions/{id}/result
X-WSign-Api-Key: <oturumu açan entegratörün anahtarı>
```

Yanıt:

```jsonc
{
  "sessionId":               "...",
  "status":                  "pending|awaitingSignature|signing|completed|expired|cancelled",
  "signedContentBase64":     "<DER CMS — yalnızca completed; aksi halde null>",
  "signerCertificateBase64": "<DER cert — yalnızca completed>",
  "contentType":             "application/pkcs7-mime",  // imzalı dosyanın MIME'ı
  "fileExtension":           ".p7s",                    // imzalı dosyanın uzantısı
  "completedAt":             "2026-06-28T10:00:00Z",
  "nonce":                   "<oturumdaki nonce aynen>",
  "metadata":                { "talepNo": "A-123" }
}
```

`status == "completed"` ise `signedContentBase64` doludur; entegratör onu saklar
ve sonuç sayfasında gösterir.

```
 Kullanıcı            Entegratör Backend           W.Sign Server
   │                        │                            │
   │ GET /imza/tamam?session={id}                        │
   │ ──────────────────────►│                            │
   │                        │ GET .../{id}/result        │
   │                        │ X-WSign-Api-Key: ***        │
   │                        │ ──────────────────────────►│
   │                        │   200 { status: completed, │
   │                        │◄──────  signedContentBase64,│
   │                        │         nonce, ... }        │
   │                        │ nonce eşleşmesini doğrula   │
   │                        │ imzalı belgeyi sakla        │
   │  "İmza tamamlandı"     │                            │
   │◄───────────────────────│                            │
```

**Neden yerelde tünelsiz çalışır:** çağrı *entegratörden W.Sign'a doğru*
gider (outbound). Entegratörün internetten erişilebilir olması gerekmez;
`localhost:5000` arkasında oturup sonucu çekebilir. Tek koşul: `localhost`
host'unun redirect allowlist'inde olması (kullanıcının `successRedirectUrl`'e
dönebilmesi için).

---

## Push (callback / webhook — güvenlik ağı)

İmza tamamlanınca W.Sign, oturumda verdiğiniz `callbackUrl`'e bir POST gönderir:

```
POST {callbackUrl}
X-WSign-Signature: sha256=<hex>     (gövdenin tamamı üzerinde HMAC-SHA256)
{ sessionId, status, nonce, signedContentBase64, signerCertificateBase64, ... }
```

```
 W.Sign Server                      Entegratör Backend
   │                                      │
   │ POST {callbackUrl}                   │
   │ X-WSign-Signature: sha256=<hex>      │
   │ ────────────────────────────────────►│
   │                                      │ HMAC (ham gövde) doğrula
   │                                      │ nonce doğrula
   │                                      │ imzalı belgeyi sakla
   │                  200 OK              │
   │◄─────────────────────────────────────│
```

Callback **gerçek ve üretimde gereklidir**: kullanıcı sonuç sayfasına hiç
dönmese bile (tarayıcıyı kapattı, ağ koptu, mobilde uygulama arka plana düştü)
imzalı belge yine de güvenilir biçimde teslim olur. Pull'un kör noktası tam da
budur — pull yalnızca kullanıcı geri döndüğünde tetiklenir.

Callback inbound olduğu için entegratörün **public erişilebilir** olmasını
ister. Yerel geliştirmede bir tünel (`cloudflared`, `ngrok`) gerekir; bu yüzden
yerel testte callback'i opsiyonel bırakıp pull ile ilerleyebilirsiniz.

---

## Güvenlik

**Pull** — iki katmanlı:

1. **Auth + sahiplik:** `GET .../result` için `X-WSign-Api-Key` zorunludur ve
   yalnızca oturumu **oluşturan** entegratör sonucu görebilir. Başka birinin
   `sessionId`'sini bilseniz bile, sizin anahtarınızla istediğinizde **404**
   alırsınız. Yani session id'yi ele geçiren biri imzalı belgeyi çekemez.
2. **nonce eşleşmesi:** yanıttaki `nonce`, oturumu açarken sakladığınız değerle
   sabit-zamanlı karşılaştırılır. Sonucun gerçekten sizin başlattığınız oturuma
   ait olduğunu doğrular.

> `GET .../result` kota tüketmez; sonuç hazır olana kadar güvenle birden çok kez
> çağrılabilir (örn. `pending` dönerse kısa bir poll).

**Push** — iki katmanlı:

1. **HMAC-SHA256:** `X-WSign-Signature` başlığı, **ham gövde** üzerinde paylaşılan
   secret ile doğrulanır (bkz. [`hmac-verify.md`](hmac-verify.md)). Callback
   internete açık olduğu için bu zorunludur — secret'ı yalnızca W.Sign bilir.
2. **nonce eşleşmesi:** pull'daki ile aynı kontrol.

Her iki yolda da **nonce** kontrolü ortaktır; bu örneklerde her iki yol da tek
bir `apply_result` / `ApplyResult` yardımcısını çağırır.

---

## İdempotentlik

Pull ve callback aynı oturum için **ikisi birden** tetiklenebilir (kullanıcı
döner *ve* callback gelir). Bu sorun değildir: her iki yol da aynı idempotent
yardımcıyı çağırır ve aynı `sessionId` için aynı sonucu yazar. İkinci uygulama
ilkinin üzerine birebir aynı değerleri yazar — çift kayıt veya bozulma olmaz.

Uygulamanızda imzalı belgeyi kalıcı bir depoya yazarken bunu unutmayın: yazma
işlemi `sessionId` üzerinden idempotent olmalıdır (örn. "varsa güncelle, yoksa
ekle").

---

## Hangisini ne zaman?

- **Yerel geliştirme / hızlı deneme:** yalnızca **pull**. Tünel kurmaya gerek
  yok; `localhost`'u redirect allowlist'ine ekleyip sonucu çekin.
- **Senkron UX (kullanıcı sonucu hemen görmeli):** **pull** birincil. Kullanıcı
  `successRedirectUrl`'e döner dönmez imzalı belge ekranda.
- **Üretim:** **ikisi birden.** Pull anlık UX'i verir; callback, kullanıcı hiç
  dönmediğinde teslimi garantiler. Callback bir nedenle kaçarsa (geçici ağ
  hatası), bir sonraki pull (veya zamanlanmış bir `result` yoklaması) sonucu
  yine de uzlaştırır (reconcile).

**Önerilen üretim deseni:** callback'i imzalı belgeyi yazan otoriter yol olarak
kurun; pull'u hem anlık UX için hem de callback kaçtığında reconcile için
kullanın. İkisi idempotent olduğundan birlikte güvenle çalışırlar.
