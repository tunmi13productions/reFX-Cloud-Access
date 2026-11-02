# reFX Cloud is a JUCE 8 app. It exposes a decent UIA tree, but none of its controls take keyboard
# focus, so Tab and the arrows do nothing. This module moves real UIA focus between the app's own
# controls and fixes the labels JUCE leaves unhelpful.

import re

import api
import appModuleHandler
import controlTypes
import core
import eventHandler
import ui
import UIAHandler
from comtypes import COMError
from keyboardHandler import KeyboardInputGesture
from logHandler import log
from NVDAObjects.UIA import UIA
from scriptHandler import script
from UIAHandler import UIA as UIAClient

Role = controlTypes.Role
State = controlTypes.State
CATEGORY = "reFX Cloud"

TAB_STOP_TYPES = frozenset((
	UIAClient.UIA_ButtonControlTypeId,
	UIAClient.UIA_RadioButtonControlTypeId,
	UIAClient.UIA_CheckBoxControlTypeId,
	UIAClient.UIA_EditControlTypeId,
	UIAClient.UIA_ComboBoxControlTypeId,
	UIAClient.UIA_SliderControlTypeId,
	UIAClient.UIA_HyperlinkControlTypeId,
	UIAClient.UIA_SplitButtonControlTypeId,
	UIAClient.UIA_SpinnerControlTypeId,
	UIAClient.UIA_TabItemControlTypeId,
))
MENU_TYPES = frozenset((UIAClient.UIA_MenuItemControlTypeId, UIAClient.UIA_MenuControlTypeId))
# Focus on these means arrows, Home, End, Enter and Space belong to the control: typing, a JUCE
# popup menu, or a control that JUCE changes with the arrows (combo box, slider, spinner).
# Tab and Shift+Tab still move between controls.
PASS_THROUGH_TYPES = (
	UIAClient.UIA_EditControlTypeId,
	UIAClient.UIA_MenuItemControlTypeId,
	UIAClient.UIA_MenuControlTypeId,
	UIAClient.UIA_ComboBoxControlTypeId,
	UIAClient.UIA_SliderControlTypeId,
	UIAClient.UIA_SpinnerControlTypeId,
)
WINDOW_CHROME = frozenset(("minimise", "maximise", "close"))
# Buttons whose names mean nothing without the label next to them.
GENERIC_BUTTON_NAMES = frozenset(("menu", "default", "move"))
# Text that is a value (version, path) rather than a label.
NOT_A_LABEL = re.compile(r"^[\d.\s]*$|[\\/]")
PATH = re.compile(r"[\\/]")
# Settings folder rows are: label text, Default button, Move button, path text.
FOLDER_BUTTON_NAMES = {"move": "Change folder", "default": "Reset to default"}


def _folderRow(items, i):
	"""items is a list of (controlType, name) siblings. If items[i] is the label of a folder row,
	return (path, indexes of the rest of the row), else None."""
	controlType, name = items[i]
	if controlType != UIAClient.UIA_TextControlTypeId or not name.strip() or NOT_A_LABEL.search(name):
		return None
	row = []
	for j in range(i + 1, len(items)):
		t, n = items[j]
		if t == UIAClient.UIA_TextControlTypeId and n.strip() and not NOT_A_LABEL.search(n):
			break  # the next row's label
		row.append(j)
	buttons = {items[j][1].strip().lower() for j in row if items[j][0] == UIAClient.UIA_ButtonControlTypeId}
	path = next((items[j][1] for j in row if items[j][0] == UIAClient.UIA_TextControlTypeId and PATH.search(items[j][1])), None)
	if path and set(FOLDER_BUTTON_NAMES) <= buttons:
		return path, row
	return None
PACK_SUFFIX = re.compile(r"\s+(download|actions)$", re.IGNORECASE)

CACHED_PROPERTIES = (
	UIAClient.UIA_NamePropertyId,
	UIAClient.UIA_ControlTypePropertyId,
	UIAClient.UIA_BoundingRectanglePropertyId,
)


