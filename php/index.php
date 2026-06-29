<?php
// ===========================================================================
// W.Sign entegrasyon örneği — saf PHP (framework yok)
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
//
// Çalıştırma (kök .env dosyasını doldurduktan sonra):
//   cd php && php -S localhost:8080 index.php
// ===========================================================================

declare(strict_types=1);

$cfg = require __DIR__ . '/config.php';
@mkdir($cfg['storage_dir'], 0700, true);

$path   = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

// --- Basit dosya tabanlı oturum deposu (üretimde: veritabanı). ---
function store_path(array $cfg, string $sessionId): string
{
    // Path traversal'a karşı sessionId'yi dosya adına gömmeden hash'le.
    return $cfg['storage_dir'] . '/' . hash('sha256', $sessionId) . '.json';
}
function store_save(array $cfg, string $sessionId, array $rec): void
{
    file_put_contents(store_path($cfg, $sessionId), json_encode($rec));
}
function store_load(array $cfg, string $sessionId): ?array
{
    $p = store_path($cfg, $sessionId);
    return is_file($p) ? json_decode((string) file_get_contents($p), true) : null;
}

// --- Yönlendirici ---
if ($method === 'GET' && $path === '/') {
    echo page_form();
} elseif ($method === 'POST' && $path === '/sign') {
    handle_sign($cfg);
} elseif ($method === 'POST' && $path === '/wsign/callback') {
    handle_callback($cfg);
} elseif ($method === 'GET' && $path === '/imza/tamam') {
    handle_result($cfg);
} elseif ($method === 'POST' && $path === '/imza/tamam') {
    handle_result_post($cfg);
} elseif ($method === 'GET' && $path === '/imza/indir') {
    handle_download($cfg);
} elseif ($method === 'GET' && $path === '/imza/iptal') {
    echo page_error('İmza iptal edildi.');
} else {
    http_response_code(404);
    echo page_error('Sayfa bulunamadı.');
}

// ---------------------------------------------------------------------------
// 2) "İmzala" → oturum oluştur → 302 yönlendir
// ---------------------------------------------------------------------------
function handle_sign(array $cfg): void
{
    $text = trim($_POST['belgeMetni'] ?? '');
    if ($text === '') {
        http_response_code(400);
        echo page_error('Belge metni boş olamaz.');
        return;
    }

    $documentName = 'OrnekBelediye_Belge_' . gmdate('Ymd_His') . '.txt';

    // CSRF/replay koruması: rastgele nonce. Callback'te aynen geri gelecek.
    $nonce = base64_encode(random_bytes(16));

    $payload = [
        'documentBase64'     => base64_encode($text),
        'documentName'       => $documentName,
        'signatureProfile'   => 'CAdES-BES',
        'digestAlgorithm'    => 'SHA256',
        'callbackUrl'        => $cfg['public_base_url'] . '/wsign/callback',
        'successRedirectUrl' => $cfg['public_base_url'] . '/imza/tamam',
        'cancelRedirectUrl'  => $cfg['public_base_url'] . '/imza/iptal',
        'nonce'              => $nonce,
        'ttlMinutes'         => 15,
        'metadata'           => ['talepNo' => 'A-' . random_int(1000, 9999)],
        // Teslim modu. "post" ise W.Sign sonucu successRedirectUrl'e tarayıcı
        // otomatik-POST formu ile gönderir (kapalı sistem); "redirect" ise 302
        // döndürür ve sonucu biz pull ederiz.
        'returnMode'         => $cfg['return_mode'],
    ];

    [$status, $body] = http_post_json(
        $cfg['api_base'] . '/v1/redirect-sign/sessions',
        json_encode($payload),
        ['X-WSign-Api-Key: ' . $cfg['api_key']]
    );

    if ($status < 200 || $status >= 300) {
        echo page_error("Oturum oluşturulamadı ($status): " . htmlspecialchars((string) $body));
        return;
    }

    $created = json_decode((string) $body, true);
    if (!is_array($created) || empty($created['sessionId']) || empty($created['redirectUrl'])) {
        echo page_error('W.Sign yanıtı beklenmedik biçimde.');
        return;
    }

    // nonce'u sessionId ile eşleştir; callback geldiğinde doğrulayacağız.
    store_save($cfg, $created['sessionId'], [
        'nonce'        => $nonce,
        'documentName' => $documentName,
        'status'       => 'pending',
    ]);

    // 3D-Secure gibi: kullanıcıyı W.Sign imzalama sayfasına yönlendir.
    header('Location: ' . $created['redirectUrl'], true, 302);
}

