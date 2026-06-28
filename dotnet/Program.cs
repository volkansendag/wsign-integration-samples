// ===========================================================================
// W.Sign entegrasyon örneği — ASP.NET Core minimal API
//
// Bu dosya, bir entegratör web uygulamasının W.Sign ile e-imza akışını kurmak
// için yazması gereken kodun TAMAMIDIR. Birincil akış "redirect + pull":
// oturum aç → kullanıcıyı yönlendir → kullanıcı dönünce sonucu outbound GET ile
// çek (pull). Ek olarak opsiyonel bir callback (push/webhook) "güvenlik ağı"
// vardır; ikisi de aynı idempotent mantığı paylaşır.
//
// W.Sign'ın içselleri (CMS üretimi, PKCS#11, sertifika, oturum durum makinesi)
// sunucu tarafında kapalıdır. Entegrasyon yalnızca REST + HMAC üzerindendir.
//
// Senaryo: kurgusal "Örnek Belediye" bir belge metni üretir ve imzalatır.
// ===========================================================================

using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

// Kök .env dosyasını (varsa) ortam değişkenlerine yükle. Zaten tanımlı olan
// process env'i EZMEZ → process env > .env > placeholder fallback önceliği.
LoadDotEnv();

// --- Yapılandırma: ortam değişkenlerinden (process env veya .env). Hiçbir sır hardcode değil. ---
string ApiBase()        => Env("WSIGN_API_BASE", "https://api.sign.wsoft.tr");
string ApiKey()         => Env("WSIGN_API_KEY", "demo-REPLACE-ME");
string CallbackSecret() => Env("WSIGN_CALLBACK_SECRET", "demo-callback-secret-REPLACE-ME");
string PublicBaseUrl()  => Env("PUBLIC_BASE_URL", "http://localhost:5000").TrimEnd('/');

static string Env(string key, string fallback) =>
    Environment.GetEnvironmentVariable(key) is { Length: > 0 } v ? v : fallback;

// Bağımlılıksız basit .env yükleyici: çalışma dizininden yukarı doğru ilk
// bulunan ".env"i okur. KEY=VALUE satırları; boş satır ve '#' yorumları atlanır;
// zaten set olan ortam değişkeninin ÜZERİNE YAZMAZ.
static void LoadDotEnv()
{
    for (var dir = new DirectoryInfo(Directory.GetCurrentDirectory()); dir is not null; dir = dir.Parent)
    {
        var path = Path.Combine(dir.FullName, ".env");
        if (!File.Exists(path)) continue;

        foreach (var raw in File.ReadAllLines(path))
        {
            var line = raw.Trim();
            if (line.Length == 0 || line[0] == '#') continue;
            var eq = line.IndexOf('=');
            if (eq <= 0) continue;
            var key = line[..eq].Trim();
            var val = line[(eq + 1)..].Trim();
            if (key.Length == 0) continue;
            // process env varsa ezme (öncelik process env'de).
            if (Environment.GetEnvironmentVariable(key) is { Length: > 0 }) continue;
            Environment.SetEnvironmentVariable(key, val);
        }
        return; // ilk .env bulundu, dur.
    }
}

// --- Basit in-memory oturum deposu (üretimde: veritabanı). ---
var sessions = new ConcurrentDictionary<string, SessionRecord>();

var http = new HttpClient();
var jsonOpts = new JsonSerializerOptions
{
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
};

// ---------------------------------------------------------------------------
// 1) Belge oluşturma formu
// ---------------------------------------------------------------------------
app.MapGet("/", () => Results.Content(Pages.Form(), "text/html; charset=utf-8"));

