# ONLYOFFICE Font Upgrades

A small administrator web app that lives at `/font-manager/` on an ONLYOFFICE Workspace portal. It lets you search and preview open fonts, select the families you actually want, and apply the **same managed font set** to both:

- ONLYOFFICE Workspace Mail / CKEditor
- ONLYOFFICE Document Server (Docs)

It also offers a Noto Color Emoji pack and installs an emoji picker into Mail compose.

## What the web app does

- Uses the live Fontsource catalogue (2,000+ open-source families).
- Search by family and filter by category or variable fonts.
- Lazy-loads previews so opening the catalogue does not download thousands of fonts.
- Select any number of families and click **Apply to Mail + Docs** once.
- `Complete language packs` downloads all available subsets, weights and styles for selected Fontsource families.
- `Colour emoji pack` installs Google's Noto Color Emoji font and enables a Mail emoji picker.
- Shows the currently selected/applied set.
- Supports local TTF, OTF, WOFF and WOFF2 import for fonts obtained from other open-font foundries.
- Keeps the managed files on the host so the selected set can be re-applied after container changes.
- Makes a best-effort rollback to the previous managed set if one ONLYOFFICE engine fails while applying an update.

## Font sources

### Fully integrated

**Fontsource** is the automatic catalogue. The manager uses Fontsource's public API to obtain family metadata and direct font-file URLs, then self-hosts the selected files locally after installation.

### Discovery + local import

The app also links to:

- Open Foundry
- FontSpace's Open category
- Fontshare
- The League of Moveable Type
- Velvetyne Type Foundry

These are intentionally not blindly scraped or mirrored. Download a font whose licence permits your intended use, then use the app's **Import a downloaded open font** control. Once imported, it is selected and can be pushed to Mail and Docs exactly like a Fontsource family.

This distinction matters because “free to download” and “open-source/redistributable” are not always the same thing.

## Install

Run this on the Docker host that runs ONLYOFFICE Workspace / Community Server and Document Server:

```bash
git clone https://github.com/lurcheous73/onlyoffice-font-upgrades.git
cd onlyoffice-font-upgrades
sudo bash ./install.sh
```

The installer:

1. Installs the dependency-free Python web service under `/opt/onlyoffice-font-manager`.
2. Creates root-only admin/session secrets in `/etc/onlyoffice-font-manager.json`.
3. Starts `onlyoffice-font-manager.service` on port `8777`.
4. Detects the running Community Server container and its Docker gateway.
5. Adds a same-origin Nginx route at `/font-manager/` inside Community Server.
6. Prints the Font Manager administrator password once.

You can preset the first admin password:

```bash
sudo OOFM_ADMIN_PASSWORD='choose-a-strong-password' bash ./install.sh
```

## Put it in the ONLYOFFICE menu

In ONLYOFFICE Workspace open:

**Settings → Modules & Tools → Custom Navigation → Add Item**

Use:

```text
Label: Fonts
URL:   https://YOUR-ONLYOFFICE-HOST/font-manager/
```

Enable **Show in menu** and optionally **Show on home page**.

The route is same-origin with the portal. Direct access to the backend port is rejected unless the request carries the private proxy header generated during installation.

## Applying fonts

Open **Fonts** from ONLYOFFICE, sign into Font Manager, select families, leave `Complete language packs` enabled if you want the complete family, then click:

**Apply to Mail + Docs**

For Mail, the manager:

- copies self-hosted fonts into the Community Server CKEditor web tree;
- creates `@font-face` CSS;
- adds selected families to the existing CKEditor font menu without deleting the stock list;
- installs the `😀` emoji rich-combo picker;
- restarts Community Server only as part of an explicit Apply operation.

For Docs, the manager:

- copies the same managed font files under `/usr/share/fonts/truetype/custom/onlyoffice-font-manager` in Document Server;
- refreshes fontconfig;
- runs `/usr/bin/documentserver-generate-allfonts.sh` when present.

ONLYOFFICE's own documentation lists TTF, OTF, WOFF and WOFF2 as supported Document Server font formats.

## Emoji

The optional emoji pack downloads `NotoColorEmoji.ttf` from the official `googlefonts/noto-emoji` repository. The Noto Emoji project licenses its font files under SIL Open Font License 1.1.

Mail gets an emoji picker with common categories (faces, people, hearts, animals, food, objects, travel). The inserted content is normal Unicode text, not image attachments.

Colour rendering still depends on the browser/editor's colour-font support. The Unicode characters remain valid even where a renderer falls back to monochrome.

## Persistent state

Manager state lives under:

```text
/var/lib/onlyoffice-font-manager/
```

The selected set is stored in `selection.json`; managed font files and the manifest live under `managed/`.

The app never deletes ONLYOFFICE's stock font directories. It owns and replaces only its own `onlyoffice-font-manager` directories.

## After an ONLYOFFICE container replacement

A normal container restart keeps the injected route and managed files. If an ONLYOFFICE upgrade **recreates** Community Server, restore the web-app route with:

```bash
sudo onlyoffice-font-manager-repair-proxy
```

Then open Font Manager and click **Apply to Mail + Docs** again to restore the managed files into freshly created containers.

## Security

- The backend has its own administrator password.
- Session cookie is HttpOnly and SameSite=Strict.
- Mutating API requests require a CSRF token.
- Requests must arrive through the ONLYOFFICE Nginx route and include a private proxy secret.
- The app does not need third-party Python packages.
- The service runs with `NoNewPrivileges=true`; it remains root because applying fonts requires controlled access to Docker containers.

Treat access to Font Manager as administrator access: it can modify the fonts exposed by the office and mail engines.

## Useful commands

```bash
systemctl status onlyoffice-font-manager
journalctl -u onlyoffice-font-manager -f
sudo onlyoffice-font-manager-repair-proxy
```

Configuration/secrets:

```text
/etc/onlyoffice-font-manager.json
```

## Licence

The manager code is MIT licensed. Downloaded fonts retain their own licences. No third-party font binaries are committed to this repository.