# Set to True to log each navigation step at info level, to trace a keypress in the NVDA log.
TRACE = False


def _trace(message):
	if TRACE:
		log.info(f"reFX Cloud: {message}")


def _client():
	return UIAHandler.handler.clientObject


def _pattern(element, patternId, interface):
	try:
		punk = element.GetCurrentPattern(patternId)
		return punk.QueryInterface(interface) if punk else None
	except COMError:
		return None


class _Node:
	"""One element of a cached snapshot of a window's UIA subtree."""

	__slots__ = ("element", "name", "controlType", "rect", "parent", "children", "isFolderLabel", "hidden")

	def __init__(self, element, parent):
		self.element = element
		self.parent = parent
		self.name = element.CachedName or ""
		self.controlType = element.CachedControlType
		r = element.CachedBoundingRectangle
		self.rect = (r.left, r.top, r.right, r.bottom)
		self.children = []
		self.isFolderLabel = False  # a Settings folder label; a tab stop that reads its path
		self.hidden = False  # text already read as part of another stop

	@property
	def visible(self):
		return self.rect[2] > self.rect[0] and self.rect[3] > self.rect[1]

	@property
	def needsScrollToLoad(self):
		"""JUCE only builds the controls of list items that are on screen (pack cards, and Settings
		sections like Advanced, which gets its container but not its checkboxes). An item that
		isn't fully in view and has nothing to stop on yet must be scrolled in first."""
		if self.controlType != UIAClient.UIA_ListItemControlTypeId:
			return False
		viewport = self.ancestor(UIAClient.UIA_ListControlTypeId)
		if viewport is not None and viewport.rect[1] <= self.rect[1] and self.rect[3] <= viewport.rect[3]:
			return False
		return not any(_isTabStop(d) for d in self.descendants())

	def descendants(self):
		for child in self.children:
			yield child
			yield from child.descendants()

	def ancestor(self, controlType):
		node = self.parent
		while node is not None and node.controlType != controlType:
			node = node.parent
		return node

	def hasAncestorNamed(self, name):
		node = self.parent
		while node is not None:
			if node.name == name:
				return True
			node = node.parent
		return False


def _snapshot(rootElement):
	"""Fetch the whole subtree in one cross-process call."""
	request = _client().CreateCacheRequest()
	for prop in CACHED_PROPERTIES:
		request.AddProperty(prop)
	request.TreeScope = UIAClient.TreeScope_Subtree
	request.TreeFilter = _client().RawViewCondition
	return _build(rootElement.BuildUpdatedCache(request), None)


def _build(element, parent):
	node = _Node(element, parent)
	kids = element.GetCachedChildren()
	if kids:
		node.children = [_build(kids.GetElement(i), node) for i in range(kids.Length)]
	if node.controlType == UIAClient.UIA_ListControlTypeId:
		# Tree order of the content list doesn't match what's on screen.
		node.children.sort(key=lambda c: (c.rect[1], c.rect[0]))
	_arrangeFolderRows(node.children)
	return node


def _arrangeFolderRows(children):
	"""Folder label becomes a stop that reads the path; the path text is hidden; "Change folder"
	(Move) comes before "Reset to default" (Default)."""
	items = [(c.controlType, c.name) for c in children]
	swaps = []
	for i, child in enumerate(children):
		row = _folderRow(items, i)
		if not row:
			continue
		child.isFolderLabel = True
		buttons = {}
		for j in row[1]:
			if children[j].controlType == UIAClient.UIA_TextControlTypeId and PATH.search(children[j].name):
				children[j].hidden = True
			elif children[j].controlType == UIAClient.UIA_ButtonControlTypeId:
				buttons[children[j].name.strip().lower()] = j
		if buttons["default"] < buttons["move"]:
			swaps.append((buttons["default"], buttons["move"]))
	for a, b in swaps:
		children[a], children[b] = children[b], children[a]


