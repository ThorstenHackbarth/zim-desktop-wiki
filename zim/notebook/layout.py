
# Copyright 2008-2016 Jaap Karssenberg <jaap.karssenberg@gmail.com>


import re
import sys

from .page import Path

from zim.newfs import File, Folder, _EOL, SEP, FileNotFoundError
from zim.formats import get_format, get_format_module, FormatConfig

import zim.parse.links # we use "error=urlencode"

FILE_TYPE_PAGE_SOURCE = 1
FILE_TYPE_ATTACHMENT = 2

_fs_encoding = sys.getfilesystemencoding()

def encode_filename(pagename):
	'''Encode a pagename to a filename

	Since the filesystem may use another encoding than UTF-8 it may
	not be able to use all valid page names directly as file names.
	Therefore characters that are not allowed for the filesystem are
	replaced with url encoding. The result is still unicode, which can
	be used to construct a L{File} object. (The File object
	implementation takes care of actually encoding the string when
	needed.)

	Namespaces are mapped to directories by replacing ":" with "/".

	@param pagename: the pagename as string or unicode object
	@returns: the filename as unicode object but with characters
	incompatble with the filesystem encoding replaced
	'''
	assert not '%' in pagename # just to be sure
	pagename = pagename.encode(_fs_encoding, 'urlencode')
	pagename = pagename.decode(_fs_encoding)
	return pagename.replace(':', '/').replace(' ', '_')


_url_decode_re = re.compile('%([a-fA-F0-9]{2})')

def _url_decode(match):
	return chr(int(match.group(1), 16))


def decode_filename(filename):
	'''Decodes a filename to a pagename

	Reverse operation of L{encode_filename()}.

	@param filename: the filename as string or unicode object
	@returns: the pagename as unicode object
	'''
	filename = _url_decode_re.sub(_url_decode, filename)
	return filename.replace('\\', ':').replace('/', ':').replace('_', ' ')



class NotebookLayout(object):
	pass



