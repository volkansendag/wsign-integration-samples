# Python örneği — W.Sign entegrasyonu (FastAPI)

Bütün entegrasyon tek dosyada: [`main.py`](main.py).

## Çalıştırma

```bash
# 1) Kök dizindeki .env.example'ı .env olarak kopyalayıp doldurun ve
#    ortam değişkenlerini yükleyin (örn. `set -a; source ../.env; set +a`).
cd python
python -m venv .venv
# Windows:  .venv\Scripts\activate     |  Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 5000
```

Tarayıcıdan `http://localhost:5000` adresini açın → belge metnini girin →
"İmzala" → W.Sign imzalama sayfasına yönlendirilirsiniz.

## Gereksinimler

- Python 3.10+.
- W.Sign callback'inin ulaşabilmesi için `PUBLIC_BASE_URL` dışarıdan erişilebilir
  olmalıdır. Yerel testte `cloudflared` / `ngrok` gibi bir tünel kullanın.

## Notlar

- Oturum durumu in-memory bir sözlükte tutulur; üretimde veritabanı kullanın.
- `main.py` yapılandırmayı ortam değişkenlerinden okur; `.env` dosyasını kabuk
  üzerinden yükleyin veya değişkenleri doğrudan tanımlayın.