def _flatten(root):
	"""Document order, with the minimise/maximise/close buttons moved to the end."""
	order, chrome = [], []

	def walk(node):
		for child in node.children:
			if node is root and child.name in WINDOW_CHROME:
				chrome.append(child)
				continue
			order.append(child)
			walk(child)

	walk(root)
	return order + chrome


def _isTabStop(node):
	if not node.visible:
		return False
	return node.controlType in TAB_STOP_TYPES or node.isFolderLabel or node.needsScrollToLoad


def _isReadingStop(node):
	if node.hidden:
		return False
	if _isTabStop(node):
		return True
	return node.visible and node.controlType == UIAClient.UIA_TextControlTypeId and node.name.strip()


# Settings section headings are drawn but not exposed; the containers only carry internal ids.
SECTION_HEADINGS = {
	"paths": "File Locations",
	"families": "Content Locations",
	"plugin formats": "Plugin Formats",
	"advanced": "Advanced",
}


def _humanize(automationName):
	heading = SECTION_HEADINGS.get(automationName.strip().lower())
	if heading:
		return heading
	return automationName[:1].upper() + automationName[1:]


class AppModule(appModuleHandler.AppModule):
	scriptCategory = CATEGORY

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# (element, automationId) of the last focused control, and of the control that opened the
		# current popup menu. JUCE drops focus onto the bare window when a menu closes.
		self._lastFocused = None
		self._menuOpener = None
		_trace(f"app module loaded for process {self.processID}")

	def event_gainFocus(self, obj, nextHandler):
		if isinstance(obj, AppWindow):
			if obj.isPopupMenu:
				self._menuOpener = self._lastFocused
			elif self._menuOpener is not None:
				opener, self._menuOpener = self._menuOpener, None
				if self._restoreFocus(obj.UIAElement, opener):
					# The opener's own focus event does the talking; skip announcing the window.
					return
		elif isinstance(obj, UIA) and not isinstance(obj, GroupedMenuItem):
			try:
				self._lastFocused = (obj.UIAElement, obj.UIAElement.CurrentAutomationId)
			except COMError:
				pass
		nextHandler()

	def _restoreFocus(self, window, saved):
		element, automationId = saved
		try:
			element.SetFocus()
			_trace("restored focus to the menu's opener")
			return True
		except COMError:
			pass
		if not automationId:
			return False
		try:
			# The opener was rebuilt (e.g. the list refreshed); find its replacement by id.
			cond = _client().CreatePropertyCondition(UIAClient.UIA_AutomationIdPropertyId, automationId)
			found = window.FindFirst(UIAClient.TreeScope_Descendants, cond)
			if found:
				found.SetFocus()
				_trace("restored focus to the menu's opener, found by id")
				return True
		except COMError:
			pass
		return False

	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		if not isinstance(obj, UIA):
			return
		try:
			controlType = obj.UIAElement.CachedControlType
		except COMError:
			return
		if controlType == UIAClient.UIA_ListItemControlTypeId:
			clsList.insert(0, ListSection)
		elif controlType == UIAClient.UIA_ListControlTypeId:
			clsList.insert(0, ContentList)
		elif controlType == UIAClient.UIA_EditControlTypeId:
			clsList.insert(0, SearchField)
		elif controlType == UIAClient.UIA_ButtonControlTypeId:
			clsList.insert(0, LabeledButton)
		elif controlType == UIAClient.UIA_CustomControlTypeId:
			clsList.insert(0, LayoutContainer)
		elif controlType == UIAClient.UIA_WindowControlTypeId:
			clsList.insert(0, AppWindow)
		elif controlType == UIAClient.UIA_MenuItemControlTypeId:
			clsList.insert(0, GroupedMenuItem)
		elif controlType == UIAClient.UIA_TextControlTypeId:
			clsList.insert(0, FolderLabel)
		elif controlType in (UIAClient.UIA_CheckBoxControlTypeId, UIAClient.UIA_RadioButtonControlTypeId):
			clsList.insert(0, ToggleControl)

	# Helpers

	# NVDA's focus object for a JUCE window isn't always a UIA object (it can be a plain window),
	# so everything below asks UI Automation directly.

	def _focusedElement(self):
		try:
			element = _client().GetFocusedElement()
			if element and element.CurrentProcessId == self.processID:
				return element
			_trace("focused element is in another process")
		except COMError:
			log.error("reFX Cloud: GetFocusedElement failed", exc_info=True)
		return None

	def _topLevel(self, element):
		"""The top-level window holding the element (main window, a dialog, or a popup menu)."""
		client = _client()
		desktop = client.GetRootElement()
		walker = client.RawViewWalker
		current = element
		while True:
			parent = walker.GetParentElement(current)
			if not parent or client.CompareElements(parent, desktop):
				return current
			current = parent

	def _snapshotOrder(self, focused):
		try:
			order = _flatten(_snapshot(self._topLevel(focused)))
		except COMError:
			log.error("reFX Cloud: snapshot failed", exc_info=True)
			return None
		if any(n.controlType in MENU_TYPES for n in order):
			_trace("popup menu open, passing key through")
			return None
		return order

	def _focusIndex(self, order, focused):
		compare = _client().CompareElements
		for i, node in enumerate(order):
			if compare(node.element, focused):
				return i
		return -1

	def _move(self, gesture, isStop, direction, jump=False, allowRetry=True):
		_trace(f"move {direction} via {gesture.displayName}")
		focused = self._focusedElement()
		order = self._snapshotOrder(focused) if focused is not None else None
		if order is None:
			gesture.send()
			return
		stops = [
			i for i, node in enumerate(order)
			# On the retry pass, an item that still has nothing to stop on after scrolling is skipped.
			if isStop(node) and (allowRetry or not node.needsScrollToLoad)
		]
		_trace(f"{len(order)} elements, {len(stops)} stops")
		if not stops:
			ui.message("No controls")
			return
		current = self._focusIndex(order, focused)
		if current < 0 and self._lastFocused is not None:
			# Focus fell back to the bare window (JUCE does this); continue from where we were.
			current = self._focusIndex(order, self._lastFocused[0])
		if jump or current < 0:
			target = stops[0] if direction > 0 else stops[-1]
		elif direction > 0:
			target = next((i for i in stops if i > current), stops[0])
		else:
			target = next((i for i in reversed(stops) if i < current), stops[-1])
		node = order[target]
		_trace(f"from {current} to {target}: {node.name!r} type {node.controlType}")
		self._scrollIntoView(node)
		if node.needsScrollToLoad:
			# Give JUCE a moment to build the item's controls, then move again to land inside it.
			core.callLater(250, self._move, gesture, isStop, direction, jump, False)
			return
		self._focus(node.element)

	def _scrollIntoView(self, node):
		item = node if node.controlType == UIAClient.UIA_ListItemControlTypeId else node.ancestor(
			UIAClient.UIA_ListItemControlTypeId
		)
		if item is None:
			return
		viewport = item.ancestor(UIAClient.UIA_ListControlTypeId)
		if viewport is not None and viewport.rect[1] <= node.rect[1] and node.rect[3] <= viewport.rect[3]:
			return
		pattern = _pattern(item.element, UIAClient.UIA_ScrollItemPatternId, UIAClient.IUIAutomationScrollItemPattern)
		if pattern:
			try:
				pattern.ScrollIntoView()
			except COMError:
				pass

	def _focus(self, element):
		before = api.getFocusObject()
		try:
			element.SetFocus()
		except COMError:
			log.error("reFX Cloud: SetFocus failed", exc_info=True)
			return
		core.callLater(250, self._announceIfSilent, element, before)

	def _announceIfSilent(self, element, before):
		"""Fallback for when NVDA didn't pick up a focus event from JUCE."""
		if api.getFocusObject() is not before:
			return
		_trace("no focus event arrived, announcing ourselves")
		try:
			obj = UIA(UIAElement=element.BuildUpdatedCache(UIAHandler.handler.baseCacheRequest))
		except COMError:
			log.error("reFX Cloud: couldn't build NVDA object", exc_info=True)
			return
		eventHandler.queueEvent("gainFocus", obj)

	def _passThrough(self):
		"""True when keys should go straight to the app: in a text field or a popup menu."""
		focused = self._focusedElement()
		if focused is None:
			return True
		try:
			return focused.CurrentControlType in PASS_THROUGH_TYPES
		except COMError:
			return True

	# Scripts

	@script(description="Moves to the next control", gesture="kb:tab")
	def script_nextControl(self, gesture):
		self._move(gesture, _isTabStop, 1)

	@script(description="Moves to the previous control", gesture="kb:shift+tab")
	def script_previousControl(self, gesture):
		self._move(gesture, _isTabStop, -1)

	@script(description="Moves to the next item, including text", gesture="kb:downArrow")
	def script_nextItem(self, gesture):
		if self._passThrough():
			gesture.send()
			return
		self._move(gesture, _isReadingStop, 1)

	@script(description="Moves to the previous item, including text", gesture="kb:upArrow")
	def script_previousItem(self, gesture):
		if self._passThrough():
			gesture.send()
			return
		self._move(gesture, _isReadingStop, -1)

	@script(description="Moves to the first item", gesture="kb:home")
	def script_firstItem(self, gesture):
		if self._passThrough():
			gesture.send()
			return
		self._move(gesture, _isReadingStop, 1, jump=True)

	@script(description="Moves to the last item", gesture="kb:end")
	def script_lastItem(self, gesture):
		if self._passThrough():
			gesture.send()
			return
		self._move(gesture, _isReadingStop, -1, jump=True)

	@script(description="Activates the focused control", gestures=["kb:enter", "kb:space"])
	def script_activate(self, gesture):
		element = self._focusedElement()
		if element is None or element.CurrentControlType in PASS_THROUGH_TYPES + (UIAClient.UIA_WindowControlTypeId,):
			gesture.send()
			return
		_trace(f"activating {element.CurrentName!r}")
		for patternId, interface, method in (
			(UIAClient.UIA_InvokePatternId, UIAClient.IUIAutomationInvokePattern, "Invoke"),
			(UIAClient.UIA_TogglePatternId, UIAClient.IUIAutomationTogglePattern, "Toggle"),
			(UIAClient.UIA_SelectionItemPatternId, UIAClient.IUIAutomationSelectionItemPattern, "Select"),
		):
			pattern = _pattern(element, patternId, interface)
			if pattern:
				try:
					getattr(pattern, method)()
				except COMError:
					log.error(f"reFX Cloud: {method} failed", exc_info=True)
				return
		gesture.send()

	@script(description="Switches to the next page in the sidebar", gesture="kb:control+tab")
	def script_nextPage(self, gesture):
		self._switchPage(gesture, 1)

	@script(description="Switches to the previous page in the sidebar", gesture="kb:control+shift+tab")
	def script_previousPage(self, gesture):
		self._switchPage(gesture, -1)

	def _switchPage(self, gesture, direction):
		focused = self._focusedElement()
		order = self._snapshotOrder(focused) if focused is not None else None
		if order is None:
			gesture.send()
			return
		pages = [
			n for n in order
			if n.controlType == UIAClient.UIA_RadioButtonControlTypeId and n.hasAncestorNamed("sidebar")
		]
		if not pages:
			ui.message("No pages")
			return
		current = 0
		for i, page in enumerate(pages):
			selection = _pattern(
				page.element, UIAClient.UIA_SelectionItemPatternId, UIAClient.IUIAutomationSelectionItemPattern
			)
			if selection and selection.CurrentIsSelected:
				current = i
				break
		page = pages[(current + direction) % len(pages)]
		invoke = _pattern(page.element, UIAClient.UIA_InvokePatternId, UIAClient.IUIAutomationInvokePattern)
		if invoke:
			invoke.Invoke()
		self._focus(page.element)


