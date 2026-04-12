
# Copyright 2008-2018 Jaap Karssenberg <jaap.karssenberg@gmail.com>

import logging

logger = logging.getLogger('zim.gui')


from gi.repository import Gtk

from zim.plugins import PluginManager
from zim.gui.widgets import Dialog, get_window, InputForm
from zim.parse.links import is_interwiki_keyword_re

notebook_properties = (
	('name', 'string', _('Name')), # T: label for properties dialog
	('interwiki', 'string', _('Interwiki Keyword'), lambda v: not v or is_interwiki_keyword_re.search(v)), # T: label for properties dialog
	('home', 'page', _('Home Page')), # T: label for properties dialog
	('icon', 'image', _('Icon')), # T: label for properties dialog
	('document_root', 'dir', _('Document Root')), # T: label for properties dialog
	('short_links', 'bool', _('Prefer short names for page links'), False), # T: label for properties dialog
	('disable_trash', 'bool', _('Do not use system trash for this notebook'), False), # T: label for properties dialog
	('paste_image_template', 'string', _('Filename template for pasted images')),
	# 'shared' property is not shown in properties anymore
	# 'default_file_format' is handled by NotebookFormatWidget, not listed here
)

class NotebookFormatWidget(Gtk.VBox):
	'''Reusable widget for notebook storage-format settings.

	Provides an "Advanced --EXPERIMENTAL--" toggle that gates the three
	format fields: C{use_all_formats}, C{default_file_format}, and
	C{markdown_flavor}.  Embed in any dialog that manages notebook format
	settings; call L{get_values()} to retrieve the current state.
	'''

	_FORMAT_INPUTS = (
		('use_all_formats', 'bool', _('Use all supported formats (do not convert pages on format change, opens all supported text files as wiki pages)')), # T: label for format widget
		('default_file_format', 'choice', _('Storage format'), # T: label for format widget
			[('zim-wiki', _('Zim Wiki')), ('markdown', _('Markdown'))]),
		('markdown_flavor', 'choice', _('Markdown flavor'), # T: label for format widget
			[
				('pandoc',    _('Pandoc')),
				('gfm',       _('GitHub Flavored (GFM)')),
				('glfm',      _('GitLab Flavored (GLFM)')),
				('php-extra', _('PHP Markdown Extra')),
				('rmarkdown', _('R Markdown')),
				('original',  _('Original (Daring Fireball)')),
			]),
	)

	_FORMAT_DEFAULTS = {
		'use_all_formats': False,
		'default_file_format': 'zim-wiki',
		'markdown_flavor': 'gfm',
	}

	def __init__(self, values=None):
		Gtk.VBox.__init__(self)

		_init = dict(self._FORMAT_DEFAULTS)
		if values:
			for k in self._FORMAT_DEFAULTS:
				if k in values:
					_init[k] = values[k]

		self._advanced_cb = Gtk.CheckButton(
			label=_('Advanced  --EXPERIMENTAL--')  # T: checkbox label
		)
		self._advanced_cb.set_active(False)
		self.pack_start(self._advanced_cb, False, False, 4)

		self.format_form = InputForm(inputs=self._FORMAT_INPUTS, values=_init)
		self.pack_start(self.format_form, False, False, 0)

		# Rename "Storage format:" ↔ "Default storage format:" dynamically
		_storage_label = None
		_target = _('Storage format') + ':'  # T: label for format widget
		for child in self.format_form.get_children():
			if isinstance(child, Gtk.Label) and child.get_text() == _target:
				_storage_label = child
				break

		def _update_storage_label(*a):
			if _storage_label is None:
				return
			if self.format_form.widgets['use_all_formats'].get_active():
				_storage_label.set_text(_('Default storage format') + ':')  # T: label for format widget
			else:
				_storage_label.set_text(_('Storage format') + ':')  # T: label for format widget

		def _update_flavor_sensitivity(*a):
			advanced = self._advanced_cb.get_active()
			is_markdown = (self.format_form['default_file_format'] == 'markdown')
			self.format_form.widgets['markdown_flavor'].set_sensitive(advanced and is_markdown)

		def _update_format_sensitivity(*a):
			advanced = self._advanced_cb.get_active()
			self.format_form.widgets['use_all_formats'].set_sensitive(advanced)
			self.format_form.widgets['default_file_format'].set_sensitive(advanced)
			_update_flavor_sensitivity()

		_update_storage_label()
		_update_format_sensitivity()
		self.format_form.widgets['use_all_formats'].connect('toggled', _update_storage_label)
		self._advanced_cb.connect('toggled', _update_format_sensitivity)
		self.format_form.widgets['default_file_format'].connect('changed', _update_flavor_sensitivity)

	def get_values(self):
		'''Return dict with C{use_all_formats}, C{default_file_format}, C{markdown_flavor}.'''
		return self.format_form.copy()


