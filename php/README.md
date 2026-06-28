# PHP örneği — W.Sign entegrasyonu (saf PHP, framework yok)

Bütün entegrasyon tek dosyada: [`index.php`](index.php). Yapılandırma
[`config.php`](config.php) ile ortam değişkenlerinden okunur.

## Çalıştırma

```bash
# 1) Kök dizindeki .env.example'ı .env olarak kopyalayıp doldurun.
#    (config.php kök .env dosyasını otomatik yükler; ya da getenv ile verin.)
cd php
php -S localhost:8080 index.php   # index.php "router script" olarak çalışır
```

Tarayıcıdan `http://localhost:8080` adresini açın → belge metnini girin →
"İmzala" → W.Sign imzalama sayfasına yönlendirilirsiniz.

## Gereksinimler

- PHP 8.1+ ve `curl`, `json` eklentileri. (`composer` opsiyoneldir; harici
  bağımlılık yoktur.)
- W.Sign callback'inin ulaşabilmesi için `PUBLIC_BASE_URL` dışarıdan erişilebilir
  olmalıdır. Yerel testte `cloudflared` / `ngrok` gibi bir tünel kullanın.

## Notlar

- Oturum durumu basit dosya deposunda (`php/storage/`, gitignore'lu) tutulur;
  üretimde veritabanı kullanın.
- `php -S` dahili sunucusu tüm istekleri `index.php`'ye yönlendirir (front
  controller); ek yapılandırma gerekmez.
