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
- **callback opsiyoneldir** (üretimde güvenlik ağı). Onu da denemek isterseniz
  `PUBLIC_BASE_URL` W.Sign'dan erişilebilir olmalı — `cloudflared` / `ngrok`
  tünel adresini verin.

## Akış

`GET /` form → `POST /sign` (oturum aç + 302) → kullanıcı W.Sign'da imzalar →
kullanıcı `GET /imza/tamam`'e döner → **pull:** `GET /sessions/{id}/result`
(`X-WSign-Api-Key`, nonce doğrula, imzalı belgeyi sakla) → sonuç sayfası.
Opsiyonel: `POST /wsign/callback` (HMAC + nonce doğrula, aynı idempotent yol).
