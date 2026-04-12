
# Copyright 2026 - Markdown flavor conversion support

'''Dialog for converting a page from one format/flavor to another.

Inspects the current page's parse tree for elements that would be lossy
in the target format or flavor and shows specific warnings before
performing the conversion.
'''

import logging

logger = logging.getLogger('zim.gui.pageformatdialog')

from gi.repository import Gtk

from zim.gui.widgets import Dialog, BrowserTreeView
from zim.formats import MARK, STRIKE, SUBSCRIPT, SUPERSCRIPT, TABLE, ANCHOR, TAG, \
	VERBATIM_BLOCK, LISTITEM, OBJECT, get_dumper, \
	UNCHECKED_BOX, XCHECKED_BOX, CHECKED_BOX, MIGRATED_BOX, TRANSMIGRATED_BOX

from zim.formats.markdown import (
	FLAVOR_PANDOC, FLAVOR_GFM, FLAVOR_GLFM, FLAVOR_PHP_EXTRA, FLAVOR_RMARKDOWN,
	FLAVOR_ORIGINAL, FLAVOR_CONFIGS,
	FLAVORS, format_string_for_flavor,
	Parser as MarkdownParser, Dumper as MarkdownDumper,
)


# ---- Lossiness detection ----

_CHECKBOX_BULLETS = frozenset((
	UNCHECKED_BOX, XCHECKED_BOX, CHECKED_BOX, MIGRATED_BOX, TRANSMIGRATED_BOX
))

#: Human-readable label for each lossy element tag
_LOSSY_ELEMENT_LABELS = {
	MARK:          _('Underline / mark formatting'),           # T: lossy element label
	STRIKE:        _('Strikethrough formatting'),              # T: lossy element label
	SUBSCRIPT:     _('Subscript text'),                       # T: lossy element label
	SUPERSCRIPT:   _('Superscript text'),                     # T: lossy element label
	TABLE:         _('Tables'),                               # T: lossy element label
	ANCHOR:        _('Named anchors ({#name})'),              # T: lossy element label
	TAG:           _('Zim tags (@tagname)'),                  # T: lossy element label
	'task-list':   _('Checkbox / task list items'),           # T: lossy element label
	'code-lang':   _('Fenced code block language annotations'),  # T: lossy element label
}


def find_lossy_elements(tree, target_format, target_flavor=None):
	'''Walk a parse tree and return elements that would be lossy in the target.

	@param tree: a L{zim.formats.ParseTree}
	@param target_format: format name string, e.g. "markdown" or "zim-wiki"
	@param target_flavor: flavor string for markdown, e.g. "gfm"
	@returns: set of tag name strings that have lossy elements
	'''
	lossy = set()

	if target_format == 'markdown' and target_flavor in FLAVOR_CONFIGS:
		cfg = FLAVOR_CONFIGS[target_flavor]
		tag_flags = {
			MARK:        cfg.mark,
			STRIKE:      cfg.strikethrough,
			SUBSCRIPT:   cfg.subscript,
			SUPERSCRIPT: cfg.superscript,
			TABLE:       cfg.tables,
			ANCHOR:      cfg.anchors,
			TAG:         cfg.zim_tags,
		}
		for token in tree.iter_tokens():
			tag = token[0]
			attrib = token[1] if len(token) > 1 else None
			if tag in tag_flags and not tag_flags[tag]:
				lossy.add(tag)
			# Checkbox list items: stored as <li bullet="*-box"> attributes
			if tag == LISTITEM and attrib and not cfg.task_lists:
				if attrib.get('bullet') in _CHECKBOX_BULLETS:
					lossy.add('task-list')
			# Fenced code language annotations are lost when fenced_code=False
			# (Original flavor falls back to 4-space indentation without lang tag)
			if tag == VERBATIM_BLOCK and attrib and not cfg.fenced_code:
				if attrib.get('lang'):
					lossy.add('code-lang')
	elif target_format == 'zim-wiki':
		# zim-wiki supports all standard elements; no lossiness for supported markdown
		pass

	return lossy


