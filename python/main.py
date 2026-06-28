# ===========================================================================
# W.Sign entegrasyon örneği — FastAPI
#
# Bu dosya, bir entegratör web uygulamasının W.Sign ile e-imza akışını kurmak
# için yazması gereken kodun TAMAMIDIR. Gördüğünüz gibi sadece birkaç HTTP
# çağrısı: oturum aç -> kullanıcıyı yönlendir -> callback'i HMAC ile doğrula.
#
# W.Sign'ın içselleri (CMS üretimi, PKCS#11, sertifika, oturum durum makinesi)
# sunucu tarafında kapalıdır. Entegrasyon yalnızca REST + HMAC üzerindendir.
#
# Senaryo: kurgusal "Örnek Belediye" bir belge metni üretir ve imzalatır.
#
# Çalıştırma (kök .env dosyasını doldurduktan sonra):
#   cd python && pip install -r requirements.txt && uvicorn main:app --port 5000
# ===========================================================================

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse


# --- Yapılandırma: yalnızca ortam değişkenlerinden. Hiçbir sır hardcode değil. ---
def env(key: str, fallback: str) -> str:
    v = os.environ.get(key)
    return v if v else fallback


API_BASE = env("WSIGN_API_BASE", "https://api.sign.wsoft.tr").rstrip("/")
API_KEY = env("WSIGN_API_KEY", "demo-REPLACE-ME")
CALLBACK_SECRET = env("WSIGN_CALLBACK_SECRET", "demo-callback-secret-REPLACE-ME").encode()
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "http://localhost:5000").rstrip("/")

app = FastAPI(title="W.Sign entegrasyon örneği")

# --- Basit in-memory oturum deposu (üretimde: veritabanı). ---
sessions: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# 1) Belge oluşturma formu
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def form() -> str:
    return page_form()


# ---------------------------------------------------------------------------
# 2) "İmzala" -> oturum oluştur -> 302 yönlendir
# ---------------------------------------------------------------------------
@app.post("/sign")
async def sign(belgeMetni: str = Form("")):
    text = belgeMetni.strip()
    if not text:
        return HTMLResponse(page_error("Belge metni boş olamaz."), status_code=400)

    document_name = f"OrnekBelediye_Belge_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.txt"

    # CSRF/replay koruması: rastgele nonce. Callback'te aynen geri gelecek.
    nonce = base64.b64encode(secrets.token_bytes(16)).decode()

    payload = {
        "documentBase64": base64.b64encode(text.encode()).decode(),
        "documentName": document_name,
        "signatureProfile": "CAdES-BES",
        "digestAlgorithm": "SHA256",
        "callbackUrl": f"{PUBLIC_BASE_URL}/wsign/callback",
        "successRedirectUrl": f"{PUBLIC_BASE_URL}/imza/tamam",
        "cancelRedirectUrl": f"{PUBLIC_BASE_URL}/imza/iptal",
        "nonce": nonce,
        "ttlMinutes": 15,
        "metadata": {"talepNo": f"A-{secrets.randbelow(9000) + 1000}"},
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{API_BASE}/v1/redirect-sign/sessions",
                json=payload,
                headers={"X-WSign-Api-Key": API_KEY},
            )
    except httpx.HTTPError as ex:
        return HTMLResponse(page_error(f"W.Sign sunucusuna ulaşılamadı: {ex}"))

    if resp.status_code // 100 != 2:
        return HTMLResponse(page_error(f"Oturum oluşturulamadı ({resp.status_code}): {resp.text}"))

    created = resp.json()
    if not created.get("sessionId") or not created.get("redirectUrl"):
        return HTMLResponse(page_error("W.Sign yanıtı beklenmedik biçimde."))

    # nonce'u sessionId ile eşleştir; callback geldiğinde doğrulayacağız.
    sessions[created["sessionId"]] = {
        "nonce": nonce,
        "documentName": document_name,
        "status": "pending",
    }

    # 3D-Secure gibi: kullanıcıyı W.Sign imzalama sayfasına yönlendir.
    return RedirectResponse(created["redirectUrl"], status_code=302)


