# İmza Tipi Seçimi — `signatureProfile` (CAdES/XAdES, BES/-T)

Redirect-session ile oturum açarken hangi **imza tipini** istediğinizi
`signatureProfile` alanıyla belirtirsiniz. Üç örnekte de (.NET, PHP, Python)
imzalama formunda bir **"İmza tipi" açılır listesi** vardır; seçilen değer create
isteğinin (`POST /v1/redirect-sign/sessions`) `signatureProfile` alanına geçer.

## Geçerli değerler (server ile ortak sabit kontrat)

| `signatureProfile` | Biçim | Zaman damgası | İçerik türü (imzalı çıktı) | Uzantı |
|---|---|---|---|---|
| `CAdES-BES` (varsayılan) | CAdES | yok | `application/pkcs7-mime` | `.p7s` |
| `CAdES-T` | CAdES | **var** | `application/pkcs7-mime` | `.p7s` |
| `XAdES-BES` | XAdES | yok | `application/xml` | `.xml` |
| `XAdES-T` | XAdES | **var** | `application/xml` | `.xml` |

- **`-BES`** = temel imza (zaman damgasız).
- **`-T`** = imzaya **güvenilir zaman damgası** eklenir (CAdES-T / XAdES-T).
- İçerik türü ve uzantı, imzalı sonuç (`result` / callback) yanıtındaki
  `contentType` ve `fileExtension` alanlarından gelir; örnekler indirme dosyasının
  uzantısını buna göre verir (CAdES → `.p7s`, XAdES → `.xml`).

## Varsayılan ve geri-düşüş (fallback)

- Formdaki açılır liste varsayılan olarak **`CAdES-BES`** seçilir.
- Form değeri yoksa/boşsa örnek, `.env` içindeki **`WSIGN_SIGNATURE_PROFILE`**
  değerine düşer (o da yoksa `CAdES-BES`).
- Tanınmayan bir değer gelirse örnek onu güvenle **`CAdES-BES`**'e normalize eder
  (`normalize_profile` / `NormalizeProfile`).

## Zaman damgası (`-T`) ve TSA gereksinimi

`-T` (CAdES-T / XAdES-T) seçildiğinde imzaya zaman damgası eklenir. Bunun için
**entegratör kaydınızda Kamu SM TSA** (zaman damgası sunucusu) tanımlı olmalıdır.

Tanımlı değilse server create isteğine **`400`** ile `TSA_NOT_CONFIGURED` koduyla
yanıt verir. Örnekler bu durumu yakalar ve kullanıcıya anlaşılır bir mesaj
gösterir:

> Zaman damgalı imza (CAdES-T/XAdES-T) için entegratörde Kamu SM TSA tanımlayın
> veya damgasız (BES) bir tip seçin.

TSA'yı /gelistirici (entegratör) ayarlarınızdan tanımlayabilir ya da geçici olarak
damgasız bir tip (`CAdES-BES` / `XAdES-BES`) seçerek devam edebilirsiniz.

## Sonuç sayfasında gösterim

İmza tamamlanınca örnekler sonuç sayfasında şunları gösterir:

- **İmza tipi** (`signatureProfile`) ve **zaman damgalı / damgasız** bilgisi
  (profil `-T` ile bitiyorsa "zaman damgalı").
- **İçerik türü** (`contentType`) — XAdES için `application/xml`.
- İmzalı içeriği indirme bağlantısı; dosya uzantısı `fileExtension`'a göre
  (`.p7s` veya `.xml`).
