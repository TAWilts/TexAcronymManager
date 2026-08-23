# Marketplace assets

Place Marketplace media in this directory.

Expected files:

- `icon.png` — square PNG, at least 128×128 px. Recommended working size:
  256×256 or 512×512.
- `tacroman-demo.gif` — short Marketplace demo GIF.

After adding either file, rerun from the repository root:

```powershell
python apply_tacroman_marketplace_prep.py
```

The updater adds `icon` to `package.json` when `icon.png` exists and inserts the
demo GIF into the extension README when `tacroman-demo.gif` exists.

Suggested GIF sequence:

1. completion after `\ac{`;
2. plain `AUV` -> `\ac{AUV}`;
3. `autonomous...` -> `\ac{AUV}`;
4. open TAcroMan and manage entries;
5. Check Current File for Acronyms / interactive replacement.

Keep the recording short and readable at Marketplace width. Avoid showing
personal file paths, account names, unpublished text, or other private data.