# ---------------------------------------------------------------------------
# 3) Callback: HMAC + nonce doğrula, imzalı belgeyi sakla
# ---------------------------------------------------------------------------
@app.post("/wsign/callback")
async def callback(request: Request):
    # KRİTİK: HMAC ham gövde üzerinde hesaplanır — önce oku, sonra parse et.
    raw_body = await request.body()
    sig_header = request.headers.get("X-WSign-Signature", "")

    if not verify_hmac(raw_body, sig_header, CALLBACK_SECRET):
        return JSONResponse({"error": "invalid_signature"}, status_code=401)

    try:
        cb = json.loads(raw_body)
    except ValueError:
        return JSONResponse({"error": "invalid_body"}, status_code=400)

    session_id = cb.get("sessionId")
    if not session_id:
        return JSONResponse({"error": "invalid_body"}, status_code=400)

    rec = sessions.get(session_id)
    if rec is None:
        return JSONResponse({"error": "unknown_session"}, status_code=404)

    # nonce doğrulaması: callback gerçekten bizim başlattığımız oturuma ait mi?
    if not hmac.compare_digest(rec["nonce"], cb.get("nonce", "")):
        return JSONResponse({"error": "nonce_mismatch"}, status_code=401)

    rec["status"] = cb.get("status", "unknown")
    rec["signedContentBase64"] = cb.get("signedContentBase64")
    rec["signerCertificateBase64"] = cb.get("signerCertificateBase64")
    rec["completedAt"] = cb.get("completedAt")

    return JSONResponse({"received": True})


# ---------------------------------------------------------------------------
# 4) Sonuç sayfası (successRedirectUrl)
# ---------------------------------------------------------------------------
@app.get("/imza/tamam", response_class=HTMLResponse)
def result(session: str = ""):
    rec = sessions.get(session)
    if rec is None:
        return HTMLResponse(page_error("Oturum bulunamadı."))
    return HTMLResponse(page_result(session, rec))


@app.get("/imza/iptal", response_class=HTMLResponse)
def cancelled() -> str:
    return page_error("İmza iptal edildi.")


# ===========================================================================
# Yardımcılar
# ===========================================================================

# HMAC-SHA256, sabit-zamanlı karşılaştırma. Başlık biçimi: "sha256=<hex>".
def verify_hmac(raw_body: bytes, signature_header: str, secret: bytes) -> bool:
    if not signature_header.startswith("sha256="):
        return False
    provided_hex = signature_header[len("sha256="):]
    computed_hex = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_hex, provided_hex)


# ===========================================================================
# Kullanıcıya görünen HTML (Türkçe). Üretimde bir şablon motoru kullanın.
# ===========================================================================

HEAD = """
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Örnek Belediye — W.Sign Demo</title>
    <style>
      body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;color:#1a1a1a}
      h1{font-size:1.4rem} textarea{width:100%;min-height:160px;font:inherit;padding:8px}
      button{background:#e34234;color:#fff;border:0;padding:10px 18px;border-radius:6px;font-size:1rem;cursor:pointer}
      .box{background:#f6f6f6;border-radius:8px;padding:16px;margin:16px 0;word-break:break-all}
      .ok{color:#0a7d28;font-weight:600} .err{color:#b00020;font-weight:600}
      code{background:#eee;padding:2px 4px;border-radius:4px}
    </style>
"""


def page_form() -> str:
    return f"""<!doctype html><html lang="tr"><head>{HEAD}</head><body>
    <h1>Örnek Belediye — Belge İmzalama</h1>
    <p>Aşağıya imzalanacak belge metnini girin. "İmzala" dediğinizde W.Sign
    imzalama sayfasına (3D-Secure gibi) yönlendirileceksiniz.</p>
    <form method="post" action="/sign">
      <textarea name="belgeMetni" placeholder="Belge metni...">Örnek Belediye resmi yazısı. Bu belge W.Sign ile elektronik imzalanacaktır.</textarea>
      <p><button type="submit">İmzala</button></p>
    </form>
    </body></html>"""


def page_result(session_id: str, rec: dict) -> str:
    from html import escape

    status = rec.get("status", "unknown")
    status_class = "ok" if status == "completed" else "err"
    signed_raw = rec.get("signedContentBase64") or ""
    if signed_raw:
        trunc = signed_raw[:120] + "…" if len(signed_raw) > 120 else signed_raw
        signed = f'<div class="box"><b>İmzalı içerik (DER CMS, base64):</b><br>{escape(trunc)}</div>'
    else:
        signed = "<p>Henüz imzalı içerik alınmadı (callback bekleniyor olabilir).</p>"
    return f"""<!doctype html><html lang="tr"><head>{HEAD}</head><body>
    <h1>İmza Sonucu</h1>
    <p>Oturum: <code>{escape(session_id)}</code></p>
    <p>Durum: <span class="{status_class}">{escape(status)}</span></p>
    <p>Belge: {escape(rec.get("documentName", ""))}</p>
    {signed}
    <p><a href="/">← Yeni belge imzala</a></p>
    </body></html>"""


def page_error(message: str) -> str:
    from html import escape

    return f"""<!doctype html><html lang="tr"><head>{HEAD}</head><body>
    <h1 class="err">Hata</h1><p class="err">{escape(message)}</p>
    <p><a href="/">← Geri dön</a></p>
    </body></html>"""
