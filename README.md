# W.Sign Entegrasyon Örnekleri

W.Sign ile e-imza entegrasyonunun **ne kadar basit** olduğunu gösteren resmi
örnek depo. Aynı senaryo üç dilde (.NET, PHP, Python) birebir uygulanır:
3D-Secure ödeme akışına benzeyen **redirect-session** modeli.

> **5 dakikada özet:** Oturum açarsınız, kullanıcıyı W.Sign'a yönlendirirsiniz,
> kullanıcı dönünce imzalı belgeyi outbound bir GET ile **çekersiniz (pull)**.
> Pull yerelde **tünelsiz** çalışır. Üretimde ayrıca opsiyonel bir **callback
> (webhook)** güvenlik ağı eklersiniz. Entegratör tarafında yazmanız gereken tek
> şey budur — birkaç HTTP çağrısı.

## Akış (3D-Secure gibi) — redirect + pull

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
           │ 4. 302 → successRedirectUrl (/imza/tamam?session={id}) │
 ┌─────────▼───────────┐                                            │
 │  Entegratör Backend │  4a. PULL (birincil):                      │
 │                     │  GET /v1/redirect-sign/sessions/{id}/result│
 │  • nonce doğrula    │ ─────────────────────────────────────────►│
 │  • imzalı belgeyi   │  X-WSign-Api-Key                           │
 │    sakla (idempotent)◄──────────────────────────────────────────┤
 │                     │  200 {status, signedContentBase64, nonce…} │
 └─────────┬───────────┘                                            │
           │ "İmza tamamlandı" + imzalı belge gösterilir            │
           ▼                                                        │
    ┌───────────────────────────────────────────────────────────┐  │
    │ 4b. PUSH (opsiyonel güvenlik ağı): W.Sign → POST callbackUrl│◄─┘
    │     X-WSign-Signature: sha256=…  (HMAC + nonce doğrula)     │
    │     Kullanıcı hiç dönmese bile teslimi garantiler.          │
    └───────────────────────────────────────────────────────────┘
```

Push vs pull ayrıntısı: [`docs/push-vs-pull.md`](docs/push-vs-pull.md).
Daha ayrıntılı diyagram: [`docs/sequence.md`](docs/sequence.md).

> **Kapalı sistem mi?** Backend ne dışarı çıkıp pull yapabiliyor ne de içeriden
> webhook alabiliyorsa, oturumu `WSIGN_RETURN_MODE=post` ile açın: W.Sign sonucu
> kullanıcının tarayıcısı üzerinden bir otomatik-POST formuyla
> `successRedirectUrl`'e teslim eder (3D-Secure `termUrl`'e POST gibi). Tüm teslim
> modları ve `post` doğrulaması: [`docs/delivery-modes.md`](docs/delivery-modes.md).

## Bu depo neyi içerir, neyi içermez

| İçerir | İçermez |
|---|---|
| İstemci/entegratör tarafı kod (.NET, PHP, Python) | W.Sign çekirdeği (CMS, kripto) |
| REST çağrıları + pull (result) + callback HMAC | W.Sign Server / oturum durum makinesi |
| Çalışan örnek web uygulaması (3 dil) | PKCS#11 / sertifika / Desktop kodu |

Bu kasıtlıdır: entegrasyon yalnızca **REST + HMAC** üzerinden yapılır; W.Sign'ın
içselleri kapalıdır. Entegratörün e-imza kütüphanesi kurmasına, sertifika veya
token yönetmesine gerek yoktur.

## Senaryo

Kurgusal **"Örnek Belediye"** bir belge metni üretir ve W.Sign ile imzalatır.
Üç örnek de tıpatıp aynı adımları uygular:

1. Belge oluşturma formu (`GET /`).
2. "İmzala" → `POST /v1/redirect-sign/sessions` → `{sessionId, redirectUrl}`.
3. Kullanıcıyı `redirectUrl`'e 302 yönlendir.
4. Kullanıcı `GET /imza/tamam?session={id}`'e döner → **pull (birincil):**
   `GET /v1/redirect-sign/sessions/{id}/result` (`X-WSign-Api-Key`) →
   **nonce doğrula** → imzalı belgeyi sakla → sonuç sayfası.
5. **(Opsiyonel güvenlik ağı)** `POST /wsign/callback` → **HMAC + nonce doğrula**
   → imzalı belgeyi sakla (pull ile aynı idempotent yol).

## Hızlı başlangıç

```bash
# 1) Yapılandırmayı hazırlayın: .env.example'ı .env olarak kopyalayıp doldurun.
cp .env.example .env
#    .env içindeki değerleri doldurun (aşağıya bakın).
#    .env git'e GİTMEZ (.gitignore'da) — sırlarınız depoya sızmaz.

