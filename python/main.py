# ===========================================================================
# W.Sign entegrasyon örneği — FastAPI
#
# Bu dosya, bir entegratör web uygulamasının W.Sign ile e-imza akışını kurmak
# için yazması gereken kodun TAMAMIDIR. Birincil akış "redirect + pull":
# oturum aç -> kullanıcıyı yönlendir -> kullanıcı dönünce sonucu outbound GET ile
# çek (pull). Ek olarak opsiyonel bir callback (push/webhook) "güvenlik ağı"
# vardır; ikisi de aynı idempotent mantığı paylaşır.
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
import ipaddress
import json
import os
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response


# Bağımlılıksız basit .env yükleyici: depo kökündeki ".env"i okur (varsa).
# KEY=VALUE satırları; boş satır ve '#' yorumları atlanır; zaten tanımlı olan
# process env'in ÜZERİNE YAZMAZ → process env > .env > placeholder fallback.
def _load_dotenv() -> None:
    path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key and key not in os.environ:  # process env varsa ezme
                os.environ[key] = val


_load_dotenv()


# --- Yapılandırma: ortam değişkenlerinden (process env veya .env). Hiçbir sır hardcode değil. ---
def env(key: str, fallback: str) -> str:
    v = os.environ.get(key)
    return v if v else fallback


API_BASE = env("WSIGN_API_BASE", "https://api.sign.wsoft.tr").rstrip("/")
API_KEY = env("WSIGN_API_KEY", "demo-REPLACE-ME")
CALLBACK_SECRET = env("WSIGN_CALLBACK_SECRET", "demo-callback-secret-REPLACE-ME").encode()
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "http://localhost:5000").rstrip("/")
# Sonuç teslim modu: "redirect" (vsy; 302 + pull) | "post" (tarayıcı-aracılı
# otomatik-POST teslimi, kapalı sistemler için). Bkz. docs/delivery-modes.md.
RETURN_MODE = env("WSIGN_RETURN_MODE", "redirect")

# Desteklenen imza tipleri (server ile ortak sabit kontrat). "-T" = zaman damgalı.
ALLOWED_PROFILES = ["CAdES-BES", "CAdES-T", "XAdES-BES", "XAdES-T"]


def normalize_profile(value: str | None) -> str:
    """Gelen değeri izin verilen listeyle eşle; tanınmazsa güvenli varsayılan CAdES-BES."""
    for p in ALLOWED_PROFILES:
        if p.casefold() == (value or "").casefold():
            return p
    return "CAdES-BES"


def is_timestamped(profile: str | None) -> bool:
    """Profil zaman damgalı mı? ("-T" ile biter → CAdES-T / XAdES-T)"""
    return bool(profile) and profile.upper().endswith("-T")


# İmza tipi varsayılanı: formda seçim yoksa bu kullanılır. Bkz. docs/signature-profiles.md.
DEFAULT_PROFILE = normalize_profile(env("WSIGN_SIGNATURE_PROFILE", "CAdES-BES"))


def _is_loopback_host(base_url: str) -> bool:
    host = (urlsplit(base_url).hostname or "").lower()
    if host == "":
        return True  # ayrıştırılamadı → güvenli taraf: webhook gönderme
    if host == "localhost" or host.endswith(".localhost") or host == "0.0.0.0":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# Webhook (callbackUrl) yalnızca GERÇEKTEN ulaşılabilir + gerekli olduğunda
# gönderilir. İki durumda hiç gönderilmez:
#   • returnMode=post → kapalı sistem; sonuç tarayıcı-POST'u ile gelir, webhook
#     gereksiz.
#   • PUBLIC_BASE_URL loopback (localhost/127.x/::1/0.0.0.0) → W.Sign bu adrese
#     POST atamaz; backend ayrıca callback'i loopback/SSRF gerekçesiyle reddeder.
# successRedirectUrl HER ZAMAN gönderilir (redirect + post bunu kullanır).
SEND_CALLBACK = RETURN_MODE.lower() != "post" and not _is_loopback_host(PUBLIC_BASE_URL)

app = FastAPI(title="W.Sign entegrasyon örneği")

# --- Basit in-memory oturum deposu (üretimde: veritabanı). ---
sessions: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# 1) Belge oluşturma formu
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def form() -> str:
    return page_form(DEFAULT_PROFILE)