def _previousLabel(obj):
	sibling = obj.previous
	while sibling is not None:
		name = sibling.name or ""
		if sibling.role == Role.STATICTEXT and name.strip() and not NOT_A_LABEL.search(name):
			return name
		sibling = sibling.previous
	parent = obj.parent
	if parent is not None and isinstance(parent, LayoutContainer) and parent.automationName:
		return _humanize(parent.automationName)
	return None


def _rawSiblings(element):
	"""([(controlType, name), ...] for the element and its siblings, the element's index)."""
	client = _client()
	parent = client.RawViewWalker.GetParentElement(element)
	if not parent:
		return [], -1
	kids = _rawChildren(parent)
	items = [(k.CurrentControlType, k.CurrentName or "") for k in kids]
	index = next((i for i, k in enumerate(kids) if client.CompareElements(k, element)), -1)
	return items, index


def _folderButtonName(element):
	""""Change folder" / "Reset to default" for a Settings folder row's Move / Default button."""
	items, index = _rawSiblings(element)
	if index < 0:
		return None
	for i in range(index - 1, -1, -1):
		row = _folderRow(items, i)
		if row:
			return FOLDER_BUTTON_NAMES.get(items[index][1].strip().lower()) if index in row[1] else None
	return None


ACTIONS_SUFFIX = " actions"


