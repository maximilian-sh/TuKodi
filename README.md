# TuKodi — TU Wien Lecture Streams für Kodi

Kodi-Addon zum Ansehen von Live-Vorlesungsstreams der TU Wien via TUWEL (LectureTube Live).

## Features

- Automatisches Login via TUWEL (SAML2 SSO mit TUaccount)
- Session-Caching — Login nur einmal nötig, solange der Cookie gültig ist
- Eigene Kurse aus TUWEL laden und Livestream-Aktivitäten auflisten
- Direkte Hörsaal-Auswahl ohne TUWEL-Login (28 Hörsäle vorkonfiguriert)
- Credential-Fallback via `credentials.json` wenn Kodi-Settings nicht lesbar sind

## Anforderungen

- Kodi 19+ (Leia oder neuer), getestet auf **Kodi 21 Omega** / LibreELEC aarch64
- `script.module.requests` (normalerweise vorinstalliert)
- `inputstream.adaptive` (normalerweise vorinstalliert)

## Installation

### Via Repository (empfohlen)

**1. Unknown Sources aktivieren**
Einstellungen → System → Add-ons → **Unbekannte Quellen** → Ein

**2. Quelle hinzufügen**
Einstellungen → Dateimanager → `<Quelle hinzufügen>` → URL direkt ins Textfeld eingeben (nicht Browse):
```
https://maximilian-sh.github.io/TuKodi/
```
Name: `TuKodi Repo` → OK

**3. Repository-Addon installieren**
Einstellungen → Add-ons → Aus ZIP-Datei installieren → `TuKodi Repo` → `repository.tukodi/` → `repository.tukodi-2026.3.3.zip`

**4. TuKodi aus dem Repository installieren**
Add-ons → Add-on Browser → Aus Repository installieren → `TuKodi Repository` → Video-Add-ons → `TuKodi - TU Wien Streams` → Installieren

**5. Zugangsdaten eintragen**
TuKodi → Einstellungen → Benutzername (Matrikelnummer) + Passwort eintragen

Kodi prüft danach automatisch auf Updates.

### Für Entwickler (SSH deploy)

```bash
KODI_HOST=192.168.x.x KODI_USER=root ./deploy.sh
```

Das Script baut ein ZIP, kopiert das Addon per SCP zu deinem Kodi-Gerät und restartet es via JSONRPC.

## Konfiguration

In den Addon-Einstellungen oder direkt in `/userdata/addon_data/plugin.video.tukodi/credentials.json`:

```json
{
  "username": "12345678",
  "password": "deinPasswort"
}
```

## Technische Details / Warum `curl` statt `requests`

Der LectureTube-Live-CDN (`live-cdn-N.video.tuwien.ac.at`) **erzwingt HTTP/2**.

Python's `requests`/`urllib3` unterstützt nur HTTP/1.1 — direkte Requests an den CDN schlagen daher immer mit `RemoteDisconnected` fehl. Kodi's `inputstream.adaptive` nutzt intern `libcurl` (mit `nghttp2`), kann HTTP/2 also, hat aber ein anderes Problem: es schlägt beim zweiten Fetch der Chunklist fehl wenn der CDN-Redirect-Chain nicht korrekt durchgegangen wird.

**Lösung:** Das Addon ruft den system-`curl` binary (kompiliert mit `nghttp2`) direkt per Subprocess auf, um die master playlist zu laden und die Chunklist-URL zu extrahieren. Diese URL wird dann direkt an inputstream.adaptive übergeben — kein Redirect mehr nötig, ISA kann die Chunklist und TS-Segmente direkt vom CDN laden.

```
live.video.tuwien.ac.at/…/playlist.m3u8
  → HTTP/2 303 → live-cdn-N.video.tuwien.ac.at/…/playlist.m3u8   (via curl)
    → Inhalt: live-cdn-N.video.tuwien.ac.at/…/chunklist.m3u8      (via curl geparst)
      → direkt an inputstream.adaptive übergeben                   (kein Redirect)
        → TS-Segmente: media-*.ts                                  (via ISA + stream_headers)
```

> **Hinweis für den FSBU-Streamer:** Das gleiche Problem (HTTP/2-only CDN) hat vermutlich auch den alten Fachschafts-Streamer kaputtgemacht, als der CDN auf HTTP/2-only umgestellt wurde.

## Bekannte Einschränkungen

- **2FA/TOTP wird nicht unterstützt.** Accounts mit aktivierter Zwei-Faktor-Authentifizierung können sich nicht einloggen.

## Authentifizierung

TUWEL verwendet SAML2 SSO via SimpleSAMLphp. Der Login-Flow:

1. GET `tuwel.tuwien.ac.at/auth/saml2/login.php` → Redirect zum IdP
2. POST credentials (+ optional TOTP) an `idp.zid.tuwien.ac.at/…/loginuserpass`
3. SAMLResponse zurück an TUWEL ACS posten
4. `MoodleSessiontuwel`-Cookie wird gesetzt und als Pickle gecacht

## Projektstruktur

```
plugin.video.tukodi/
├── addon.xml                  # Addon-Metadaten und Dependencies
├── addon.py                   # Router, Menüs, Playback
└── resources/
    ├── settings.xml           # Kodi-Settings-Definition
    └── lib/
        ├── auth.py            # SAML2-Login, Session-Caching
        └── tuwel.py           # TUWEL-Scraping, curl-basierter Stream-Resolver
```