# 2) İstediğiniz dili çalıştırın
```

Her üç örnek de başlangıçta depo kökündeki `.env`'i otomatik yükler (harici
bağımlılık yok). Öncelik: **process env > `.env` > placeholder fallback** — bir
değişkeni kabukta da tanımlarsanız o `.env`'i ezer.

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
| `WSIGN_CALLBACK_SECRET` | Callback/POST HMAC secret'ı | `demo-...` (placeholder) |
| `WSIGN_SIGNATURE_PROFILE` | İmza tipi varsayılanı: `CAdES-BES` \| `CAdES-T` \| `CAdES-ESXLong` \| `XAdES-BES` \| `XAdES-T` | `CAdES-BES` |
| `WSIGN_RETURN_MODE` | Sonuç teslim modu: `redirect` (vsy) \| `post` (kapalı sistem) | `redirect` |
| `PUBLIC_BASE_URL` | Bu örneğin dışarıdan erişilebilir kök adresi | `http://localhost:5000` |

> **İmza tipi seçimi (CAdES/XAdES; BES / -T / ESXLong):** İmzalama formundaki
> "İmza tipi" açılır listesinden `CAdES-BES` / `CAdES-T` / `CAdES-ESXLong` /
> `XAdES-BES` / `XAdES-T` seçilir ve create isteğine `signatureProfile` olarak
> geçer. `CAdES-ESXLong` **uzun dönemli imzadır** (zaman damgası + sertifika
> zinciri + OCSP/CRL gömülü; EBYS/arşiv için). Damgalı tipler (`-T` / `ESXLong`)
> için entegratörde **Kamu SM TSA** tanımlı olmalıdır; değilse server `400`
> (`TSA_NOT_CONFIGURED`) döner ve örnek bunu kullanıcıya açıklar. İmzalı çıktının
> içerik türü/uzantısı profile göre değişir (CAdES → `.p7s`, XAdES → `.xml`).
> Ayrıntı: [`docs/signature-profiles.md`](docs/signature-profiles.md).

> **Hosted demo:** Kurulumsuz denemek için bir **demo entegratör anahtarı yakında**
> yayınlanacaktır (`api.sign.wsoft.tr` üzerinde sandbox tenant). O zamana kadar
> kendi W.Sign Server adresinizi ve anahtarınızı `.env` ile verin.

> **Yerel test — tünel GEREKMEZ:** redirect + pull akışı outbound çalışır.
> Yalnızca `localhost` host'unu entegratör kaydınızın **redirect allowlist**'ine
> ekleyin (kullanıcının `successRedirectUrl`'e dönebilmesi için); `PUBLIC_BASE_URL`
> `http://localhost:5000` kalabilir. Sonuç, backend'in W.Sign'a yaptığı GET ile
> çekilir.

> **callbackUrl ne zaman gönderilir?** Örnekler `callbackUrl`'i yalnızca webhook
> gerçekten kullanılabilir + gerekli olduğunda gönderir. **Yerel/kapalı kullanımda**
> (`PUBLIC_BASE_URL` loopback — `localhost`/`127.x`/`::1` — **veya**
> `WSIGN_RETURN_MODE=post`) `callbackUrl` **hiç gönderilmez**: webhook loopback'e
> ulaşamaz ve `post` modunda zaten gereksizdir. Bu durumda entegratör kaydınızda
> **callback allowlist gerekmez** — yalnızca redirect allowlist'e `localhost`
> ekleyin. Webhook'u (push güvenlik ağı) gerçekten denemek isterseniz
> `PUBLIC_BASE_URL`'i **public** bir adrese (tünel: `cloudflared` / `ngrok`) ayarlayın;
> o zaman `callbackUrl` otomatik gönderilir.

## Güvenlik

İmza sonucu iki yoldan alınabilir; her ikisi de iki bağımsız kontrol uygular.

**Pull** (`GET /sessions/{id}/result`):

1. **Auth + sahiplik** — `X-WSign-Api-Key` zorunludur; yalnızca oturumu açan
   entegratör sonucu görür (başkasının/bilinmeyen oturumu → **404**). Session
   id'yi ele geçiren biri imzalı belgeyi çekemez.
2. **nonce** — yanıttaki değer, oturum açarken sakladığınızla sabit-zamanlı
   karşılaştırılır.

**Push** (callback, internete açık):

1. **HMAC-SHA256** — `X-WSign-Signature: sha256=<hex>` başlığını **ham gövde**
   üzerinde, paylaşılan secret ile sabit-zamanlı karşılaştırır.
2. **nonce** — pull'daki ile aynı kontrol (replay/CSRF koruması).

Push vs pull (ne zaman hangisi): [`docs/push-vs-pull.md`](docs/push-vs-pull.md).
Her dilde HMAC snippet'i: [`docs/hmac-verify.md`](docs/hmac-verify.md).
Tam REST sözleşmesi: [`docs/rest-contract.md`](docs/rest-contract.md).

## Lisans

Örnek kod [MIT](LICENSE) ile sunulur. W.Sign ürün ve sunucusu bu lisansın
kapsamı dışındadır.