def _packName(listItem):
	"""A pack card holds "<pack> <status>" and "<pack> actions" buttons. Taking the name from the
	actions button means any status the app shows (installed, download, progress...) splits off cleanly.
	Reads raw UIA so it never touches our overlay classes."""
	for child in _rawChildren(listItem):
		if child.CurrentControlType == UIAClient.UIA_ButtonControlTypeId:
			name = child.CurrentName or ""
			if name.endswith(ACTIONS_SUFFIX):
				return name[: -len(ACTIONS_SUFFIX)]
	return None


def _valueText(obj, steps=("next", "previous")):
	"""The value (path, version) belonging to the button's row: the nearest text after it, else before it."""
	for step in steps:
		sibling = getattr(obj, step)
		while sibling is not None:
			if sibling.role == Role.STATICTEXT:
				name = sibling.name or ""
				if NOT_A_LABEL.search(name) and name.strip():
					return name
				break
			sibling = getattr(sibling, step)
	return None


class ListSection(UIA):
	"""Items in the content list are named "1", "2", ...; name them after what they hold."""

	def _get_name(self):
		name = super().name or ""
		if name and not name.strip().isdigit():
			return name
		return self._label() or name

	def _label(self):
		try:
			pack = _packName(self.UIAElement)
		except COMError:
			pack = None
		if pack:
			return pack
		child = self.firstChild
		depth = 0
		while child is not None and depth < 2:
			if isinstance(child, LayoutContainer) and child.automationName:
				return _humanize(child.automationName)
			if child.role in (Role.STATICTEXT, Role.BUTTON) and child.name:
				return PACK_SUFFIX.sub("", child.name)
			if child.next is not None:
				child = child.next
			else:
				child, depth = child.firstChild, depth + 1
		return None

	_cache_isPresentableFocusAncestor = True

	def _get_isPresentableFocusAncestor(self):
		"""Announce a section on entry only when its name is otherwise invisible to NVDA: the
		Settings headings ("File Locations"...) are drawn but not exposed. "Plugin", "Expansions"
		and pack names already appear as text or in the control names."""
		label = self.name
		if not label:
			return False
		try:
			if _packName(self.UIAElement):
				return False
			client = _client()
			cond = client.CreateAndCondition(
				client.CreatePropertyCondition(UIAClient.UIA_ControlTypePropertyId, UIAClient.UIA_TextControlTypeId),
				client.CreatePropertyCondition(UIAClient.UIA_NamePropertyId, label),
			)
			return not self.UIAElement.FindFirst(UIAClient.TreeScope_Descendants, cond)
		except COMError:
			return True

	# The list is a grid of selectable items to JUCE; NVDA would add "not selected" and "row 3".
	def _get_states(self):
		return super().states - {State.SELECTABLE, State.SELECTED}

	def _get_positionInfo(self):
		return {}

	def _get_rowNumber(self):
		raise NotImplementedError

	def _get_columnNumber(self):
		raise NotImplementedError

	def _get_rowCount(self):
		raise NotImplementedError

	def _get_columnCount(self):
		raise NotImplementedError

	def _get_table(self):
		raise NotImplementedError


