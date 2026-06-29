<?php
// ===========================================================================
// Yapılandırma — yalnızca ortam değişkenlerinden okunur. Hiçbir sır hardcode değil.
// İsteğe bağlı: depo kökündeki .env dosyasını yükler (varsa).
// ===========================================================================

declare(strict_types=1);

/** .env varsa basitçe yükle (zaten tanımlı değişkenlerin üzerine yazmaz). */
function load_dotenv(string $path): void
{
    if (!is_file($path)) {
        return;
    }
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#' || !str_contains($line, '=')) {
            continue;
        }
        [$key, $val] = explode('=', $line, 2);
        $key = trim($key);
        $val = trim($val);
        if (getenv($key) === false) {
            putenv("$key=$val");
        }
    }
}

load_dotenv(__DIR__ . '/../.env');

function env(string $key, string $fallback): string
{
    $v = getenv($key);
    return ($v === false || $v === '') ? $fallback : $v;
}

return [
    'api_base'        => rtrim(env('WSIGN_API_BASE', 'https://api.sign.wsoft.tr'), '/'),
    'api_key'         => env('WSIGN_API_KEY', 'demo-REPLACE-ME'),
    'callback_secret' => env('WSIGN_CALLBACK_SECRET', 'demo-callback-secret-REPLACE-ME'),
    // Sonuç teslim modu: "redirect" (vsy; 302 + pull) | "post" (tarayıcı-aracılı
    // otomatik-POST teslimi, kapalı sistemler için). Bkz. docs/delivery-modes.md.
    'return_mode'     => env('WSIGN_RETURN_MODE', 'redirect'),
    'public_base_url' => rtrim(env('PUBLIC_BASE_URL', 'http://localhost:8080'), '/'),
    'storage_dir'     => __DIR__ . '/storage',
];