# Keep as a module-level constant so existing tests / external code can iterate
# over the property metadata (e.g. to verify documentation coverage).
notebook_format_properties = NotebookFormatWidget._FORMAT_INPUTS


class PropertiesDialog(Dialog):

	def __init__(self, parent, notebook, chosen_plugin=None):
		Dialog.__init__(self, parent, _('Properties'), help='Help:Properties') # T: Dialog title
		self.notebook = notebook

		stack = Gtk.Stack()
		sidebar = Gtk.StackSidebar()
		sidebar.set_stack(stack)

		hbox = Gtk.Box()
		hbox.add(sidebar)
		hbox.add(stack)
		self.vbox.add(hbox)

		def add_widget(form, name, title):
			if chosen_plugin and chosen_plugin != name:
				return
			if self.notebook.readonly:
				for widget in list(form.widgets.values()):
					widget.set_sensitive(False)
			box = Gtk.VBox()
			box.pack_start(form, False, False, 0)
			stack.add_titled(box, name, title)

		self.form = InputForm(
			inputs=notebook_properties,
			values=notebook.config['Notebook']
		)
		self.form.widgets['icon'].set_use_relative_paths(self.notebook)
		self.form.widgets['document_root'].set_use_relative_paths(self.notebook)

		# Format settings fragment — Advanced checkbox + three format fields
		self._format_widget = NotebookFormatWidget(notebook.config['Notebook'])

		# Build the notebook tab: general form, then format fragment
		if not chosen_plugin or chosen_plugin == 'notebook':
			nb_box = Gtk.VBox()
			nb_box.pack_start(self.form, False, False, 0)
			nb_box.pack_start(self._format_widget, False, False, 0)
			if self.notebook.readonly:
				for widget in list(self.form.widgets.values()):
					widget.set_sensitive(False)
				self._format_widget.set_sensitive(False)
			stack.add_titled(nb_box, 'notebook', _('Notebook'))

		self.plugin_forms = {}
		plugins = PluginManager()
		for name in plugins:
			plugin = plugins[name]
			if plugin.plugin_notebook_properties:
				key = plugin.config_key
				form = InputForm(
					inputs=plugin.form_fields(plugin.plugin_notebook_properties),
					values=notebook.config[key]
				)
				self.plugin_forms[key] = form
				add_widget(form, name, plugin.plugin_info['name'])

	def do_response_ok(self):
		if not self.notebook.readonly:
			old_format = self.notebook.config['Notebook']['default_file_format']
			if old_format == "zim-wiki":
				old_flavor = ""
			else:
				old_flavor = self.notebook.config['Notebook'].get('markdown_flavor', 'gfm')
			old_use_all = self.notebook.config['Notebook'].get('use_all_formats', False)

			properties = self.form.copy()
			properties['icon'] = self.form.widgets['icon'].get_text() # XXX should be file, but resolves relative
			properties['document_root'] = self.form.widgets['document_root'].get_text() # XXX should be file, but resolves relative
			properties.update(self._format_widget.get_values())

			new_format = properties['default_file_format']
			if new_format == "zim-wiki":
				new_flavor = ""
			else:
				new_flavor = properties.get('markdown_flavor', 'gfm')
			
			new_use_all = properties.get('use_all_formats', False)
			format_changed = (old_format != new_format or old_flavor != new_flavor)

			# Convert pages BEFORE updating notebook properties so that
			# notebook.get_page() still resolves files with the old extension.
			# _offer_notebook_conversion() is synchronous and returns True when
			# the user confirmed and conversion ran, False when cancelled.
			conversion_done = False
			if not new_use_all and format_changed \
					and (old_format == 'markdown' or new_format == 'markdown'):
				conversion_done = _offer_notebook_conversion(
					self, self.notebook,
					old_format, old_flavor,
					new_format, new_flavor,
				)

			self.notebook.properties.update(properties)

			for key, form in self.plugin_forms.items():
				self.notebook.config[key].update(form)

			if hasattr(self.notebook.config, 'write'): # XXX Check needed for tests
				logger.debug('Write notebook properties')
				self.notebook.config.write()

			if new_use_all and (format_changed or new_use_all != old_use_all):
				# Use-all-formats mode: flush index and rebuild — no conversion
				_save_and_rebuild_index(self, self.notebook)
			elif conversion_done:
				# Files on disk were rewritten; rebuild index to reflect new paths
				_save_and_rebuild_index(self, self.notebook)

		return True