// ---------------------------------------------------------------------------
// 2) "İmzala" → oturum oluştur → 302 yönlendir
// ---------------------------------------------------------------------------
app.MapPost("/sign", async (HttpRequest req) =>
{
    var form = await req.ReadFormAsync();
    var text = form["belgeMetni"].ToString();
    if (string.IsNullOrWhiteSpace(text))
        return Results.BadRequest("Belge metni boş olamaz.");

    var documentName = $"OrnekBelediye_Belge_{DateTime.UtcNow:yyyyMMdd_HHmmss}.txt";

    // CSRF/replay koruması: rastgele nonce. Callback'te aynen geri gelecek.
    var nonce = Convert.ToBase64String(RandomNumberGenerator.GetBytes(16));

    var payload = new
    {
        documentBase64 = Convert.ToBase64String(Encoding.UTF8.GetBytes(text)),
        documentName,
        signatureProfile = "CAdES-BES",
        digestAlgorithm = "SHA256",
        callbackUrl = $"{PublicBaseUrl()}/wsign/callback",
        successRedirectUrl = $"{PublicBaseUrl()}/imza/tamam",
        cancelRedirectUrl = $"{PublicBaseUrl()}/imza/iptal",
        nonce,
        ttlMinutes = 15,
        metadata = new { talepNo = $"A-{Random.Shared.Next(1000, 9999)}" },
    };

    using var msg = new HttpRequestMessage(HttpMethod.Post, $"{ApiBase()}/v1/redirect-sign/sessions");
    msg.Headers.Add("X-WSign-Api-Key", ApiKey());
    msg.Content = new StringContent(JsonSerializer.Serialize(payload, jsonOpts), Encoding.UTF8, "application/json");

    HttpResponseMessage resp;
    try { resp = await http.SendAsync(msg); }
    catch (Exception ex) { return Results.Content(Pages.Error($"W.Sign sunucusuna ulaşılamadı: {ex.Message}"), "text/html; charset=utf-8"); }

    if (!resp.IsSuccessStatusCode)
    {
        var body = await resp.Content.ReadAsStringAsync();
        return Results.Content(Pages.Error($"Oturum oluşturulamadı ({(int)resp.StatusCode}): {body}"), "text/html; charset=utf-8");
    }

    var created = await resp.Content.ReadFromJsonAsync<CreateSessionResponse>(jsonOpts);
    if (created is null || string.IsNullOrEmpty(created.SessionId) || string.IsNullOrEmpty(created.RedirectUrl))
        return Results.Content(Pages.Error("W.Sign yanıtı beklenmedik biçimde."), "text/html; charset=utf-8");

    // nonce'u sessionId ile eşleştir; callback geldiğinde doğrulayacağız.
    sessions[created.SessionId] = new SessionRecord { Nonce = nonce, DocumentName = documentName, Status = "pending" };

    // 3D-Secure gibi: kullanıcıyı W.Sign imzalama sayfasına yönlendir.
    return Results.Redirect(created.RedirectUrl);
});

// ---------------------------------------------------------------------------
// 3) Sonuç sayfası (successRedirectUrl) — BİRİNCİL: pull ile sonucu çek
//
// Kullanıcı imzadan sonra buraya döner. Sonucu W.Sign'dan outbound bir GET ile
// çekeriz (pull). Bu, NAT/localhost arkasından TÜNELSİZ çalışır ve senkron UX
// verir. Pull authed'dir (X-WSign-Api-Key) ve yalnızca oturumu açan entegratör
// sonucu görür (başkasının oturumu → 404).
// ---------------------------------------------------------------------------
app.MapGet("/imza/tamam", async (string? session) =>
{
    if (string.IsNullOrEmpty(session) || !sessions.TryGetValue(session, out var rec))
        return Results.Content(Pages.Error("Oturum bulunamadı."), "text/html; charset=utf-8");

    // Henüz tamamlanmadıysa (ya da callback henüz gelmediyse) sonucu pull et.
    if (rec.Status != "completed")
    {
        try
        {
            using var msg = new HttpRequestMessage(
                HttpMethod.Get, $"{ApiBase()}/v1/redirect-sign/sessions/{session}/result");
            msg.Headers.Add("X-WSign-Api-Key", ApiKey());
            var resp = await http.SendAsync(msg);
            if (resp.IsSuccessStatusCode)
            {
                var result = await resp.Content.ReadFromJsonAsync<ResultResponse>(jsonOpts);
                if (result is not null)
                    ApplyResult(rec, result.Status, result.Nonce,
                        result.SignedContentBase64, result.SignerCertificateBase64, result.CompletedAt,
                        result.ContentType, result.FileExtension);
            }
            // 404/401 vb. → henüz bizim sonucumuz yok; sayfayı mevcut durumla göster.
        }
        catch { /* pull başarısızsa callback güvenlik ağı devreye girer; yine de göster */ }
    }

    return Results.Content(Pages.Result(session, rec), "text/html; charset=utf-8");
});