class FilesLayout(NotebookLayout):
	'''Layout is responsible for mapping between pages and files.
	This is the most basic version, where each page maps to the
	like-named file.
	'''

	def __init__(self, folder, endofline=_EOL, default_format='wiki', default_extension='.txt', markdown_flavor=None, use_all_formats=False):
		'''Constructor
		@param folder: a L{Folder} object
		@param endofline: either "dos" or "unix", default per OS
		@param markdown_flavor: optional flavor for markdown notebooks
		  (one of FLAVOR_PANDOC, FLAVOR_GFM, FLAVOR_ORIGINAL)
		@param use_all_formats: when C{True} all supported text file
		  extensions (.txt, .md) are treated as page sources regardless
		  of the default extension
		'''
		assert isinstance(folder, Folder)
		self.root = folder
		self.endofline = endofline
		self._markdown_flavor = markdown_flavor
		self._use_all_formats = use_all_formats
		self.update_format(default_format, default_extension)

	def update_format(self, default_format, default_extension):
		if not default_extension.startswith('.'):
			default_extension = '.' + default_extension

		self.default_extension = default_extension

		raw_module = get_format_module(default_format)
		if default_format == 'markdown' and self._markdown_flavor:
			from zim.formats.markdown import FLAVOR_CONFIGS
			if self._markdown_flavor in FLAVOR_CONFIGS:
				self.default_format = FormatConfig(raw_module, default_flavor=self._markdown_flavor)
				return
		self.default_format = raw_module

	def update_use_all_formats(self, value):
		'''Update the use_all_formats flag.

		Called when the notebook use_all_formats property changes.
		'''
		self._use_all_formats = value

	def update_markdown_flavor(self, flavor):
		'''Update the markdown flavor without changing the format or extension.

		Called when the notebook markdown_flavor property changes.
		'''
		self._markdown_flavor = flavor
		if self.default_extension == '.md':
			self.update_format('markdown', self.default_extension)

	def _check_source_file_for_ext(self, file, ext):
		'''Check if file is a valid page source for a given extension.
		Returns True/False, or None if the extension does not match.
		'''
		if not file.path.endswith(ext):
			return None
		name = file.basename
		pname = decode_filename(name)
		if encode_filename(pname) != name: # reject e.g. whitespace in file name
			return False
		if ext == '.txt':
			try:
				line = file.readline(size=50)
				return line.strip() == 'Content-Type: text/x-zim-wiki'
			except FileNotFoundError:
				return True # give file the benefit of the doubt
		else: # .md or other
			return True

	def is_source_file(self, file):
		result = self._check_source_file_for_ext(file, self.default_extension)
		if result is not None:
			return result
		if self._use_all_formats:
			for ext in ('.txt', '.md'):
				if ext != self.default_extension:
					result = self._check_source_file_for_ext(file, ext)
					if result is not None:
						return result
		return False

	def map_page(self, pagename):
		'''Map a pagename to a (default) file
		@param pagename: a L{Path}
		@returns: a 2-tuple of a L{File} for the source and a L{Folder}
		for the attachments. Neither of these needs to exist.
		'''
		path = encode_filename(pagename.name)
		file = self.root.file(path + self.default_extension)
		file.endofline = self.endofline ## TODO, make this auto-detect for existing files ?
		folder = self.root.folder(path) if path else self.root
		return file, folder

	def get_attachments_folder(self, pagename):
		file, folder = self.map_page(pagename)
		return FilesAttachmentFolder(folder, self.is_source_file)

	def map_file(self, file):
		'''Map a filepath to a pagename
		@param file: a L{File} or L{FilePath} object
		@returns: a L{Path} and a file type (C{FILE_TYPE_PAGE_SOURCE},
		F{FILE_TYPE_ATTACHMENT})
		'''
		type = FILE_TYPE_PAGE_SOURCE if self.is_source_file(file) else FILE_TYPE_ATTACHMENT

		path = file.relpath(self.root)
		if type == FILE_TYPE_PAGE_SOURCE:
			for ext in (self.default_extension, '.txt', '.md'):
				if path.endswith(ext):
					path = path[:-len(ext)]
					break
		else: # FILE_TYPE_ATTACHMENT
			if SEP in path:
				path, x = path.rsplit(SEP, 1)
			else:
				path = ':' # ROOT_PATH

		if path == ':':
			return Path(':'), type
		else:
			name = decode_filename(path)
			Path.assertValidPageName(name)
			return Path(name), type

	def map_filepath(self, path):
		'''Like L{map_file} but takes a string with relative path'''
		return self.map_file(self.root.file(path))

	def resolve_conflict(self, *filepaths):
		'''Decide which is the real page file when multiple files
		map to the same page.
		@param filepaths: 2 or more L{FilePath} objects
		@returns: L{FilePath} that should take precedent as te page
		source
		'''
		filepaths.sort(key=lambda p: (p.ctime(), p.basename))
		return filepaths[0]

	def get_format(self, file):
		if file.path.endswith(self.default_extension):
			return self.default_format
		elif self._use_all_formats:
			if file.path.endswith('.txt'):
				return get_format_module('wiki')
			elif file.path.endswith('.md'):
				raw_module = get_format_module('markdown')
				if self._markdown_flavor:
					from zim.formats.markdown import FLAVOR_CONFIGS
					if self._markdown_flavor in FLAVOR_CONFIGS:
						return FormatConfig(raw_module, default_flavor=self._markdown_flavor)
				return raw_module
		raise AssertionError('Unknown file type for page: %s' % file.basename)

	def index_list_children(self, pagename):
		# Convenience method - remove if no longer used by the index
		file, folder = self.map_page(pagename)
		if not folder.exists():
			return []

		names = set()
		for object in folder:
			if isinstance(object, File):
				if self.is_source_file(object):
					name = object.basename[:-len(self.default_extension)]
				else:
					continue
			else: # Folder
				name = object.basename

			pname = decode_filename(name)
			if encode_filename(pname) == name: # will reject e.g. whitespace in file name
				names.add(pname)

		return [pagename + basename for basename in sorted(names)]


class FilesAttachmentFolder(object):

	def __init__(self, folder, is_source_file_func):
		self._inner_fs_object = folder
		self._is_source_file_func = is_source_file_func

	def __str__(self):
		return str(self._inner_fs_object)

	def __getattr__(self, name):
		return getattr(self._inner_fs_object, name)

	def __iter__(self):
		for obj in self._inner_fs_object:
			if isinstance(obj, File) \
			and not self._is_source_file_func(obj) \
			and not obj.basename.endswith('.zim'):
				yield obj

	def list_names(self):
		for obj in self.__iter__():
			yield obj.basename

	def list_files(self):
		return self.__iter__()

	def list_folders(self):
		return []