// ---------------------------------------------------------------------------
// 3) Sonuç sayfası (successRedirectUrl) — BİRİNCİL: pull ile sonucu çek
//
// Kullanıcı imzadan sonra buraya döner. Sonucu W.Sign'dan outbound bir GET ile
// çekeriz (pull). Bu, NAT/localhost arkasından TÜNELSİZ çalışır ve senkron UX
// verir. Pull authed'dir (X-WSign-Api-Key) ve yalnızca oturumu açan entegratör
// sonucu görür (başkasının oturumu → 404).
// ---------------------------------------------------------------------------
function handle_result(array $cfg): void
{
    $sessionId = $_GET['session'] ?? '';
    $rec = $sessionId !== '' ? store_load($cfg, $sessionId) : null;
    if ($rec === null) {
        echo page_error('Oturum bulunamadı.');
        return;
    }

    // Henüz tamamlanmadıysa (ya da callback henüz gelmediyse) sonucu pull et.
    if (($rec['status'] ?? '') !== 'completed') {
        [$status, $body] = http_get_json(
            $cfg['api_base'] . '/v1/redirect-sign/sessions/' . rawurlencode($sessionId) . '/result',
            ['X-WSign-Api-Key: ' . $cfg['api_key']]
        );
        // 404/401 vb. → henüz bizim sonucumuz yok; sayfayı mevcut durumla göster.
        if ($status >= 200 && $status < 300) {
            $result = json_decode((string) $body, true);
            if (is_array($result) && apply_result($rec, $result)) {
                store_save($cfg, $sessionId, $rec);
            }
        }
    }

    echo page_result($sessionId, $rec);
}

// ---------------------------------------------------------------------------
// 3b) Sonuç sayfası (successRedirectUrl) — returnMode=post: tarayıcı-aracılı POST
//
// KAPALI SİSTEM için. returnMode "post" ile oturum açıldıysa, kullanıcı imzayı
// bitirince W.Sign sonucu BU adrese tarayıcının otomatik-gönderdiği bir POST
// formu (application/x-www-form-urlencoded) ile teslim eder — backend'in dışarı
// çıkıp pull yapmasına veya inbound webhook almasına gerek kalmadan.
//
// Form alanları: sessionId, status, nonce, metadata, completedAt,
// signedContentBase64, signerCertificateBase64, payload, signature.
// TEK doğruluk kaynağı `payload` (webhook callback gövdesiyle BİREBİR aynı JSON);
// `signature` = "sha256=<hex>" = HMAC-SHA256(hmacSecret, payload) = webhook'taki
// X-WSign-Signature ile aynı. Doğrulama callback ile AYNI (verify_hmac + nonce);
// tek fark imza header'da değil `signature` form alanında, HMAC da `payload`
// form alanının ham metni üzerinde.
// ---------------------------------------------------------------------------
function handle_result_post(array $cfg): void
{
    $payload   = $_POST['payload'] ?? '';
    $signature = $_POST['signature'] ?? '';
    if ($payload === '') {
        http_response_code(400);
        echo page_error("POST teslimatında 'payload' alanı yok.");
        return;
    }

    // KRİTİK: HMAC `payload` alanının ham metni üzerinde hesaplanır.
    if (!verify_hmac((string) $payload, (string) $signature, $cfg['callback_secret'])) {
        http_response_code(401);
        echo page_error('İmza doğrulanamadı (HMAC uyuşmuyor).');
        return;
    }

    $cb = json_decode((string) $payload, true);
    if (!is_array($cb) || empty($cb['sessionId'])) {
        http_response_code(400);
        echo page_error('payload içinde sessionId yok.');
        return;
    }

    $rec = store_load($cfg, $cb['sessionId']);
    if ($rec === null) {
        echo page_error('Oturum bulunamadı.');
        return;
    }

    // nonce doğrulaması + idempotent uygulama (pull + callback ile ortak).
    if (!apply_result($rec, $cb)) {
        http_response_code(401);
        echo page_error('nonce uyuşmuyor.');
        return;
    }
    store_save($cfg, $cb['sessionId'], $rec);

    echo page_result($cb['sessionId'], $rec);
}