def _save_and_rebuild_index(parent_dialog, notebook):
	'''Save the current page, flush the index, and rebuild it.

	Called when use_all_formats is enabled so newly-eligible files are
	discovered without converting any page content.
	'''
	main_window = get_window(parent_dialog)
	if main_window and hasattr(main_window, 'pageview'):
		main_window.pageview.save_changes()

	notebook.index.flush()

	from zim.notebook.index import IndexUpdateOperation
	from zim.gui.widgets import ProgressDialog
	ProgressDialog(parent_dialog, IndexUpdateOperation(notebook)).run()


def _offer_notebook_conversion(parent_dialog, notebook, old_format, old_flavor, new_format, new_flavor):
	'''Show a confirmation dialog and, if accepted, convert all pages.

	@param parent_dialog: the PropertiesDialog that triggered this
	@param notebook: the L{Notebook} object
	@param old_format: previous storage format name
	@param old_flavor: previous markdown flavor
	@param new_format: new storage format name
	@param new_flavor: new markdown flavor
	'''
	from zim.gui.pageformatdialog import _format_label, find_lossy_elements

	# Save the currently open page so on-disk content is up to date
	main_window = get_window(parent_dialog)
	if main_window and hasattr(main_window, 'pageview'):
		main_window.pageview.save_changes()

	old_label = _format_label(old_format, old_flavor)
	new_label = _format_label(new_format, new_flavor)

	# Count pages and collect per-page lossiness
	page_count = 0
	page_losses = {}  # {page_name: set_of_lossy_tags}
	for page_info in notebook.pages.walk():
		page_count += 1
		page = notebook.get_page(page_info)
		tree = page.get_parsetree()
		if tree:
			lossy = find_lossy_elements(tree, new_format, new_flavor)
			if lossy:
				page_losses[page_info.name] = lossy

	if page_count == 0:
		return False  # nothing to convert

	if not NotebookConversionPreviewDialog(
		parent_dialog, old_label, new_label, page_count, page_losses
	).run():
		return False  # user cancelled

	# Run conversion with a progress dialog (synchronous)
	_convert_all_pages(parent_dialog, notebook, new_format, new_flavor)
	return True


