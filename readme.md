# reFX Cloud Access

An NVDA add-on that makes the reFX Cloud app (the installer and manager for Nexus and its expansions) usable with a screen reader.

reFX Cloud is built with JUCE 8. It exposes its controls through UI Automation, but none of them accept keyboard focus, so Tab and the arrow keys do nothing on their own. This add-on moves real focus between the app's own controls and activates them, and it fixes labels that would otherwise be read as numbers or as bare words like "Default".

Warning: this add-on was vibe coded with Claude Opus 5.5, Anthropic's AI model. Expect oddities, and please report anything that behaves strangely.

## Download

Download the latest version: https://github.com/tunmi13productions/reFX-Cloud-Access/releases/latest/download/refxCloudAccess.nvda-addon

Press Enter on the downloaded file to install it, then restart NVDA when prompted. The link always points at the newest release.

## Keys (inside reFX Cloud)

| Key | Action |
|---|---|
| Tab / Shift+Tab | Next / previous control (buttons, sidebar pages, checkboxes, search field) |
| Down / Up arrow | Next / previous item, including text such as headings and versions |
| Home / End | First / last item |
| Enter or Space | Activate the focused control |
| Ctrl+Tab / Ctrl+Shift+Tab | Next / previous sidebar page (Nexus, Queued, Settings) |

In the search field, combo boxes (such as the drive picker when changing a folder) and sliders, the arrows, Home, End, Enter and Space go to the control as normal. Tab moves out of it. In popup menus (such as a pack's actions menu) the keys go straight to the menu, the first item is selected when it opens, and closing the menu returns you to the button that opened it.

Sections that are off screen, such as packs further down the list or the Advanced settings, are scrolled into view as you reach them.

## Label fixes

- Pack buttons read as "Christmas 2017, Installed" (pack, then status) and "Actions for Christmas 2017".
- The user menu button reads its account and computer name inline ("user menu, account, computer") instead of as a multi-line description.
- The plugin's status button ("Install" or "Latest Version") reads as a plain button with its version ("Plugin, Latest Version, 5.5.21, button") instead of "checked" or "toggle button, not pressed".
- Other unlabeled "menu" buttons get their row's label ("Plugin Menu", "Expansions menu").
- In Settings, each folder row is three Tab stops: the folder with its path ("User Folder, C:\Users\Public\Documents\reFX\User Content\"), then "Change folder" (the app's Move button), then "Reset to default" (its Default button).
- Settings sections are announced by their on-screen headings (File Locations, Content Locations, Plugin Formats, Advanced). The list structure behind the page ("list", "not selected", "row 3") is not announced.
- Checkboxes and sidebar pages are no longer announced as read-only (the app wrongly flags their On/Off value as read-only).
- Items in ticked menus, like the Filter menu, are read as radio menu items. The filters (Owned through Outdated) are one pick-one list, and so is the sort order. The app shows the choice as a tick, so it would otherwise sound like a checkbox you can untick. To change a filter, choose a different one.
- The unnamed search box is called "Search".

## Building

```
py build.py
```

This writes `refxCloudAccess-<version>.nvda-addon` next to the script, generating `addon/manifest.ini` and the add-on's help page from `buildVars.py` and this readme. `py build.py --clean` removes the build output.

## Releasing

Set the new `addon_version` (and `addon_changelog`) in `buildVars.py`, commit, then tag and push:

```
git tag v1.1
git push origin main v1.1
```

The build workflow checks the tag matches `addon_version`, publishes a release for that version, and moves the `latest` release so the download link above serves it.

## License

GPL v2, the same as NVDA. See LICENSE.
