<#
  W.Sign redirect-session — otomatik uçtan-uca (E2E) sunucu akışı testi.

  Bu script, GERÇEK USB token / W.Sign Desktop / tarayıcı GEREKTİRMEDEN sunucu
  protokolünün tamamını doğrular: create -> info -> prepare -> (yerel imza) ->
  complete -> result (pull) -> callback. İmzayı, private key'ini KENDİMİZ
  tuttuğumuz geçici bir software (self-signed) sertifikayla üretir; böylece
  /prepare'in döndürdüğü DataToSign'ı imzalayıp /complete'i sürebiliriz.

  "result (pull)" adımı, entegratörün birincil akışını (sonucu outbound GET ile
  çekme) tünelsiz doğrular; webhook.site beklemeye gerek kalmaz.

  KAPSAMADIĞI (kasıtlı): nitelikli USB token, Desktop wsign:// UI, tarayıcı redirect.
  Bunlar manuel kart testinin konusu (bkz. e2e/README.md).

  ÖN KOŞUL: demo tenant host'ta ENABLE edilmiş olmalı ve aşağıdaki callback host'u
  entegratör allowlist'inde olmalı. Public callback alıcısı olarak webhook.site
  (veya kendi public endpoint'in) kullan.

  Kullanım:
    $env:WSIGN_API_BASE      = "https://api.sign.wsoft.tr"
    $env:WSIGN_API_KEY       = "wsign-demo-key"
    $env:WSIGN_CALLBACK_URL  = "https://webhook.site/<senin-uuid>"
    $env:WSIGN_RETURN_URL    = "https://webhook.site/<senin-uuid>"   # redirect allowlist'te olmalı
    ./smoke-e2e.ps1
#>
$ErrorActionPreference = "Stop"

$apiBase     = $env:WSIGN_API_BASE;     if (-not $apiBase)     { $apiBase = "https://api.sign.wsoft.tr" }
$apiKey      = $env:WSIGN_API_KEY;      if (-not $apiKey)      { $apiKey  = "wsign-demo-key" }
$callbackUrl = $env:WSIGN_CALLBACK_URL; if (-not $callbackUrl) { throw "WSIGN_CALLBACK_URL gerekli (public, allowlist'te)." }
$returnUrl   = $env:WSIGN_RETURN_URL;   if (-not $returnUrl)   { $returnUrl = $callbackUrl }

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }

# 0) Geçici software imzalama sertifikası (private key bizde -> DataToSign'ı imzalayabiliriz)
Step "Geçici self-signed RSA sertifikası üretiliyor"
$cert = New-SelfSignedCertificate -Subject "CN=WSign E2E Test" -KeyAlgorithm RSA -KeyLength 2048 `
        -CertStoreLocation "Cert:\CurrentUser\My" -NotAfter (Get-Date).AddDays(1) -KeyExportPolicy Exportable
try {
  $certB64 = [Convert]::ToBase64String($cert.RawData)
  $docB64  = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("W.Sign E2E test belgesi - $(Get-Date -Format o)"))
  $nonce   = [Convert]::ToBase64String((1..16 | ForEach-Object { Get-Random -Max 256 }))

  $headers = @{ "X-WSign-Api-Key" = $apiKey }

  # 1) create
  Step "POST /v1/redirect-sign/sessions"
  $createBody = @{ documentBase64=$docB64; documentName="e2e.txt"; signatureProfile="CAdES-BES";
                   callbackUrl=$callbackUrl; successRedirectUrl=$returnUrl; nonce=$nonce } | ConvertTo-Json
  $created = Invoke-RestMethod -Method Post "$apiBase/v1/redirect-sign/sessions" -Headers $headers -ContentType "application/json" -Body $createBody
  $sid = $created.sessionId
  Write-Host "    sessionId=$sid"
  Write-Host "    redirectUrl=$($created.redirectUrl)"
  if ($created.redirectUrl -notmatch "/rs/") { throw "redirectUrl /rs/ içermiyor!" }

  # 2) info (auth yok)
  Step "GET /v1/redirect-sign/sessions/{id}"
  $info = Invoke-RestMethod "$apiBase/v1/redirect-sign/sessions/$sid"
  Write-Host "    status=$($info.status) origin=$($info.origin) successRedirectUrl=$($info.successRedirectUrl)"

  # 3) prepare (Desktop'ın yaptığı; cert'i biz veriyoruz)
  Step "POST /v1/redirect-sign/sessions/{id}/prepare"
  $prep = Invoke-RestMethod -Method Post "$apiBase/v1/redirect-sign/sessions/$sid/prepare" -ContentType "application/json" -Body (@{ signerCertificate=$certB64 } | ConvertTo-Json)
  $dataToSign = [Convert]::FromBase64String($prep.dataToSign)
  Write-Host "    dataToSign $($dataToSign.Length) bytes, algorithm=$($prep.algorithm)"

  # 4) DataToSign'ı private key ile imzala (RSA PKCS#1 v1.5, SHA-256) -- token YOK, key bizde
  Step "DataToSign yerel private key ile imzalanıyor"
  $rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)
  $rawSig = $rsa.SignData($dataToSign, [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
  $rawSigB64 = [Convert]::ToBase64String($rawSig)

  # 5) complete
  Step "POST /v1/redirect-sign/sessions/{id}/complete"
  $done = Invoke-RestMethod -Method Post "$apiBase/v1/redirect-sign/sessions/$sid/complete" -ContentType "application/json" -Body (@{ rawSignature=$rawSigB64 } | ConvertTo-Json)
  Write-Host "    status=$($done.status)"
  if ($done.status -ne "completed") { throw "complete status beklenen 'completed' değil: $($done.status)" }

  # 6) result (PULL) -- entegratörün birincil akışı: sonucu authed GET ile çek (tünelsiz)
  Step "GET /v1/redirect-sign/sessions/{id}/result (pull)"
  $result = Invoke-RestMethod "$apiBase/v1/redirect-sign/sessions/$sid/result" -Headers $headers
  Write-Host "    status=$($result.status)"
  if ($result.status -ne "completed") { throw "result status beklenen 'completed' değil: $($result.status)" }
  if (-not $result.signedContentBase64) { throw "result.signedContentBase64 boş -- imzalı içerik pull ile gelmedi!" }
  if ($result.nonce -ne $nonce) { throw "result.nonce eşleşmiyor: beklenen '$nonce', gelen '$($result.nonce)'" }
  Write-Host "    signedContentBase64 dolu, nonce eşleşti." -ForegroundColor Green

  Write-Host ""
  Write-Host "E2E SUNUCU AKIŞI BAŞARILI (pull doğrulandı)." -ForegroundColor Green
  Write-Host "Opsiyonel callback'i $callbackUrl adresinde de kontrol edebilirsin: X-WSign-Signature header'i + nonce='$nonce' eşleşmeli, signedContentBase64 dolu olmalı." -ForegroundColor Green
}
finally {
  # Geçici sertifikayı temizle
  Remove-Item "Cert:\CurrentUser\My\$($cert.Thumbprint)" -Force -ErrorAction SilentlyContinue
}