// ---------------------------------------------------------------------------
// 5) İmzalı dosyayı indir — saklanan DER CMS'i .p7s olarak sun
// ---------------------------------------------------------------------------
function handle_download(array $cfg): void
{
    $sessionId = $_GET['session'] ?? '';
    $rec = $sessionId !== '' ? store_load($cfg, $sessionId) : null;
    if ($rec === null || empty($rec['signedContentBase64'])) {
        http_response_code(404);
        echo page_error('İmzalı içerik bulunamadı.');
        return;
    }
    $bytes    = base64_decode((string) $rec['signedContentBase64']);
    $baseName = pathinfo($rec['documentName'] ?? 'imza', PATHINFO_FILENAME);
    // İndirilen dosyanın MIME ve uzantısı, W.Sign result yanıtından gelen
    // contentType/fileExtension ile belirlenir (imza profiline göre değişir).
    // Alanlar yoksa güvenli fallback: attached CAdES-BES.
    $contentType = !empty($rec['contentType'])   ? (string) $rec['contentType']   : 'application/pkcs7-mime';
    $fileExt     = !empty($rec['fileExtension']) ? (string) $rec['fileExtension'] : '.p7s';
    header('Content-Type: ' . $contentType);
    header('Content-Disposition: attachment; filename="' . $baseName . $fileExt . '"');
    header('Content-Length: ' . strlen($bytes));
    echo $bytes;
}

// ---------------------------------------------------------------------------
// 4) Callback (OPSİYONEL güvenlik ağı / webhook) — push: W.Sign → entegratör
//
// Pull birincil akıştır. Bu callback, kullanıcı successRedirectUrl'e hiç
// dönmese bile (tarayıcı kapandı, ağ koptu) sonucu güvenilir biçimde almak için
// üretimde önerilir. İnternete açık bir adres (veya tünel) ister. Pull ile
// AYNI idempotent mantığı (apply_result) paylaşır: aynı sonuç iki kez gelse
// sorun olmaz.
// ---------------------------------------------------------------------------
function handle_callback(array $cfg): void
{
    // KRİTİK: HMAC ham gövde üzerinde hesaplanır — önce oku, sonra parse et.
    $rawBody   = file_get_contents('php://input') ?: '';
    $sigHeader = $_SERVER['HTTP_X_WSIGN_SIGNATURE'] ?? '';

    if (!verify_hmac($rawBody, $sigHeader, $cfg['callback_secret'])) {
        http_response_code(401);
        echo json_encode(['error' => 'invalid_signature']);
        return;
    }

    $cb = json_decode($rawBody, true);
    if (!is_array($cb) || empty($cb['sessionId'])) {
        http_response_code(400);
        echo json_encode(['error' => 'invalid_body']);
        return;
    }

    $rec = store_load($cfg, $cb['sessionId']);
    if ($rec === null) {
        http_response_code(404);
        echo json_encode(['error' => 'unknown_session']);
        return;
    }

    // nonce doğrulaması + idempotent uygulama (pull ile ortak).
    if (!apply_result($rec, $cb)) {
        http_response_code(401);
        echo json_encode(['error' => 'nonce_mismatch']);
        return;
    }
    store_save($cfg, $cb['sessionId'], $rec);

    http_response_code(200);
    echo json_encode(['received' => true]);
}

// ===========================================================================
// Yardımcılar
// ===========================================================================

// İmza sonucunu kayda idempotent uygula (pull + callback ortak yardımcısı).
// nonce'u sabit-zamanlı doğrular: sonuç gerçekten bizim oturumumuza mı ait?
// Aynı sonuç ikinci kez gelse de aynı değerleri yazar → güvenle tekrar edilebilir.
function apply_result(array &$rec, array $data): bool
{
    if (!hash_equals((string) ($rec['nonce'] ?? ''), (string) ($data['nonce'] ?? ''))) {
        return false;
    }
    if (!empty($data['status']))                  $rec['status'] = $data['status'];
    if (!empty($data['signedContentBase64']))     $rec['signedContentBase64'] = $data['signedContentBase64'];
    if (!empty($data['signerCertificateBase64'])) $rec['signerCertificateBase64'] = $data['signerCertificateBase64'];
    if (!empty($data['completedAt']))             $rec['completedAt'] = $data['completedAt'];
    if (!empty($data['contentType']))             $rec['contentType'] = $data['contentType'];
    if (!empty($data['fileExtension']))           $rec['fileExtension'] = $data['fileExtension'];
    return true;
}

