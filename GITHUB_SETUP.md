# GitHub-Setup für "Neumann Connect"

Kurzanleitung, um dieses Verzeichnis als **privates** GitHub-Repository
namens `neumann-connect` anzulegen und den aktuellen Stand (v1.3.0)
hochzuladen.

## 1. Repo bei GitHub anlegen

Auf https://github.com/new:
- **Repository name:** `neumann-connect`
- **Visibility:** Private
- Kein README/.gitignore/License bei der Erstellung mitanlegen lassen
  (die liegen hier bereits lokal, sonst gibt's beim ersten Push einen
  unnötigen Merge-Konflikt).

## 2. Lokal initialisieren und pushen

Im entpackten Ordner (dort, wo diese Datei liegt) ausführen:

```bash
git init
git add .
git commit -m "Neumann Connect v1.3.0: SSC-Integration mit Auto-Discovery und hardware-verifizierten Pfaden

- Eigenständiger asyncio-SSC-Client (Port 45, JSON), keine Fremdabhängigkeit
- Config Flow: manuelle Eingabe ODER aktive mDNS-Netzwerksuche mit Auswahlliste
- Number/Switch/Sensor/Button-Entities für Level, Dimm, Delay, Mute, Phasenumkehr,
  Logo-Helligkeit, Eingangsverstärkung, Live-Pegelmessung, Einstellungen speichern
- SSC-Pfade gegen echten khtool-Dump (KH 120 II, Firmware 1_7_3) verifiziert
- Container-weises Polling statt Sammelanfrage (vermeidet 'message not understood')
- Details siehe CHANGELOG.md"
git branch -M main
git remote add origin https://github.com/<DEIN-GITHUB-USERNAME>/neumann-connect.git
git push -u origin main
```

`<DEIN-GITHUB-USERNAME>` durch deinen tatsächlichen GitHub-Benutzernamen
ersetzen. Falls du SSH statt HTTPS bevorzugst, stattdessen:

```bash
git remote add origin git@github.com:<DEIN-GITHUB-USERNAME>/neumann-connect.git
```

## 3. Optional, aber empfohlen: Release-Tag setzen

Damit die aktuelle Version auch als GitHub-Release auffindbar ist:

```bash
git tag -a v1.3.0 -m "v1.3.0 - Hardware-verifizierte SSC-Pfade, containerweises Polling"
git push origin v1.3.0
```

Auf GitHub kannst du daraus unter **Releases → Draft a new release** direkt
ein Release erstellen und den entsprechenden Abschnitt aus `CHANGELOG.md`
als Beschreibung einfügen.

## 4. Spätere Änderungen hochladen

Für jede weitere Anpassung (z. B. neue Versionen dieser Integration):
Version in `manifest.json` hochzählen, Änderung oben in `CHANGELOG.md`
ergänzen, dann:

```bash
git add .
git commit -m "Kurze, aber aussagekräftige Beschreibung der Änderung"
git push
```

## 5. Optional: Als HACS Custom Repository einbinden

Die Datei `hacs.json` im Repo-Root ist bereits vorbereitet. Um die
Integration künftig über HACS zu installieren/aktualisieren, statt den
Ordner manuell zu kopieren:

1. HACS → Integrationen → Menü (⋮) oben rechts → **Benutzerdefinierte
   Repositories**
2. URL: `https://github.com/<DEIN-GITHUB-USERNAME>/neumann-connect`
3. Kategorie: **Integration**
4. Danach erscheint "Neumann Connect" in der normalen HACS-Suche und lässt
   sich darüber installieren/aktualisieren.

> Hinweis: Bei einem **privaten** Repo muss HACS zusätzlich mit einem
> GitHub-Token mit Lesezugriff auf private Repos verbunden sein (unter
> HACS-Einstellungen → GitHub-Personal-Access-Token). Für den reinen
> manuellen Kopier-Weg (wie bisher beschrieben) ist das nicht nötig.
