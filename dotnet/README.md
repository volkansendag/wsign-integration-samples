# .NET örneği — W.Sign entegrasyonu (ASP.NET Core minimal API)

Bütün entegrasyon tek dosyada: [`Program.cs`](Program.cs) (~250 satır).

## Çalıştırma

```bash
# 1) Kök dizindeki .env.example'ı .env olarak kopyalayıp doldurun.
# 2) Ortam değişkenlerini yükleyin (PowerShell örneği):
#    $env:WSIGN_API_BASE="https://api.sign.wsoft.tr"
#    $env:WSIGN_API_KEY="demo-..."
#    $env:WSIGN_CALLBACK_SECRET="..."
#    $env:PUBLIC_BASE_URL="http://localhost:5000"

cd dotnet
dotnet run
```

Tarayıcıdan `http://localhost:5000` adresini açın → belge metnini girin →
"İmzala" → W.Sign imzalama sayfasına yönlendirilirsiniz.

## Gereksinimler

- .NET 8 SDK veya üzeri.
- W.Sign callback'inin ulaşabilmesi için `PUBLIC_BASE_URL` dışarıdan erişilebilir
  olmalıdır. Yerel testte `cloudflared` / `ngrok` gibi bir tünel kullanın ve
  tünel adresini `PUBLIC_BASE_URL` olarak verin.

## Akış

`GET /` form → `POST /sign` (oturum aç + 302) → kullanıcı W.Sign'da imzalar →
`POST /wsign/callback` (HMAC + nonce doğrula, imzalı belgeyi sakla) →
`GET /imza/tamam` (sonuç sayfası).
