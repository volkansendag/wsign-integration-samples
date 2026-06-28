# Callback HMAC Doğrulaması

## Neden önemli?

W.Sign callback POST'u, imzalı belgeyi (`signedContentBase64`) entegratöre
teslim eden adımdır. Bu endpoint internete açıktır; **herkes** sahte bir POST
gönderebilir. İki bağımsız kontrol callback'in gerçekten W.Sign'dan geldiğini
ve değiştirilmediğini kanıtlar:

1. **HMAC-SHA256** — gövdenin tamamı üzerinde, paylaşılan `hmacSecret` ile.
   `X-WSign-Signature: sha256=<hex>` başlığıyla karşılaştırılır. Yalnızca
   secret'ı bilen taraf (W.Sign) bu imzayı üretebilir. Gövde bir byte bile
   değişirse imza tutmaz.
2. **nonce** — oturum açarken gönderdiğiniz rastgele değerin callback'te aynen
   dönmesi. Bu, callback'i **sizin başlattığınız** belirli oturuma bağlar
   (replay/CSRF koruması).

## Kritik kural: HAM gövde üzerinde hesapla

HMAC, **alınan ham byte'lar** üzerinde hesaplanmalıdır. Önce JSON parse edip
sonra yeniden serialize ederseniz boşluk/anahtar sırası değişir ve imza tutmaz.
Her örnekte gövde önce ham olarak okunur, HMAC doğrulanır, **sonra** parse
edilir.

## Sabit-zamanlı karşılaştırma

İmzayı normal `==` ile karşılaştırmayın — erken çıkış zamanlama saldırısına
açık olur. Her dilde sabit-zamanlı bir karşılaştırma kullanın.

---

## .NET (C#)

```csharp
using System.Security.Cryptography;

static bool VerifyHmac(byte[] rawBody, string signatureHeader, byte[] secret)
{
    // Başlık biçimi: "sha256=<hex>"
    if (string.IsNullOrEmpty(signatureHeader) ||
        !signatureHeader.StartsWith("sha256=", StringComparison.Ordinal))
        return false;

    var providedHex = signatureHeader["sha256=".Length..];
    var computed = HMACSHA256.HashData(secret, rawBody);
    var computedHex = Convert.ToHexStringLower(computed);

    // Sabit-zamanlı karşılaştırma
    var a = System.Text.Encoding.ASCII.GetBytes(computedHex);
    var b = System.Text.Encoding.ASCII.GetBytes(providedHex);
    return CryptographicOperations.FixedTimeEquals(a, b);
}
```

## PHP

```php
function verify_hmac(string $rawBody, string $signatureHeader, string $secret): bool
{
    // Başlık biçimi: "sha256=<hex>"
    if (strncmp($signatureHeader, 'sha256=', 7) !== 0) {
        return false;
    }
    $providedHex = substr($signatureHeader, 7);
    $computedHex = hash_hmac('sha256', $rawBody, $secret); // hex string

    // hash_equals: sabit-zamanlı karşılaştırma
    return hash_equals($computedHex, $providedHex);
}
```

## Python

```python
import hmac, hashlib

def verify_hmac(raw_body: bytes, signature_header: str, secret: bytes) -> bool:
    # Başlık biçimi: "sha256=<hex>"
    if not signature_header.startswith("sha256="):
        return False
    provided_hex = signature_header[len("sha256="):]
    computed_hex = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    # compare_digest: sabit-zamanlı karşılaştırma
    return hmac.compare_digest(computed_hex, provided_hex)
```

---

## Doğrulama akışının tamamı

```
1. Ham gövde byte'larını oku       (parse ETME)
2. X-WSign-Signature başlığını al
3. HMAC-SHA256(rawBody, secret) == başlık ?   → hayırsa 401, dur
4. JSON parse et
5. nonce == bu sessionId için sakladığın nonce ?  → hayırsa 401, dur
6. signedContentBase64'ü sakla, durumu güncelle
7. 200 OK döndür
```

Bu altı adım her üç örnekte (`dotnet/`, `php/`, `python/`) birebir aynıdır.