// HMAC-SHA256, sabit-zamanlı karşılaştırma. Başlık biçimi: "sha256=<hex>".
function verify_hmac(string $rawBody, string $signatureHeader, string $secret): bool
{
    if (strncmp($signatureHeader, 'sha256=', 7) !== 0) {
        return false;
    }
    $providedHex = substr($signatureHeader, 7);
    $computedHex = hash_hmac('sha256', $rawBody, $secret);
    return hash_equals($computedHex, $providedHex);
}

/** @return array{0:int,1:string|false} [statusCode, body] */
function http_post_json(string $url, string $json, array $headers): array
{
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => $json,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER     => array_merge(['Content-Type: application/json'], $headers),
        CURLOPT_TIMEOUT        => 30,
    ]);
    $body   = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    if ($body === false) {
        $body = 'cURL hatası: ' . curl_error($ch);
        $status = 0;
    }
    curl_close($ch);
    return [$status, $body];
}

/** @return array{0:int,1:string|false} [statusCode, body] — pull GET için. */
function http_get_json(string $url, array $headers): array
{
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER     => array_merge(['Accept: application/json'], $headers),
        CURLOPT_TIMEOUT        => 30,
    ]);
    $body   = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    if ($body === false) {
        $body = 'cURL hatası: ' . curl_error($ch);
        $status = 0;
    }
    curl_close($ch);
    return [$status, $body];
}

// ===========================================================================
// Kullanıcıya görünen HTML (Türkçe). Üretimde bir şablon motoru kullanın.
// ===========================================================================

function html_head(): string
{
    return <<<HTML
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
    HTML;
}

function page_form(): string
{
    $head = html_head();
    return <<<HTML
    <!doctype html><html lang="tr"><head>{$head}</head><body>
    <h1>Örnek Belediye — Belge İmzalama</h1>
    <p>Aşağıya imzalanacak belge metnini girin. "İmzala" dediğinizde W.Sign
    imzalama sayfasına (3D-Secure gibi) yönlendirileceksiniz.</p>
    <form method="post" action="/sign">
      <textarea name="belgeMetni" placeholder="Belge metni...">Örnek Belediye resmi yazısı. Bu belge W.Sign ile elektronik imzalanacaktır.</textarea>
      <p><button type="submit">İmzala</button></p>
    </form>
    </body></html>
    HTML;
}

function page_result(string $sessionId, array $rec): string
{
    $head        = html_head();
    $sid         = htmlspecialchars($sessionId);
    $status      = htmlspecialchars($rec['status'] ?? 'unknown');
    $statusClass = ($rec['status'] ?? '') === 'completed' ? 'ok' : 'err';
    $docName     = htmlspecialchars($rec['documentName'] ?? '');
    $signedRaw   = $rec['signedContentBase64'] ?? '';
    if ($signedRaw !== '') {
        $trunc  = strlen($signedRaw) > 120 ? substr($signedRaw, 0, 120) . '…' : $signedRaw;
        $signed = '<div class="box"><b>İmzalı içerik (DER CMS, base64):</b><br>' . htmlspecialchars($trunc) . '</div>'
            . '<p><a href="/imza/indir?session=' . rawurlencode($sessionId) . '"><button type="button">İmzalı dosyayı indir (.p7s)</button></a></p>';
    } else {
        $signed = '<p>Henüz imzalı içerik alınmadı (callback bekleniyor olabilir).</p>';
    }
    return <<<HTML
    <!doctype html><html lang="tr"><head>{$head}</head><body>
    <h1>İmza Sonucu</h1>
    <p>Oturum: <code>{$sid}</code></p>
    <p>Durum: <span class="{$statusClass}">{$status}</span></p>
    <p>Belge: {$docName}</p>
    {$signed}
    <p><a href="/">← Yeni belge imzala</a></p>
    </body></html>
    HTML;
}

function page_error(string $message): string
{
    $head = html_head();
    $msg  = htmlspecialchars($message);
    return <<<HTML
    <!doctype html><html lang="tr"><head>{$head}</head><body>
    <h1 class="err">Hata</h1><p class="err">{$msg}</p>
    <p><a href="/">← Geri dön</a></p>
    </body></html>
    HTML;
}
