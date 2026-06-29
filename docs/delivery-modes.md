# Teslim Modları — `returnMode` (redirect | post | webhook | pull)

Redirect-session imzasında belge imzalandıktan sonra entegratörün **imzalı
sonucu** (`signedContentBase64`) alması gerekir. W.Sign bunu farklı ağ
kısıtlarına uyacak biçimde birden çok yolla teslim edebilir. Oturum açarken
gönderdiğiniz `returnMode` alanı, kullanıcı imzayı bitirince W.Sign'ın **ne
yapacağını** belirler:

| `returnMode` | W.Sign ne yapar | Sonucu nasıl alırsınız | Gerektirdiği ağ |
|---|---|---|---|
| `redirect` (vsy) | Kullanıcıyı `successRedirectUrl`'e **302** ile döndürür | Backend **pull** eder (outbound `GET .../result`) | Backend → W.Sign çıkışı (outbound) |
| `post` | `successRedirectUrl`'e tarayıcı-aracılı **otomatik-POST** formu gönderir | Sonuç POST gövdesinde **gelir** (`payload` + `signature`) | **Hiçbiri** — sonuç kullanıcının tarayıcısından geçer |
| `webhook` | `callbackUrl`'e server-to-server **POST** gönderir | İnbound POST'u **alırsınız** (HMAC header) | W.Sign → backend girişi (inbound/public) |
| `pull` | Kullanıcıyı döndürür ama tek teslim yolu poll'dur | Backend `result`'u **yoklar** (poll) | Backend → W.Sign çıkışı (outbound) |

> `redirect` ve `pull` pratikte aynı outbound `GET .../result` çağrısını
> kullanır; fark UX'tedir (redirect senkron döner, pull arka planda yoklanır).
> Bu depodaki birincil akış **redirect + pull**'dur (bkz.
> [`push-vs-pull.md`](push-vs-pull.md)). `webhook` ise opsiyonel güvenlik ağıdır.
> Bu belge asıl **`post`** modunu anlatır.

---

## `post` — kapalı sistem teslimi (bu dosyanın konusu)

**Ne zaman:** entegratör backend'i **ne dışarı çıkabiliyor** (pull/redirect
yapamaz) **ne de içeriden webhook alabiliyor** (inbound POST kapalı). Kapalı
kurumsal ağlar, hava-boşluklu segmentler, yalnızca tarayıcının dış dünyaya
ulaşabildiği ortamlar. Bu durumda sonucu taşıyabilecek tek aktör **kullanıcının
tarayıcısıdır**.

Çözüm 3D-Secure'un `termUrl`'e POST'uyla birebir aynı desendir: imza sayfası,
sonucu gizli alanlarla doldurulmuş bir HTML formuna koyar ve formu
`successRedirectUrl`'e **otomatik submit** eder. Sonuç böylece kullanıcının
tarayıcısı üzerinden, hiçbir doğrudan backend↔W.Sign bağlantısı olmadan teslim
edilir.

### Akış

```
 Kullanıcı (tarayıcı)        Entegratör Backend            W.Sign Server
   │                              │                              │
   │ 1. POST /sign                │                              │
   │ ────────────────────────────►│ POST .../sessions           │
   │                              │  { returnMode: "post", ... } │
   │                              │ ────────────────────────────►│
   │                              │◄──────── 201 {redirectUrl}   │
   │◄──── 302 redirectUrl ────────│                              │
   │                                                             │
   │ 2. İmza sayfası (sertifika seç + PIN)                       │
   │ ───────────────────────────────────────────────────────────►│
   │                                                             │
   │ 3. W.Sign otomatik-POST formu döndürür:                     │
   │    <form action="successRedirectUrl" method="post">         │
   │      payload, signature, sessionId, status, nonce, ...      │
   │    </form> + onload submit                                  │
   │◄────────────────────────────────────────────────────────────│
   │                              │                              │
   │ 4. POST /imza/tamam          │                              │
   │    (form-urlencoded)         │                              │
   │ ────────────────────────────►│ HMAC(secret, payload)==sig?  │
   │                              │ payload JSON parse           │
   │                              │ nonce eşleşmesini doğrula    │
   │                              │ imzalı belgeyi sakla         │
   │◄──── "İmza tamamlandı" ──────│                              │
```

### POST gövdesi (form-urlencoded)

W.Sign `successRedirectUrl`'e şu alanlarla bir form POST'lar:

| Alan | Açıklama |
|---|---|
| `payload` | **Tek doğruluk kaynağı.** Webhook callback gövdesiyle **birebir aynı** JSON (`sessionId, status, nonce, metadata, completedAt, signedContentBase64, signerCertificateBase64, ...`). |
| `signature` | `sha256=<hex>` = `HMAC-SHA256(hmacSecret, payload)`. Webhook'taki `X-WSign-Signature` başlığıyla **aynı** değer. |
| `sessionId`, `status`, `nonce`, `metadata`, `completedAt`, `signedContentBase64`, `signerCertificateBase64` | `payload` içindeki alanların **okunabilirlik kopyası** (kolaylık için form alanı olarak da gönderilir). |

