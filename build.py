"""Packages reFX Cloud Access into a .nvda-addon file.

	py build.py           build refxCloudAccess-<version>.nvda-addon
	py build.py --clean   remove build output
"""

import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.join(ROOT, "addon")
sys.path.insert(0, ROOT)

from buildVars import addon_info, addon_source_dirs  # noqa: E402

MANIFEST_TEMPLATE = """name = {addon_name}
summary = "{addon_summary}"
description = \"\"\"{addon_description}\"\"\"
author = "{addon_author}"
url = {addon_url}
version = {addon_version}
{changelogLine}minimumNVDAVersion = {addon_minimumNVDAVersion}
lastTestedNVDAVersion = {addon_lastTestedNVDAVersion}
updateChannel = {addon_updateChannel}
"""


def writeManifest(path):
	values = dict(addon_info)
	values["addon_url"] = values["addon_url"] or "None"
	values["addon_updateChannel"] = values["addon_updateChannel"] or "None"
	changelog = values.get("addon_changelog")
	if changelog and '"""' in changelog:
		raise SystemExit("addon_changelog cannot contain triple quotes")
	# Left out entirely when there is none, rather than written as the text None.
	values["changelogLine"] = 'changelog = """%s"""\n' % changelog if changelog else ""
	with open(path, "w", encoding="utf-8", newline="\n") as f:
		f.write(MANIFEST_TEMPLATE.format(**values))


def packageName():
	return "%s-%s.nvda-addon" % (addon_info["addon_name"], addon_info["addon_version"])


def build():
	manifestPath = os.path.join(ADDON_DIR, "manifest.ini")
	writeManifest(manifestPath)
	target = os.path.join(ROOT, packageName())
	with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
		archive.write(manifestPath, "manifest.ini")
		for sourceDir in addon_source_dirs:
			base = os.path.join(ADDON_DIR, sourceDir)
			if not os.path.isdir(base):
				continue
			for dirPath, dirNames, fileNames in os.walk(base):
				dirNames[:] = [d for d in dirNames if d != "__pycache__"]
				for fileName in fileNames:
					if fileName.endswith((".pyc", ".pyo")):
						continue
					full = os.path.join(dirPath, fileName)
					archive.write(full, os.path.relpath(full, ADDON_DIR).replace(os.sep, "/"))
	print("built %s" % os.path.relpath(target, ROOT))


def clean():
	for name in os.listdir(ROOT):
		if name.endswith(".nvda-addon"):
			os.remove(os.path.join(ROOT, name))
			print("removed %s" % name)
	manifest = os.path.join(ADDON_DIR, "manifest.ini")
	if os.path.isfile(manifest):
		os.remove(manifest)
		print("removed addon/manifest.ini")


if __name__ == "__main__":
	if "--clean" in sys.argv[1:]:
		clean()
	else:
		build()
