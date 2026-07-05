# GitHub-Setup für "Neumann Connect"

Kurzanleitung, um dieses Verzeichnis als **privates** GitHub-Repository
namens `neumann-connect` anzulegen und den aktuellen Stand hochzuladen.

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
git commit -m "Initial commit: Neumann Connect HA Integration"
git branch -M main
git remote add origin https://github.com/<DEIN-GITHUB-USERNAME>/neumann-connect.git
git push -u origin main
```

`<DEIN-GITHUB-USERNAME>` durch deinen tatsächlichen GitHub-Benutzernamen
ersetzen. Falls du SSH statt HTTPS bevorzugst, stattdessen:

```bash
git remote add origin git@github.com:<DEIN-GITHUB-USERNAME>/neumann-connect.git
```

## 3. Spätere Änderungen hochladen

Für jede weitere Anpassung (z. B. neue Versionen dieser Integration):

```bash
git add .
git commit -m "Kurze Beschreibung der Änderung"
git push
```

## 4. Optional: Als HACS Custom Repository einbinden

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