> **Önemli:** doğrulama ve veri **yalnızca `payload`** üzerinden yapılmalıdır.
> Bireysel form alanları imzaya dahil **değildir**; sadece okuma kolaylığı
> içindir. Onlara güvenmeyin — `payload`'ı doğrulayın, sonra `payload`'ı parse
> edin.

### Doğrulama — `payload` + `signature`

Adımlar webhook callback ile **aynı** iki kontroldür; tek fark imzanın bir
HTTP başlığında değil, `signature` form alanında gelmesi ve HMAC'in `payload`
form alanının **ham metni** üzerinde hesaplanmasıdır:

```
1. Form alanlarından `payload` ve `signature`'ı al
2. HMAC-SHA256(hmacSecret, payload) == signature ?   → hayırsa 401/hata, dur
3. payload'ı JSON parse et
4. payload.nonce == bu sessionId için sakladığın nonce ?  → hayırsa hata, dur
5. signedContentBase64'ü sakla, durumu güncelle (idempotent)
6. Sonuç sayfasını göster
```

Üç örnekte de bu, callback ile aynı `verify_hmac` / `VerifyHmac` ve
`apply_result` / `ApplyResult` yardımcılarını yeniden kullanır.

`.NET` (özet — tam kod `dotnet/Program.cs`, `MapPost("/imza/tamam")`):

```csharp
var payload   = form["payload"].ToString();
var signature = form["signature"].ToString();           // "sha256=<hex>"

// HMAC, payload alanının ham byte'ları üzerinde (callback ile aynı yardımcı).
if (!VerifyHmac(Encoding.UTF8.GetBytes(payload), signature,
                Encoding.UTF8.GetBytes(CallbackSecret())))
    return /* 401 — imza geçersiz */;

var cb = JsonSerializer.Deserialize<CallbackBody>(payload, jsonOpts);
// nonce eşleşmesi + idempotent uygulama (pull + callback ile ortak):
ApplyResult(rec, cb.Status, cb.Nonce, cb.SignedContentBase64, ...);
```

`PHP` (özet — `php/index.php`, `handle_result_post`):

```php
$payload   = $_POST['payload'] ?? '';
$signature = $_POST['signature'] ?? '';                 // "sha256=<hex>"
if (!verify_hmac((string) $payload, (string) $signature, $cfg['callback_secret']))
    /* 401 */;
$cb = json_decode((string) $payload, true);
apply_result($rec, $cb);                                // nonce + idempotent
```

`Python` (özet — `python/main.py`, `result_post`):

```python
payload   = str(form.get("payload") or "")
signature = str(form.get("signature") or "")            # "sha256=<hex>"
if not verify_hmac(payload.encode(), signature, CALLBACK_SECRET):
    ...  # 401
cb = json.loads(payload)
apply_result(rec, cb)                                   # nonce + idempotent
```

### Güvenlik

- **Tek-kullanımlık doğrulama sunucuda:** `sessionId` tahmin edilemez, TTL'li ve
  tek kullanımlıktır; sonuç W.Sign'da yalnızca bir kez teslime hazırdır.
- **HMAC zorunlu:** `post` modunda sonuç **kullanıcının tarayıcısından geçtiği**
  için, gövde teorik olarak istemcide görülebilir/elle değiştirilebilir.
  `signature` = `HMAC-SHA256(hmacSecret, payload)` tam da bunu engeller: secret'ı
  yalnızca W.Sign ve entegratör bilir; `payload` bir byte değişse imza tutmaz.
  Bu yüzden `post` modunda HMAC doğrulaması **opsiyonel değildir.**
- **nonce:** sonucu sizin başlattığınız oturuma bağlar (replay/CSRF).
- **Sabit-zamanlı karşılaştırma:** imzayı `==` ile karşılaştırmayın (bkz.
  [`hmac-verify.md`](hmac-verify.md)).

### Tradeoff

| Artı | Eksi |
|---|---|
| Backend ne outbound ne inbound erişim ister — sadece tarayıcı dışarı çıkar | İmzalı sonuç kullanıcının tarayıcısından **geçer** (bütünlük HMAC ile korunur, ama gövde istemcide görünür) |
| Kapalı/segmentli ağlarda çalışır | Kullanıcı son adımı tamamlamazsa (tarayıcı kapanırsa) sonuç teslim **edilmez** — `post`'un kör noktası |
| 3D-Secure deneyimine birebir oturur | Büyük `signedContentBase64` form gövdesinde taşınır |

> **Öneri:** mümkünse `redirect`/`webhook` tercih edin (sonuç tarayıcıdan
> geçmez, kullanıcı dönmese de webhook teslim eder). `post`'u yalnızca backend'in
> **ne pull ne webhook** yapamadığı gerçekten kapalı ortamlar için kullanın.

---

## Hangi modu ne zaman?

- **Yerel geliştirme / hızlı deneme:** `redirect` (pull). Tünel gerekmez.
- **Senkron UX:** `redirect` (pull). Kullanıcı döner dönmez sonuç ekranda.
- **Üretim (açık backend):** `redirect` + `webhook` birlikte (pull anlık UX,
  webhook kullanıcı dönmese de teslim).
- **Kapalı sistem (backend dışarı çıkamaz/webhook alamaz):** `post`. Sonuç
  kullanıcının tarayıcısı üzerinden teslim edilir; `payload` + `signature`
  doğrulanır.