class NotebookConversionPreviewDialog(Dialog):
	'''Dialog showing a summary of what will happen during notebook conversion.

	Lists pages that will lose formatting and warns that the operation
	cannot be undone.
	'''

	def __init__(self, parent, old_label, new_label, page_count, page_losses):
		Dialog.__init__(self, parent, _('Convert Notebook'),  # T: dialog title
			button=_('Convert'),  # T: dialog button
		)

		# No-undo warning
		warning = Gtk.Label()
		warning.set_markup(
			'<b>' + _('Warning: This conversion cannot be undone.') + '</b>\n'  # T: conversion warning
			+ _('Make a backup of your notebook before proceeding.')  # T: backup advice
		)
		warning.set_halign(Gtk.Align.START)
		warning.set_line_wrap(True)
		warning.set_margin_bottom(8)
		self.vbox.pack_start(warning, False, False, 0)

		# Summary line
		summary = Gtk.Label()
		summary.set_markup(
			_('Converting <b>%(n)d</b> pages from %(old)s to %(new)s.')  # T: conversion summary
			% {'n': page_count, 'old': old_label, 'new': new_label}
		)
		summary.set_halign(Gtk.Align.START)
		summary.set_line_wrap(True)
		self.vbox.pack_start(summary, False, False, 0)

		if not page_losses:
			no_loss = Gtk.Label(label=_('No formatting will be lost.'))  # T: no-loss message
			no_loss.set_halign(Gtk.Align.START)
			no_loss.set_margin_top(8)
			self.vbox.pack_start(no_loss, False, False, 0)
		else:
			from zim.gui.pageformatdialog import _LOSSY_ELEMENT_LABELS

			lossy_header = Gtk.Label()
			lossy_header.set_markup(
				'<b>' + _('%d page(s) will lose formatting:') % len(page_losses) + '</b>'  # T: lossy pages header
			)
			lossy_header.set_halign(Gtk.Align.START)
			lossy_header.set_margin_top(8)
			self.vbox.pack_start(lossy_header, False, False, 0)

			model = Gtk.ListStore(str, str)  # (page_name, losses)
			for name in sorted(page_losses):
				tags = page_losses[name]
				loss_str = ', '.join(
					_LOSSY_ELEMENT_LABELS.get(t, t) for t in sorted(tags)
				)
				model.append([name, loss_str])

			treeview = Gtk.TreeView(model=model)
			treeview.set_headers_visible(True)
			treeview.set_size_request(-1, 200)

			col_page = Gtk.TreeViewColumn(_('Page'), Gtk.CellRendererText(), text=0)  # T: column header
			col_page.set_expand(True)
			treeview.append_column(col_page)

			col_loss = Gtk.TreeViewColumn(_('Formatting lost'), Gtk.CellRendererText(), text=1)  # T: column header
			col_loss.set_expand(True)
			treeview.append_column(col_loss)

			from zim.gui.widgets import ScrolledWindow
			self.vbox.pack_start(ScrolledWindow(treeview), True, True, 0)

		self.vbox.show_all()

	def do_response_ok(self):
		self.result = True
		return True


def _convert_all_pages(parent, notebook, target_format, target_flavor):
	'''Convert every page in the notebook to the target format/flavor.

	Runs synchronously with a progress indicator.  The caller is responsible
	for rebuilding the index afterwards (files on disk are rewritten but
	notebook.store_page() is intentionally NOT called here to avoid index
	corruption before notebook properties have been updated).
	'''
	from zim.gui.pageformatdialog import _convert_page_tree

	pages = list(notebook.pages.walk())
	total = len(pages)
	errors = []
	logger.debug('_convert_all_pages to %s/%s', target_format, target_flavor)

	progress = Gtk.MessageDialog(
		parent=parent,
		modal=True,
		message_type=Gtk.MessageType.INFO,
		buttons=Gtk.ButtonsType.NONE,
		text=_('Converting pages…'),  # T: progress dialog title
	)
	progress.format_secondary_text('0 / %d' % total)
	progress.show()

	for idx, page_info in enumerate(pages):
		try:
			page = notebook.get_page(page_info)
			tree = page.get_parsetree()
			if tree:
				_convert_page_tree(page, tree, target_format, target_flavor)
				logger.debug('Converted page %s', page_info.name)
			else:
				logger.debug('Skipped page %s (no content)', page_info.name)
		except Exception:
			logger.exception('Failed to convert page %s', page_info.name)
			errors.append(page_info.name)

		progress.format_secondary_text('%d / %d' % (idx + 1, total))

	progress.destroy()

	if errors:
		msg = _('%(n)d page(s) could not be converted:\n%(pages)s') % {  # T: error summary
			'n': len(errors),
			'pages': '\n'.join(errors),
		}
		from zim.gui.widgets import ErrorDialog
		ErrorDialog(parent, msg).run()
	