# ---------------------------------------------------------------------------
# 2) "İmzala" -> oturum oluştur -> 302 yönlendir
# ---------------------------------------------------------------------------
@app.post("/sign")
async def sign(belgeMetni: str = Form(""), signatureProfile: str = Form("")):
    text = belgeMetni.strip()
    if not text:
        return HTMLResponse(page_error("Belge metni boş olamaz."), status_code=400)

    document_name = f"OrnekBelediye_Belge_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.txt"

    # İmza tipini formdan al; tanınmazsa env varsayılanına düş. "-T" seçilirse
    # server, entegratörde Kamu SM TSA tanımlı değilse 400 (TSA_NOT_CONFIGURED)
    # döner — aşağıda yakalanır.
    profile = normalize_profile(signatureProfile or DEFAULT_PROFILE)

    # CSRF/replay koruması: rastgele nonce. Callback'te aynen geri gelecek.
    nonce = base64.b64encode(secrets.token_bytes(16)).decode()

    payload = {
        "documentBase64": base64.b64encode(text.encode()).decode(),
        "documentName": document_name,
        "signatureProfile": profile,
        "digestAlgorithm": "SHA256",
        "successRedirectUrl": f"{PUBLIC_BASE_URL}/imza/tamam",
        "cancelRedirectUrl": f"{PUBLIC_BASE_URL}/imza/iptal",
        "nonce": nonce,
        "ttlMinutes": 15,
        "metadata": {"talepNo": f"A-{secrets.randbelow(9000) + 1000}"},
        # Teslim modu. "post" ise W.Sign sonucu successRedirectUrl'e tarayıcı
        # otomatik-POST formu ile gönderir (kapalı sistem); "redirect" ise 302
        # döndürür ve sonucu biz pull ederiz.
        "returnMode": RETURN_MODE,
    }

    # Webhook güvenlik ağı yalnızca ulaşılabilir + gerekli olduğunda eklenir
    # (aksi halde callbackUrl hiç gönderilmez; bkz. SEND_CALLBACK).
    if SEND_CALLBACK:
        payload["callbackUrl"] = f"{PUBLIC_BASE_URL}/wsign/callback"

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
        # Zaman damgalı tip (-T) seçildi ama entegratörde Kamu SM TSA tanımlı değil.
        if resp.status_code == 400 and "TSA_NOT_CONFIGURED" in resp.text.upper():
            return HTMLResponse(page_error(
                "Zaman damgalı imza (CAdES-T/XAdES-T) için entegratörde Kamu SM TSA "
                "tanımlayın veya damgasız (BES) bir tip seçin."
            ))
        return HTMLResponse(page_error(f"Oturum oluşturulamadı ({resp.status_code}): {resp.text}"))

    created = resp.json()
    if not created.get("sessionId") or not created.get("redirectUrl"):
        return HTMLResponse(page_error("W.Sign yanıtı beklenmedik biçimde."))

    # nonce'u sessionId ile eşleştir; callback geldiğinde doğrulayacağız.
    # Talep edilen imza tipini de saklarız (sonuç sayfasında göstermek için;
    # sonuç/callback server'ın belirlediği değeri döndürürse onunla güncellenir).
    sessions[created["sessionId"]] = {
        "nonce": nonce,
        "documentName": document_name,
        "status": "pending",
        "signatureProfile": profile,
    }

    # 3D-Secure gibi: kullanıcıyı W.Sign imzalama sayfasına yönlendir.
    return RedirectResponse(created["redirectUrl"], status_code=302)


# ---------------------------------------------------------------------------
# 3) Sonuç sayfası (successRedirectUrl) — BİRİNCİL: pull ile sonucu çek
#
# Kullanıcı imzadan sonra buraya döner. Sonucu W.Sign'dan outbound bir GET ile
# çekeriz (pull). Bu, NAT/localhost arkasından TÜNELSİZ çalışır ve senkron UX
# verir. Pull authed'dir (X-WSign-Api-Key) ve yalnızca oturumu açan entegratör
# sonucu görür (başkasının oturumu -> 404).
# ---------------------------------------------------------------------------
@app.get("/imza/tamam", response_class=HTMLResponse)
async def result(session: str = ""):
    rec = sessions.get(session)
    if rec is None:
        return HTMLResponse(page_error("Oturum bulunamadı."))

    # Henüz tamamlanmadıysa (ya da callback henüz gelmediyse) sonucu pull et.
    if rec.get("status") != "completed":
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{API_BASE}/v1/redirect-sign/sessions/{session}/result",
                    headers={"X-WSign-Api-Key": API_KEY},
                )
            # 404/401 vb. -> henüz bizim sonucumuz yok; sayfayı mevcut durumla göster.
            if resp.status_code // 100 == 2:
                apply_result(rec, resp.json())
        except httpx.HTTPError:
            pass  # pull başarısızsa callback güvenlik ağı devreye girer; yine de göster

    return HTMLResponse(page_result(session, rec))


