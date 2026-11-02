# The executable is "reFX Cloud.exe". NVDA can't import an app module whose name has a space,
# so map the executable to appModules/refxcloud.py explicitly.

import appModuleHandler
import globalPluginHandler
from logHandler import log

EXECUTABLE = "refx cloud"
APP_MODULE = "refxcloud"


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()
		appModuleHandler.registerExecutableWithAppModule(EXECUTABLE, APP_MODULE)
		# If reFX Cloud was already running, it got the default app module; swap it out.
		for mod in list(appModuleHandler.runningTable.values()):
			if mod.appName == EXECUTABLE and not type(mod).__module__.endswith(APP_MODULE):
				log.debug("reFX Cloud already running, reloading app modules")
				appModuleHandler.reloadAppModules()
				break

	def terminate(self):
		# NVDA has no public unregister call.
		getattr(appModuleHandler, "_executableNamesToAppModsAddons", {}).pop(EXECUTABLE, None)
		super().terminate()