# ---- Format/flavor description helpers ----

def _format_label(fmt, flavor=None):
	if fmt == 'zim-wiki':
		return _('Zim Wiki')   # T: format name
	elif fmt == 'markdown':
		labels = {
			FLAVOR_PANDOC:    _('Markdown — Pandoc extensions'),        # T: flavor name
			FLAVOR_GFM:       _('Markdown — GitHub Flavored (GFM)'),    # T: flavor name
			FLAVOR_GLFM:      _('Markdown — GitLab Flavored (GLFM)'),   # T: flavor name
			FLAVOR_PHP_EXTRA: _('Markdown — PHP Markdown Extra'),       # T: flavor name
			FLAVOR_RMARKDOWN: _('Markdown — R Markdown'),               # T: flavor name
			FLAVOR_ORIGINAL:  _('Markdown — Original (Daring Fireball)'),  # T: flavor name
		}
		return labels.get(flavor, 'Markdown')
	return fmt


def _current_page_format(page):
	'''Return (format_name, flavor) for the current on-disk page.'''
	if page.source_file.path.endswith('.md'):
		# Try reading the Format: header
		try:
			text = page.source_file.read()
		except Exception:
			return 'markdown', FLAVOR_PANDOC
		from zim.formats.markdown import parse_yaml_front_matter, flavor_from_format_string
		_, meta = parse_yaml_front_matter(text)
		flavor = flavor_from_format_string(meta.get('Format', ''))
		return 'markdown', flavor
	else:
		return 'zim-wiki', None


# ---- Dialog ----