# ---------------------------------------------------------------------------
# 3b) Sonuç sayfası (successRedirectUrl) — returnMode=post: tarayıcı-aracılı POST
#
# KAPALI SİSTEM için. returnMode "post" ile oturum açıldıysa, kullanıcı imzayı
# bitirince W.Sign sonucu BU adrese tarayıcının otomatik-gönderdiği bir POST
# formu (application/x-www-form-urlencoded) ile teslim eder — backend'in dışarı
# çıkıp pull yapmasına veya inbound webhook almasına gerek kalmadan.
#
# Form alanları: sessionId, status, nonce, metadata, completedAt,
# signedContentBase64, signerCertificateBase64, payload, signature.
# TEK doğruluk kaynağı `payload` (webhook callback gövdesiyle BİREBİR aynı JSON);
# `signature` = "sha256=<hex>" = HMAC-SHA256(hmacSecret, payload) = webhook'taki
# X-WSign-Signature ile aynı. Doğrulama callback ile AYNI (verify_hmac + nonce);
# tek fark imza header'da değil `signature` form alanında, HMAC da `payload`
# form alanının ham metni üzerinde.
# ---------------------------------------------------------------------------
@app.post("/imza/tamam", response_class=HTMLResponse)
async def result_post(request: Request):
    form = await request.form()
    payload = str(form.get("payload") or "")
    signature = str(form.get("signature") or "")
    if not payload:
        return HTMLResponse(page_error("POST teslimatında 'payload' alanı yok."), status_code=400)

    # KRİTİK: HMAC `payload` alanının ham byte'ları üzerinde hesaplanır.
    if not verify_hmac(payload.encode(), signature, CALLBACK_SECRET):
        return HTMLResponse(page_error("İmza doğrulanamadı (HMAC uyuşmuyor)."), status_code=401)

    try:
        cb = json.loads(payload)
    except ValueError:
        return HTMLResponse(page_error("Geçersiz payload JSON."), status_code=400)

    session_id = cb.get("sessionId")
    if not session_id:
        return HTMLResponse(page_error("payload içinde sessionId yok."), status_code=400)

    rec = sessions.get(session_id)
    if rec is None:
        return HTMLResponse(page_error("Oturum bulunamadı."))

    # nonce doğrulaması + idempotent uygulama (pull + callback ile ortak).
    if not apply_result(rec, cb):
        return HTMLResponse(page_error("nonce uyuşmuyor."), status_code=401)

    return HTMLResponse(page_result(session_id, rec))


# ---------------------------------------------------------------------------
# 4) Callback (OPSİYONEL güvenlik ağı / webhook) — push: W.Sign -> entegratör
#
# Pull birincil akıştır. Bu callback, kullanıcı successRedirectUrl'e hiç
# dönmese bile (tarayıcı kapandı, ağ koptu) sonucu güvenilir biçimde almak için
# üretimde önerilir. İnternete açık bir adres (veya tünel) ister. Pull ile
# AYNI idempotent mantığı (apply_result) paylaşır: aynı sonuç iki kez gelse
# sorun olmaz.
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

    # nonce doğrulaması + idempotent uygulama (pull ile ortak).
    if not apply_result(rec, cb):
        return JSONResponse({"error": "nonce_mismatch"}, status_code=401)

    return JSONResponse({"received": True})


# ---------------------------------------------------------------------------
# 5) İmzalı dosyayı indir — saklanan DER CMS'i .p7s olarak sun
# ---------------------------------------------------------------------------
@app.get("/imza/indir")
def download(session: str = ""):
    rec = sessions.get(session)
    if rec is None or not rec.get("signedContentBase64"):
        return HTMLResponse(page_error("İmzalı içerik bulunamadı."), status_code=404)
    data = base64.b64decode(rec["signedContentBase64"])
    base_name = os.path.splitext(rec.get("documentName", "imza"))[0]
    # İndirilen dosyanın MIME ve uzantısı, W.Sign result yanıtından gelen
    # contentType/fileExtension ile belirlenir (imza profiline göre değişir).
    # Alanlar yoksa güvenli fallback: attached CAdES-BES.
    content_type = rec.get("contentType") or "application/pkcs7-mime"
    file_ext = rec.get("fileExtension") or ".p7s"
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{base_name}{file_ext}"'},
    )


@app.get("/imza/iptal", response_class=HTMLResponse)
def cancelled() -> str:
    return page_error("İmza iptal edildi.")


# ===========================================================================
# Yardımcılar
# ===========================================================================