class ContentList(UIA):
	"""The content area's list. Saying "list" on entry adds nothing."""

	def _get_isPresentableFocusAncestor(self):
		return False


class SearchField(UIA):
	def _get_name(self):
		return super().name or "Search"


class LabeledButton(UIA):
	"""Give row context to buttons that need it, and drop JUCE's meaningless toggle state.

	"Default", "Move" and "menu" mean nothing alone: they become "User Folder Default", "Plugin Menu".
	The plugin row's status button ("Install", "Latest Version") exposes a toggle pattern, so NVDA
	would call it checked; it becomes "Plugin, Latest Version, 5.5.21".
	"""

	_cache_isStatusButton = True

	def _get_isStatusButton(self):
		try:
			return bool(self.UIAElement.GetCurrentPattern(UIAClient.UIA_TogglePatternId))
		except COMError:
			return False

	_cache_folderButtonName = True

	def _get_folderButtonName(self):
		if (super().name or "").strip().lower() not in FOLDER_BUTTON_NAMES:
			return None
		try:
			return _folderButtonName(self.UIAElement)
		except COMError:
			return None

	def _isGeneric(self):
		return (super().name or "").strip().lower() in GENERIC_BUTTON_NAMES

	def _packParts(self, name):
		"""("Christmas 2017", "installed") for a pack card button, else None."""
		try:
			parent = _client().RawViewWalker.GetParentElement(self.UIAElement)
			if not parent or parent.CurrentControlType != UIAClient.UIA_ListItemControlTypeId:
				return None
			pack = _packName(parent)
		except COMError:
			return None
		if pack and name.startswith(pack) and name[len(pack):].strip():
			return pack, name[len(pack):].strip()
		return None

	def _helpDetails(self):
		"""The user menu's help text is "reFX account\\n#<account>\\n#<computer>"; return the # lines."""
		help = super().description or ""
		return [line.lstrip("#").strip() for line in help.splitlines() if line.startswith("#") and line.strip("#").strip()]

	def _get_name(self):
		name = super().name or ""
		details = self._helpDetails()
		if details:
			return ", ".join([name, *details])
		parts = self._packParts(name)
		if parts:
			pack, status = parts
			if status.lower() == ACTIONS_SUFFIX.strip():
				return f"Actions for {pack}"
			return f"{pack}, {status[:1].upper()}{status[1:]}"
		if self.folderButtonName:
			return self.folderButtonName
		if self.isStatusButton:
			parts = [_previousLabel(self), name, _valueText(self)]
			return ", ".join(p for p in parts if p)
		if self._isGeneric():
			label = _previousLabel(self)
			if label:
				return f"{label} {name}"
		return name

	def _get_description(self):
		description = super().description
		if self._helpDetails() or self.folderButtonName:
			return None  # already read as part of the name, or by the folder label before it
		if not description and self._isGeneric():
			# Only a value after the button belongs to it (the folder path under Default/Move);
			# the version before the plugin Menu button belongs to the status button.
			return _valueText(self, steps=("next",))
		return description

	def _get_role(self):
		role = super().role
		return Role.BUTTON if role == Role.TOGGLEBUTTON else role

	def _get_states(self):
		return super().states - {State.CHECKED, State.PRESSED, State.CHECKABLE, State.HALFCHECKED}

	def _get_value(self):
		return None