class PageFormatDialog(Dialog):
	'''Dialog to convert a page to a different format or markdown flavor.

	Shows the current format, a target selector, and specific lossiness
	warnings. On confirmation, rewrites the page in the target format.
	'''

	def __init__(self, parent, notebook, page):
		Dialog.__init__(self, parent, _('Convert Page Format'),  # T: dialog title
			button=_('Convert'),  # T: dialog button
			help='Help:Properties',
		)
		self.notebook = notebook
		self.page = page

		# Current format
		cur_format, cur_flavor = _current_page_format(page)
		cur_label = _format_label(cur_format, cur_flavor)

		info_label = Gtk.Label()
		info_label.set_markup(
			_('<b>Current format:</b> %s') % cur_label  # T: label in convert dialog
		)
		info_label.set_halign(Gtk.Align.START)
		self.vbox.pack_start(info_label, False, False, 6)

		# Default notebook format
		def_format = notebook.config['Notebook'].get('default_file_format', 'zim-wiki')
		def_flavor = notebook.config['Notebook'].get('markdown_flavor', 'gfm') \
			if def_format == 'markdown' else ''

		# Target format selector — exclude current format; mark default with "(default)"
		target_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
		target_label = Gtk.Label(label=_('Convert to:'))  # T: label in convert dialog
		target_label.set_halign(Gtk.Align.START)
		target_box.pack_start(target_label, False, False, 0)

		from zim.formats import _MARKDOWN_EXPORT_FLAVOR_MAP
		self._target_store = Gtk.ListStore(str, str, str)  # (format, flavor, label)

		def _is_current(fmt, flv):
			return fmt == cur_format and (flv or '') == (cur_flavor or '')

		def _is_default(fmt, flv):
			return fmt == def_format and (flv or '') == (def_flavor or '')

		def _entry_label(fmt, flv):
			label = _format_label(fmt, flv)
			if _is_default(fmt, flv):
				label += ' ' + _('(default)')  # T: suffix for default format in combo
			return label

		default_idx = 0
		for fmt, flv in [('zim-wiki', '')] + [('markdown', f) for f in _MARKDOWN_EXPORT_FLAVOR_MAP.values()]:
			if _is_current(fmt, flv):
				continue  # omit current format from target list
			if _is_default(fmt, flv):
				default_idx = len(self._target_store)
			self._target_store.append([fmt, flv, _entry_label(fmt, flv)])

		self._target_combo = Gtk.ComboBox(model=self._target_store)
		renderer = Gtk.CellRendererText()
		self._target_combo.pack_start(renderer, True)
		self._target_combo.set_entry_text_column(2)
		self._target_combo.add_attribute(renderer, 'text', 2)
		self._target_combo.set_active(default_idx)
		self._target_combo.connect('changed', self._on_target_changed)
		target_box.pack_start(self._target_combo, False, False, 0)
		self.vbox.pack_start(target_box, False, False, 0)

		# Warnings area
		self._warnings_label = Gtk.Label()
		self._warnings_label.set_halign(Gtk.Align.START)
		self._warnings_label.set_line_wrap(True)
		self._warnings_label.set_margin_top(8)
		self.vbox.pack_start(self._warnings_label, False, False, 0)

		self.vbox.show_all()
		self._update_warnings()

	def _get_target(self):
		it = self._target_combo.get_active_iter()
		if it is None:
			return None, None
		row = self._target_store[it]
		return row[0], row[1] or None

	def _on_target_changed(self, combo):
		self._update_warnings()

	def _update_warnings(self):
		fmt, flavor = self._get_target()
		if fmt is None:
			self._warnings_label.set_text('')
			return

		tree = self.page.get_parsetree()
		if tree is None:
			self._warnings_label.set_text('')
			return

		lossy = find_lossy_elements(tree, fmt, flavor)
		if lossy:
			lines = [_('<b>Warning — the following will be converted to plain text:</b>')]  # T: warning header
			for tag in sorted(lossy):
				label = _LOSSY_ELEMENT_LABELS.get(tag, tag)
				lines.append('  • ' + label)
			self._warnings_label.set_markup('\n'.join(lines))
		else:
			self._warnings_label.set_text(
				_('No data will be lost in this conversion.')  # T: no-loss message
			)

	def do_response_ok(self):
		fmt, flavor = self._get_target()
		if fmt is None:
			return False

		tree = self.page.get_parsetree()
		if tree is None:
			return True  # nothing to convert

		try:
			_convert_page_tree(self.page, tree, fmt, flavor)
		except Exception as e:
			logger.exception('Failed to convert page %s', self.page.name)
			from zim.gui.widgets import ErrorDialog
			ErrorDialog(self, e).run()
			return False

		self.result = True
		return True


def _convert_page_tree(page, tree, target_format, target_flavor):
	'''Re-dump a page's parse tree in the target format and save it.

	This changes both the file extension and file content.  The page
	object's source_file and format are updated accordingly.

	@param page: a L{zim.notebook.page.Page}
	@param tree: the current L{zim.formats.ParseTree}
	@param target_format: "zim-wiki" or "markdown"
	@param target_flavor: flavor string or None
	'''
	import os
	from zim.formats import get_format_module, FormatConfig
	from zim.newfs import LocalFile

	if target_format == 'markdown':
		flavor = target_flavor or FLAVOR_GFM
		mod = get_format_module('markdown')
		fmt_obj = FormatConfig(mod, default_flavor=flavor)
		new_ext = '.md'
	else:
		fmt_obj = get_format_module('zim-wiki')
		new_ext = '.txt'

	# Determine new file path
	old_path = page.source_file.path
	base, old_ext = os.path.splitext(old_path)
	new_path = base + new_ext

	# Dump with new format
	dumper = fmt_obj.Dumper()
	lines = dumper.dump(tree, file_output=True)

	# Write new file
	new_file = LocalFile(new_path)
	new_file.writelines(lines)

	# Remove old file if extension changed
	if old_path != new_path and os.path.exists(old_path):
		os.remove(old_path)

	# Update page object to point at the new file and format
	page.source_file = new_file
	page.format = fmt_obj
	page._parsetree = None
	page._meta = None
	page._last_etag = None

	logger.info('Converted page %s to %s (%s)', page.name, target_format, target_flavor)