# İmza sonucunu kayda idempotent uygula (pull + callback ortak yardımcısı).
# nonce'u sabit-zamanlı doğrular: sonuç gerçekten bizim oturumumuza mı ait?
# Aynı sonuç ikinci kez gelse de aynı değerleri yazar -> güvenle tekrar edilebilir.
def apply_result(rec: dict, data: dict) -> bool:
    if not hmac.compare_digest(rec.get("nonce", ""), data.get("nonce") or ""):
        return False
    if data.get("status"):
        rec["status"] = data["status"]
    if data.get("signedContentBase64"):
        rec["signedContentBase64"] = data["signedContentBase64"]
    if data.get("signerCertificateBase64"):
        rec["signerCertificateBase64"] = data["signerCertificateBase64"]
    if data.get("completedAt"):
        rec["completedAt"] = data["completedAt"]
    if data.get("contentType"):
        rec["contentType"] = data["contentType"]
    if data.get("fileExtension"):
        rec["fileExtension"] = data["fileExtension"]
    # Server sonucu/callback imza tipini döndürürse onu otoriter kabul et.
    if data.get("signatureProfile"):
        rec["signatureProfile"] = data["signatureProfile"]
    return True


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


def page_form(default_profile: str) -> str:
    options = "\n      ".join(
        f'<option value="{p}"{" selected" if p == default_profile else ""}>{p}</option>'
        for p in ALLOWED_PROFILES
    )
    return f"""<!doctype html><html lang="tr"><head>{HEAD}</head><body>
    <h1>Örnek Belediye — Belge İmzalama</h1>
    <p>Aşağıya imzalanacak belge metnini girin. "İmzala" dediğinizde W.Sign
    imzalama sayfasına (3D-Secure gibi) yönlendirileceksiniz.</p>
    <form method="post" action="/sign">
      <textarea name="belgeMetni" placeholder="Belge metni...">Örnek Belediye resmi yazısı. Bu belge W.Sign ile elektronik imzalanacaktır.</textarea>
      <p>
        <label for="signatureProfile"><b>İmza tipi</b></label><br>
        <select name="signatureProfile" id="signatureProfile">
      {options}
        </select>
        <br><small>-T = zaman damgalı (CAdES-T/XAdES-T); entegratörde Kamu SM TSA tanımlı olmalı.</small>
      </p>
      <p><button type="submit">İmzala</button></p>
    </form>
    </body></html>"""


def page_result(session_id: str, rec: dict) -> str:
    from html import escape

    status = rec.get("status", "unknown")
    status_class = "ok" if status == "completed" else "err"
    # İmza tipi (CAdES/XAdES, BES/-T) + zaman damgalı bilgisi + içerik türü.
    profile = rec.get("signatureProfile") or ""
    file_ext = rec.get("fileExtension") or ".p7s"
    profile_line = (
        f'<p>İmza tipi: <code>{escape(profile)}</code> '
        f'({"zaman damgalı" if is_timestamped(profile) else "damgasız"})</p>'
        if profile else ""
    )
    content_type_line = (
        f'<p>İçerik türü: <code>{escape(rec.get("contentType") or "")}</code></p>'
        if rec.get("contentType") else ""
    )
    signed_raw = rec.get("signedContentBase64") or ""
    if signed_raw:
        trunc = signed_raw[:120] + "…" if len(signed_raw) > 120 else signed_raw
        signed = (
            f'<div class="box"><b>İmzalı içerik (base64):</b><br>{escape(trunc)}</div>'
            f'<p><a href="/imza/indir?session={escape(session_id)}">'
            f'<button type="button">İmzalı dosyayı indir ({escape(file_ext)})</button></a></p>'
        )
    else:
        signed = "<p>Henüz imzalı içerik alınmadı (callback bekleniyor olabilir).</p>"
    return f"""<!doctype html><html lang="tr"><head>{HEAD}</head><body>
    <h1>İmza Sonucu</h1>
    <p>Oturum: <code>{escape(session_id)}</code></p>
    <p>Durum: <span class="{status_class}">{escape(status)}</span></p>
    <p>Belge: {escape(rec.get("documentName", ""))}</p>
    {profile_line}
    {content_type_line}
    {signed}
    <p><a href="/">← Yeni belge imzala</a></p>
    </body></html>"""


def page_error(message: str) -> str:
    from html import escape

    return f"""<!doctype html><html lang="tr"><head>{HEAD}</head><body>
    <h1 class="err">Hata</h1><p class="err">{escape(message)}</p>
    <p><a href="/">← Geri dön</a></p>
    </body></html>"""
