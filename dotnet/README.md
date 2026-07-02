# .NET örneği — W.Sign entegrasyonu (ASP.NET Core minimal API)

Bütün entegrasyon tek dosyada: [`Program.cs`](Program.cs) (~250 satır).

## Çalıştırma

```bash
# 1) Kök dizindeki .env.example'ı .env olarak kopyalayıp doldurun.
#    (.env git'e GİTMEZ — .gitignore'da.)
cp .env.example .env

cd dotnet
dotnet run
```

`Program.cs` başlangıçta depo kökündeki `.env` dosyasını otomatik yükler
(bağımlılıksız basit ayrıştırıcı). Öncelik: **process env > `.env` > placeholder
fallback** — yani bir değişkeni kabukta da verirseniz (`$env:WSIGN_API_KEY=...`)
o `.env`'i ezer.

Tarayıcıdan `http://localhost:5000` adresini açın → belge metnini girin →
"İmzala" → W.Sign imzalama sayfasına yönlendirilirsiniz.

## Gereksinimler

- .NET 8 SDK veya üzeri.
- **Yerel test (redirect + pull): tünel GEREKMEZ.** Sonuç, backend'in W.Sign'a
  yaptığı outbound GET ile çekilir. `localhost` host'unu entegratör kaydınızın
  redirect allowlist'ine ekleyin (kullanıcının `successRedirectUrl`'e dönebilmesi
  için).
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