// ---------------------------------------------------------------------------
// 4) Callback (OPSİYONEL güvenlik ağı / webhook) — push: W.Sign → entegratör
//
// Pull birincil akıştır. Bu callback, kullanıcı successRedirectUrl'e hiç
// dönmese bile (tarayıcı kapandı, ağ koptu) sonucu güvenilir biçimde almak için
// üretimde önerilir. İnternete açık bir adres (veya tünel) ister. Pull ile
// AYNI idempotent mantığı paylaşır: aynı sonuç iki kez gelse sorun olmaz.
// ---------------------------------------------------------------------------
app.MapPost("/wsign/callback", async (HttpRequest req) =>
{
    // KRİTİK: HMAC ham gövde üzerinde hesaplanır — önce oku, sonra parse et.
    using var reader = new StreamReader(req.Body, Encoding.UTF8);
    var rawBody = await reader.ReadToEndAsync();
    var rawBytes = Encoding.UTF8.GetBytes(rawBody);

    var sigHeader = req.Headers["X-WSign-Signature"].ToString();
    if (!VerifyHmac(rawBytes, sigHeader, Encoding.UTF8.GetBytes(CallbackSecret())))
        return Results.Unauthorized();

    CallbackBody? cb;
    try { cb = JsonSerializer.Deserialize<CallbackBody>(rawBody, jsonOpts); }
    catch { return Results.BadRequest("Geçersiz JSON."); }
    if (cb is null || string.IsNullOrEmpty(cb.SessionId))
        return Results.BadRequest("Eksik sessionId.");

    if (!sessions.TryGetValue(cb.SessionId, out var rec))
        return Results.NotFound("Bilinmeyen oturum.");

    // nonce doğrulaması + idempotent uygulama (pull ile ortak).
    if (!ApplyResult(rec, cb.Status, cb.Nonce, cb.SignedContentBase64, cb.SignerCertificateBase64, cb.CompletedAt,
            cb.ContentType, cb.FileExtension))
        return Results.Unauthorized();

    return Results.Ok(new { received = true });
});

// ---------------------------------------------------------------------------
// 5) İmzalı dosyayı indir — saklanan DER CMS'i .p7s olarak sun
// ---------------------------------------------------------------------------
app.MapGet("/imza/indir", (string? session) =>
{
    if (string.IsNullOrEmpty(session) || !sessions.TryGetValue(session, out var rec)
        || string.IsNullOrEmpty(rec.SignedContentBase64))
        return Results.NotFound("İmzalı içerik bulunamadı.");

    var bytes    = Convert.FromBase64String(rec.SignedContentBase64);
    var baseName = Path.GetFileNameWithoutExtension(rec.DocumentName);
    // İndirilen dosyanın MIME ve uzantısı, W.Sign result yanıtından gelen
    // contentType/fileExtension ile belirlenir (imza profiline göre değişir:
    // CAdES → application/pkcs7-mime/.p7s, PAdES → application/pdf/.pdf vb.).
    // Alanlar yoksa güvenli fallback: attached CAdES-BES.
    var contentType = string.IsNullOrEmpty(rec.ContentType) ? "application/pkcs7-mime" : rec.ContentType;
    var fileExt     = string.IsNullOrEmpty(rec.FileExtension) ? ".p7s" : rec.FileExtension;
    return Results.File(bytes, contentType, $"{baseName}{fileExt}");
});

app.MapGet("/imza/iptal", () => Results.Content(Pages.Error("İmza iptal edildi."), "text/html; charset=utf-8"));

app.Run();

// ===========================================================================
// Yardımcılar
// ===========================================================================

// İmza sonucunu kayda idempotent uygula (pull + callback ortak yardımcısı).
// nonce'u sabit-zamanlı doğrular: sonuç gerçekten bizim oturumumuza mı ait?
// Aynı sonuç ikinci kez gelse de aynı değerleri yazar → güvenle tekrar edilebilir.
static bool ApplyResult(SessionRecord rec, string? status, string? nonce,
    string? signedContentBase64, string? signerCertificateBase64, string? completedAt,
    string? contentType, string? fileExtension)
{
    if (!FixedTimeEquals(nonce ?? "", rec.Nonce))
        return false;
    if (!string.IsNullOrEmpty(status)) rec.Status = status;
    if (!string.IsNullOrEmpty(signedContentBase64)) rec.SignedContentBase64 = signedContentBase64;
    if (!string.IsNullOrEmpty(signerCertificateBase64)) rec.SignerCertificateBase64 = signerCertificateBase64;
    if (!string.IsNullOrEmpty(completedAt)) rec.CompletedAt = completedAt;
    if (!string.IsNullOrEmpty(contentType)) rec.ContentType = contentType;
    if (!string.IsNullOrEmpty(fileExtension)) rec.FileExtension = fileExtension;
    return true;
}

// HMAC-SHA256, sabit-zamanlı karşılaştırma. Başlık biçimi: "sha256=<hex>".
static bool VerifyHmac(byte[] rawBody, string signatureHeader, byte[] secret)
{
    if (string.IsNullOrEmpty(signatureHeader) ||
        !signatureHeader.StartsWith("sha256=", StringComparison.Ordinal))
        return false;

    var providedHex = signatureHeader["sha256=".Length..];
    var computedHex = Convert.ToHexString(HMACSHA256.HashData(secret, rawBody)).ToLowerInvariant();
    return FixedTimeEquals(computedHex, providedHex);
}

