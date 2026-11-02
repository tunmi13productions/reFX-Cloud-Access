"""Add-on metadata, read by build.py to generate the manifest."""

addon_info = {
	"addon_name": "refxCloudAccess",
	# Translators: summary of the add-on, shown in NVDA's add-on manager.
	"addon_summary": "reFX Cloud Access",
	# Translators: long description of the add-on, shown in NVDA's add-on manager.
	"addon_description": (
		"Makes the reFX Cloud app, which installs and manages Nexus and its expansions, usable with NVDA. "
		"The app has no keyboard navigation of its own, so this add-on moves between its controls with "
		"Tab and the arrow keys, activates them with Enter and Space, and gives clear names to buttons, "
		"packs, menus and settings that would otherwise be unlabeled or misleading. "
		"Warning: this add-on was vibe coded with Claude Opus 5.5, Anthropic's AI model. "
		"Expect oddities, and please report anything that behaves strangely."
	),
	"addon_version": "1.0",
	# Translators: what changed in this version, shown in NVDA's add-on store.
	"addon_changelog": "First release.",
	"addon_author": "tunmi13 <tunmi12@mail.com>",
	"addon_url": "https://github.com/tunmi13productions/reFX-Cloud-Access",
	"addon_minimumNVDAVersion": "2024.1",
	"addon_lastTestedNVDAVersion": "2026.2",
	"addon_updateChannel": None,
}

# Paths inside addon/ that are copied into the package.
addon_source_dirs = ["appModules", "globalPlugins"]