class FolderLabel(UIA):
	"""A Settings folder label reads with its path: "User Folder, C:\\...\\User Content\\"."""

	_cache_folderPath = True

	def _get_folderPath(self):
		try:
			items, index = _rawSiblings(self.UIAElement)
		except COMError:
			return None
		row = _folderRow(items, index) if index >= 0 else None
		return row[0] if row else None

	def _get_name(self):
		name = super().name or ""
		path = self.folderPath
		return f"{name}, {path}" if path else name

	def _get_value(self):
		# JUCE gives text a value pattern holding its own text, which NVDA reads after the name.
		return None if self.folderPath else super().value


class ToggleControl(UIA):
	"""JUCE gives checkboxes and radio buttons a read-only "On"/"Off" value pattern, so NVDA calls
	them read-only. The checked state comes from the toggle/selection pattern, which works."""

	def _get_states(self):
		return super().states - {State.READONLY}

	def _get_value(self):
		return None


class LayoutContainer(UIA):
	"""JUCE layout components. Their names are internal ids, and the list items carry the context."""

	@property
	def automationName(self):
		return super().name or ""

	def _get_isPresentableFocusAncestor(self):
		return False


def _hasToggle(obj):
	try:
		return bool(obj.UIAElement.GetCurrentPattern(UIAClient.UIA_TogglePatternId))
	except COMError:
		return False