static bool FixedTimeEquals(string a, string b)
{
    var ba = Encoding.ASCII.GetBytes(a);
    var bb = Encoding.ASCII.GetBytes(b);
    return ba.Length == bb.Length && CryptographicOperations.FixedTimeEquals(ba, bb);
}

// ===========================================================================
// Tipler
// ===========================================================================

sealed class SessionRecord
{
    public string Nonce { get; set; } = "";
    public string DocumentName { get; set; } = "";
    public string Status { get; set; } = "pending";
    public string? SignedContentBase64 { get; set; }
    public string? SignerCertificateBase64 { get; set; }
    public string? CompletedAt { get; set; }
    public string? ContentType { get; set; }   // result'tan: imzalı dosyanın MIME'ı
    public string? FileExtension { get; set; }  // result'tan: imzalı dosyanın uzantısı
}

sealed class CreateSessionResponse
{
    public string? SessionId { get; set; }
    public string? RedirectUrl { get; set; }
    public string? ExpiresAt { get; set; }
    public string? Status { get; set; }
}

sealed class CallbackBody
{
    public string? SessionId { get; set; }
    public string? Status { get; set; }
    public string? Nonce { get; set; }
    public string? SignedContentBase64 { get; set; }
    public string? SignerCertificateBase64 { get; set; }
    public string? CompletedAt { get; set; }
    public string? ContentType { get; set; }
    public string? FileExtension { get; set; }
    public string? ErrorReason { get; set; }
}

// GET /v1/redirect-sign/sessions/{id}/result yanıtı (pull).
sealed class ResultResponse
{
    public string? SessionId { get; set; }
    public string? Status { get; set; }
    public string? Nonce { get; set; }
    public string? SignedContentBase64 { get; set; }
    public string? SignerCertificateBase64 { get; set; }
    public string? CompletedAt { get; set; }
    public string? ContentType { get; set; }   // imzalı dosyanın MIME'ı (örn. application/pkcs7-mime)
    public string? FileExtension { get; set; }  // imzalı dosyanın uzantısı (örn. .p7s)
}

// ===========================================================================
// Kullanıcıya görünen HTML (Türkçe). Üretimde Razor/şablon kullanın.
// ===========================================================================

static class Pages
{
    const string Head = """
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
        """;

    public static string Form() => $"""
        <!doctype html><html lang="tr"><head>{Head}</head><body>
        <h1>Örnek Belediye — Belge İmzalama</h1>
        <p>Aşağıya imzalanacak belge metnini girin. "İmzala" dediğinizde W.Sign
        imzalama sayfasına (3D-Secure gibi) yönlendirileceksiniz.</p>
        <form method="post" action="/sign">
          <textarea name="belgeMetni" placeholder="Belge metni...">Örnek Belediye resmi yazısı. Bu belge W.Sign ile elektronik imzalanacaktır.</textarea>
          <p><button type="submit">İmzala</button></p>
        </form>
        </body></html>
        """;

    public static string Result(string sessionId, SessionRecord rec)
    {
        var statusClass = rec.Status == "completed" ? "ok" : "err";
        var signed = rec.SignedContentBase64 is { Length: > 0 }
            ? $"""
               <div class="box"><b>İmzalı içerik (DER CMS, base64):</b><br>{Trunc(rec.SignedContentBase64)}</div>
               <p><a href="/imza/indir?session={sessionId}"><button type="button">İmzalı dosyayı indir (.p7s)</button></a></p>
               """
            : "<p>Henüz imzalı içerik alınmadı (callback bekleniyor olabilir).</p>";
        return $"""
            <!doctype html><html lang="tr"><head>{Head}</head><body>
            <h1>İmza Sonucu</h1>
            <p>Oturum: <code>{sessionId}</code></p>
            <p>Durum: <span class="{statusClass}">{rec.Status}</span></p>
            <p>Belge: {rec.DocumentName}</p>
            {signed}
            <p><a href="/">← Yeni belge imzala</a></p>
            </body></html>
            """;
    }

    public static string Error(string message) => $"""
        <!doctype html><html lang="tr"><head>{Head}</head><body>
        <h1 class="err">Hata</h1><p class="err">{message}</p>
        <p><a href="/">← Geri dön</a></p>
        </body></html>
        """;

    static string Trunc(string s) => s.Length > 120 ? s[..120] + "…" : s;
}