def _rawChildren(element):
	"""Child UIA elements, read straight from UIA. Never use NVDA object properties like role here:
	those run our overlay classes, which would ask for siblings again and recurse forever.
	comtypes returns a NULL pointer (falsy, but not None) at the end of the list."""
	walker = _client().RawViewWalker
	children = []
	child = walker.GetFirstChildElement(element)
	while child:
		children.append(child)
		child = walker.GetNextSiblingElement(child)
	return children


class GroupedMenuItem(UIA):
	"""Menu items in a menu that has a ticked item are read as radio items.

	reFX Cloud's ticked menus are pick-one lists: the Filter menu (Owned through Outdated is one
	group, despite the visual gap after Installed) and the sort order. Picking an item moves the
	tick, and nothing can be unticked, so "checked" checkbox wording is misleading. The app
	doesn't expose group boundaries, so the whole menu is treated alike.
	"""

	_cache_isRadio = True

	def _get_isRadio(self):
		try:
			parent = _client().RawViewWalker.GetParentElement(self.UIAElement)
			return bool(parent) and any(
				c.CurrentControlType == UIAClient.UIA_MenuItemControlTypeId
				and c.GetCurrentPattern(UIAClient.UIA_TogglePatternId)
				for c in _rawChildren(parent)
			)
		except COMError:
			return False

	def _get_role(self):
		return Role.RADIOMENUITEM if self.isRadio else super().role

	def _get_states(self):
		states = super().states
		if self.isRadio:
			states = states - {State.CHECKABLE}
			if _hasToggle(self):
				states = states | {State.CHECKED}
		return states


class AppWindow(UIA):
	_cache_isPopupMenu = True

	def _get_isPopupMenu(self):
		try:
			first = _client().RawViewWalker.GetFirstChildElement(self.UIAElement)
			return bool(first) and first.CurrentControlType == UIAClient.UIA_MenuItemControlTypeId
		except COMError:
			return False

	def _get_role(self):
		return Role.POPUPMENU if self.isPopupMenu else super().role

	def event_gainFocus(self):
		super().event_gainFocus()
		if self.isPopupMenu:
			# JUCE opens menus with nothing highlighted; select the first item so it gets read.
			KeyboardInputGesture.fromName("downArrow").send()
