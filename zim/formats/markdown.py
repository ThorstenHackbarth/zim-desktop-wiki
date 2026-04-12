
# Copyright 2012,2013 Jaap Karssenberg <jaap.karssenberg@gmail.com>
# Copyright 2026 - Markdown native format support

'''This module handles parsing and dumping markdown text with pandoc extensions.

It supports full round-trip as a native storage format: pages can be
stored as ``.md`` files with YAML front matter for metadata.
'''

import os.path
import re
import logging

logger = logging.getLogger('zim.formats.markdown')

from zim.parse import convert_space_to_tab, fix_unicode_whitespace
from zim.parse.encode import escape_string, split_escaped_string, unescape_string, encode_xml_attrib, decode_xml
from zim.parse.regexparser import Rule, RegexParser
from zim.parse.links import is_url_link, match_url_link, is_wiki_link, url_link_re, is_path_re

from zim.formats import *
from zim.formats.plain import Dumper as TextDumper


# Format header strings per flavor — referencing the actual spec versions:
#   GFM 0.31.2: based on CommonMark 0.31.2 (https://github.github.com/gfm/)
#   Pandoc: no frozen spec version, identified by name only
#   Original: Gruber's 2004 spec, no formal version number
_FORMAT_STRINGS = {}

# ---- Markdown flavor support ----

FLAVOR_PANDOC    = 'pandoc'
FLAVOR_GFM       = 'gfm'
FLAVOR_GLFM      = 'glfm'
FLAVOR_PHP_EXTRA = 'php-extra'
FLAVOR_RMARKDOWN = 'rmarkdown'
FLAVOR_ORIGINAL  = 'original'
FLAVORS = (FLAVOR_PANDOC, FLAVOR_GFM, FLAVOR_GLFM, FLAVOR_PHP_EXTRA, FLAVOR_RMARKDOWN, FLAVOR_ORIGINAL)


class MarkdownFlavorConfig(object):
	'''Feature flags for a markdown flavor.

	Each flag controls whether a specific markdown extension is
	enabled in the parser and dumper.
	'''

	def __init__(self,
		tables=True,
		task_lists=True,
		strikethrough=True,
		fenced_code=True,
		subscript=True,
		superscript=True,
		mark=True,
		anchors=True,
		pandoc_images=True,
		zim_tags=True,
	):
		self.tables        = tables
		self.task_lists    = task_lists
		self.strikethrough = strikethrough
		self.fenced_code   = fenced_code
		self.subscript     = subscript
		self.superscript   = superscript
		self.mark          = mark
		self.anchors       = anchors
		self.pandoc_images = pandoc_images
		self.zim_tags      = zim_tags


FLAVOR_CONFIGS = {
	FLAVOR_PANDOC: MarkdownFlavorConfig(),
	FLAVOR_GFM: MarkdownFlavorConfig(
		subscript=False,
		superscript=False,
		mark=False,
		anchors=False,
		pandoc_images=False,
		zim_tags=False,
	),
	# GitLab Flavored Markdown: GFM + named heading anchors ({#id} syntax).
	# Additional GLFM features (footnotes, definition lists, wiki links,
	# inline diffs, math) are not yet represented in the flag set.
	FLAVOR_GLFM: MarkdownFlavorConfig(
		subscript=False,
		superscript=False,
		mark=False,
		anchors=True,
		pandoc_images=False,
		zim_tags=False,
	),
	# PHP Markdown Extra: fenced code + tables + header anchors.
	# Definition lists, footnotes, and abbreviations are not yet in the flag set.
	# Strikethrough is not in the core spec.
	FLAVOR_PHP_EXTRA: MarkdownFlavorConfig(
		task_lists=False,
		strikethrough=False,
		subscript=False,
		superscript=False,
		mark=False,
		pandoc_images=False,
		zim_tags=False,
	),
	# R Markdown: Pandoc markdown + knitr code chunks.
	# Code chunks use fenced-code syntax ({r options}); stored as verbatim
	# blocks with the language attribute, so they round-trip without special
	# handling.  All Pandoc flags apply.
	FLAVOR_RMARKDOWN: MarkdownFlavorConfig(),
	FLAVOR_ORIGINAL: MarkdownFlavorConfig(
		tables=False,
		task_lists=False,
		strikethrough=False,
		fenced_code=False,
		subscript=False,
		superscript=False,
		mark=False,
		anchors=False,
		pandoc_images=False,
		zim_tags=False,
	),
}


_FORMAT_STRINGS.update({
	FLAVOR_PANDOC:    'markdown pandoc',
	FLAVOR_GFM:       'markdown gfm 0.31.2',
	FLAVOR_GLFM:      'markdown glfm',
	FLAVOR_PHP_EXTRA: 'markdown php-extra',
	FLAVOR_RMARKDOWN: 'markdown rmarkdown',
	FLAVOR_ORIGINAL:  'markdown 1.0',
})


def flavor_from_format_string(fmt):
	'''Extract markdown flavor from a Format header string.

	Recognises current strings (e.g. "markdown gfm 0.29") as well as the
	legacy format "markdown 1.0 <flavor>" written by earlier versions.

	@param fmt: Format header value from YAML front matter
	@returns: one of L{FLAVOR_PANDOC}, L{FLAVOR_GFM}, L{FLAVOR_ORIGINAL}
	'''
	fmt = fmt.strip()
	# GLFM must be tested before GFM — 'gfm' is a substring of 'glfm'
	if 'glfm' in fmt or 'gitlab' in fmt:
		return FLAVOR_GLFM
	if 'gfm' in fmt:
		return FLAVOR_GFM
	if 'original' in fmt or '1.0' in fmt:
		return FLAVOR_ORIGINAL
	if 'php-extra' in fmt or 'php extra' in fmt:
		return FLAVOR_PHP_EXTRA
	if 'rmarkdown' in fmt or 'rmd' in fmt:
		return FLAVOR_RMARKDOWN
	# 'markdown pandoc' or anything else → pandoc
	return FLAVOR_PANDOC


def format_string_for_flavor(flavor):
	'''Build a Format header string for the given flavor.

	@param flavor: one of L{FLAVOR_PANDOC}, L{FLAVOR_GFM}, L{FLAVOR_ORIGINAL}
	@returns: string like "markdown pandoc" or "markdown gfm 0.29"
	'''
	return _FORMAT_STRINGS.get(flavor, 'markdown pandoc')


info = {
	'name': 'markdown',
	'desc': 'Markdown Text (pandoc)',
	'mimetype': 'text/markdown',
	'extension': 'md',
	'native': True,
	'import': True,
	'export': True,
	'usebase': True,
}


# ---- YAML front matter helpers ----

_yaml_front_matter_re = re.compile(r'\A---[ \t]*\n(.*?\n)---[ \t]*\n\n?', re.DOTALL)
_yaml_kv_re = re.compile(r'^([\w-]+):\s+(.*?)$', re.M)


def parse_yaml_front_matter(text):
	'''Parse YAML front matter delimited by --- lines.

	@returns: tuple of (body_text, meta_dict)
	'''
	meta = {}
	m = _yaml_front_matter_re.match(text)
	if m:
		yaml_block = m.group(1)
		for kv in _yaml_kv_re.finditer(yaml_block):
			meta[kv.group(1)] = kv.group(2).strip().strip('"').strip("'")
		text = text[m.end():]
	return text, meta


def dump_yaml_front_matter(meta):
	'''Dump metadata as YAML front matter string.

	@param meta: dict of key-value pairs
	@returns: string with YAML front matter block, or empty string if no meta
	'''
	if not meta:
		return ''
	lines = ['---\n']
	for k, v in meta.items():
		v = str(v).strip()
		if ':' in v or '#' in v or "'" in v:
			v = '"%s"' % v.replace('"', '\\"')
		lines.append('%s: %s\n' % (k, v))
	lines.append('---\n')
	return ''.join(lines)


# ---- Markdown bullet patterns ----

# GFM task list: - [ ], - [x], - [X]
# Regular bullets: -, *, +
# Numbered: 1. 2. etc.
md_bullet_line_re = re.compile(
	r'^([ \t]*)((?:[-*+]|\d+\.|[a-zA-Z]\.)[ \t]+(?:\[[ xX*><]\][ \t]+)?)(.*$\n?)',
	re.M
)
md_checkbox_re = re.compile(r'[-*+]\s+\[([ xX*><])\]')
md_number_bullet_re = re.compile(r'^(\d+|[a-zA-Z])\.$')

md_empty_lines_re = re.compile(r'((?:^[ \t]*\n)+)', re.M | re.U)

blockquote_line_re = re.compile(r'^((?:>[ \t]?)+)(.*\n?)')

def _has_valid_href_parenthesis(href):
	# Either ensure balanced pairs of unescaped ()
	open = len(re.findall(r'(?<!\\)\(', href))
	close = len(re.findall(r'(?<!\\)\)', href))
	return open == close

# ---- Markdown Parser ----

def _chain_rules(rules):
	'''Chain a list of Rule objects using the | operator.'''
	result = rules[0]
	for r in rules[1:]:
		result = result | r
	return result


class MarkdownParser(object):
	'''Parser for Markdown text using the same 3-level architecture
	as WikiParser: block -> list/indent -> inline.
	'''

	BULLETS = {
		'[ ]': UNCHECKED_BOX,
		'[x]': XCHECKED_BOX,
		'[X]': XCHECKED_BOX,
		'[*]': CHECKED_BOX,
		'[>]': MIGRATED_BOX,
		'[<]': TRANSMIGRATED_BOX,
	}

	def __init__(self, default_flavor=FLAVOR_PANDOC):
		self._set_flavor(default_flavor)
		self.blockquote_indent = None

	def _set_flavor(self, flavor):
		if flavor not in FLAVOR_CONFIGS:
			logger.warning('Unknown markdown flavor %r, defaulting to pandoc', flavor)
			flavor = FLAVOR_PANDOC
		self._flavor = flavor
		self._cfg = FLAVOR_CONFIGS[flavor]
		self.inline_parser = self._init_inline_parser()
		self.para_parser = self._init_intermediate_parser()
		self.block_parser = self._init_block_parser()

	def __call__(self, builder, text):
		builder.start(FORMATTEDTEXT)
		if text:
			self.block_parser(builder, text)
		builder.end(FORMATTEDTEXT)

	def _init_inline_parser(self):
		cfg = self._cfg
		descent = lambda *a: self.nested_inline_parser_below_link(*a)
		# Rules valid below a link (no nesting of links allowed)
		below_link = [
			Rule(EMPHASIS, r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', descent=descent),
			Rule(STRONG, r'\*\*(?!\*)(.+?)\*\*', descent=descent),
		]
		if cfg.zim_tags:
			below_link.insert(0, Rule(TAG, r'(?<!\S)@\w+', process=self.parse_tag))
		if cfg.mark:
			below_link.append(Rule(MARK, r'__(?!_)(.+?)__', descent=descent))
		if cfg.subscript:
			below_link.append(Rule(SUBSCRIPT, r'(?<!~)~(?!~)(.+?)(?<!~)~(?!~)', descent=descent))
		if cfg.superscript:
			below_link.append(Rule(SUPERSCRIPT, r'\^(?!\^)(.+?)\^', descent=descent))
		if cfg.strikethrough:
			below_link.append(Rule(STRIKE, r'~~(?!~)(.+?)~~', descent=descent))
		below_link.extend([
			Rule(VERBATIM, r'(?<!`)``(?!`)(.+?)(?<!`)``(?!`)'),
			Rule(VERBATIM, r'(?<!`)`(?!`)(.+?)(?<!`)`(?!`)'),
		])
		self.nested_inline_parser_below_link = _chain_rules(below_link)

		descent = lambda *a: self.inline_parser(*a)

		# Top-level inline rules
		top = [
			Rule(LINK, r'<([a-zA-Z][a-zA-Z0-9.+-]*:[^\s>]+)>', process=self.parse_autolink),
			Rule(LINK, r"<([a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*)>", process=self.parse_autolink),  # email autolink
			Rule(LINK, url_link_re, process=self.parse_url),
			Rule(IMAGE, r'!\[([^\]]*)\]\(([^)]+)\)(\{[^}]*\})?', process=self.parse_image),
			Rule(LINK, r'\[([^\]]*)\]\((\S+)\)', process=self.parse_link),
			Rule(LINK, r'\[\[(?!\[)(.*?\]*)\]\]', process=self.parse_wiki_link),
		]
		if cfg.anchors:
			top.append(Rule(ANCHOR, r'\{\#(\w[\w-]*)\}', process=self.parse_anchor))
		if cfg.zim_tags:
			top.append(Rule(TAG, r'(?<!\S)@\w+', process=self.parse_tag))
		top.extend([
			Rule(EMPHASIS, r'\\\*', process=self._unescape_char),  # backslash escape for \*
			Rule(EMPHASIS, r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', descent=descent),
			Rule(STRONG, r'\*\*(?!\*)(.+?)\*\*', descent=descent),
		])
		if cfg.mark:
			top.append(Rule(MARK, r'__(?!_)(.+?)__', descent=descent))
		if cfg.subscript:
			top.append(Rule(SUBSCRIPT, r'(?<!~)~(?!~)(.+?)(?<!~)~(?!~)', descent=descent))
		if cfg.superscript:
			top.append(Rule(SUPERSCRIPT, r'\^(?!\^)(.+?)\^', descent=descent))
		if cfg.strikethrough:
			top.append(Rule(STRIKE, r'~~(?!~)(.+?)~~', descent=descent))
		top.extend([
			Rule(VERBATIM, r'(?<!`)``(?!`)(.+?)(?<!`)``(?!`)'),
			Rule(VERBATIM, r'(?<!`)`(?!`)(.+?)(?<!`)`(?!`)'),
		])
		return _chain_rules(top)


	def _init_intermediate_parser(self):
		p = RegexParser(
			Rule('X-Bullet-List', r'''(
				^[ \t]* (?:[-*+]|\d+\.|[a-zA-Z]\.) [ \t]+ (?:\[[ xX*><]\][ \t]+)? .* $\n?    # Line with bullet
				(?:
					^[ \t]* (?:[-*+]|\d+\.|[a-zA-Z]\.) [ \t]+ (?:\[[ xX*><]\][ \t]+)? .* $\n? # More items
				)*
			)''',
				process=self.parse_list
			),
		)
		p.process_unmatched = self.parse_inline_block
		return p

	def _init_block_parser(self):
		cfg = self._cfg
		rules = []

		if cfg.fenced_code:
			# Zim object in fenced code block: ```{object_type: params}
			# Must come before generic fenced code block
			rules.append(Rule(OBJECT, r'''
				^[ \t]* `{3,} [ \t]* \{ (\S+) : [ \t]* (.*?) \} [ \t]* \n		# ```{type: params}
				( (?:^.*\n)*? )													# body
				^[ \t]* `{3,} [ \t]* \n											# closing ```
			''',
				process=self.parse_object
			))
			# Backtick fenced code block (``` ... ```)
			rules.append(Rule(VERBATIM_BLOCK, r'''
				^[ \t]* (`{3,}) [ \t]* (.*?) \n					# opening backtick fence with optional info
				( (?:^.*\n)*? )									# multi-line content
				^[ \t]* `{3,} [ \t]* \n							# closing backtick fence
			''',
				process=self.parse_fenced_code
			))
			# Tilde fenced code block (~~~ ... ~~~)
			rules.append(Rule(VERBATIM_BLOCK, r'''
				^[ \t]* (~{3,}) [ \t]* (.*?) \n					# opening tilde fence with optional info
				( (?:^.*\n)*? )									# multi-line content
				^[ \t]* ~{3,} [ \t]* \n							# closing tilde fence
			''',
				process=self.parse_fenced_code
			))
		else:
			# Original flavor: 4-space / tab indented code blocks.
			# Note: RegexParser always uses re.X (verbose), so literal spaces
			# in patterns are stripped.  Use [ ]{4} to match 4 real spaces.
			rules.append(Rule(VERBATIM_BLOCK,
				r'((?:^(?:[ ]{4}|\t).*$\n)+)',
				process=self.parse_indented_code
			))

		# ATX headings: # Heading
		rules.append(Rule(HEADING,
			r'^(\#{1,6})[ \t]+(\S.*?)[ \t]*\#*[ \t]*$\n?',
			process=self.parse_heading
		))

		if cfg.tables:
			# GFM pipe table
			rules.append(Rule(TABLE, r'''
				^(\|.+\|)[ \t]*\n								# header row
				^([ \t]*\|[ \t\-:|]+\|[ \t]*\n)					# separator row
				((?:^[ \t]*\|.+\|[ \t]*\n)+)					# body rows
			''',
				process=self.parse_table
			))

		# Horizontal rule
		rules.append(Rule(LINE, r'^[ \t]*(?:[-*_][ \t]*){3,}$\n?', process=self.parse_line))
		# Blockquote
		rules.append(Rule('X-Blockquote',
			r'((?:^>[ \t]?.*$\n?)+)',						# Lines with > prefix
			process=self.parse_blockquote
		))

		p = RegexParser(*rules)
		p.process_unmatched = self.parse_para
		return p

	@staticmethod
	def _unescape_char(builder, text):
		builder.text(text[1:]) # strip leading "\"

	# --- Block-level handlers ---

	def parse_blockquote(self, builder, text):
		# First break into blocks with same indenting, then recurs block parser per block
		# We set blockquote_indent to apply indent to embedded blocks / paras
		lines = text.splitlines(True)
		blocklvl, block = None, []
		while lines:
			line = lines.pop(0)
			m = blockquote_line_re.match(line)
			lvl = m.group(1).count('>')
			if blocklvl is None:
				blocklvl = lvl
				block.append(m.group(2))
			elif lvl != blocklvl:
				self.blockquote_indent = blocklvl
				self.block_parser(builder, ''.join(block))
				self.blockquote_indent = None

				blocklvl, block = lvl, [m.group(2)]
			else:
				block.append(m.group(2))

		if block:
			self.blockquote_indent = blocklvl
			self.block_parser(builder, ''.join(block))
			self.blockquote_indent = None

	def parse_heading(self, builder, hashes, text):
		level = min(len(hashes), 6)
		text = text.rstrip() + '\n'
		builder.start(HEADING, {'level': level})
		self.inline_parser(builder, text)
		builder.end(HEADING)

	def parse_indented_code(self, builder, text):
		'''Parse 4-space / tab indented code blocks (original flavor).'''
		lines = []
		for line in text.splitlines(True):
			if line.startswith('    '):
				lines.append(line[4:])
			elif line.startswith('\t'):
				lines.append(line[1:])
			else:
				lines.append(line)
		builder.append(VERBATIM_BLOCK, None, ''.join(lines))

	def parse_fenced_code(self, builder, fence, info, text):
		attrib = None
		if info and info.strip():
			# Store the full info string so it round-trips faithfully.
			# This preserves R Markdown chunk headers like {r fig.width=8}
			# as well as plain language names like "python".
			attrib = {'lang': info.strip()}
		if self.blockquote_indent:
			attrib = attrib if attrib else {}
			attrib['indent'] = self.blockquote_indent
		builder.append(VERBATIM_BLOCK, attrib, text)

	def parse_object(self, builder, otype, param, body):
		otype = otype.strip().lower()
		attrib = {}

		from zim.formats.wiki import param_re
		for match in param_re.finditer(param):
			key = match.group(1).lower()
			value = match.group(2)
			if value.startswith('"') and len(value) > 1:
				value = value[1:-1].replace('""', '"')
			attrib[key] = value

		attrib['type'] = otype
		if self.blockquote_indent:
			attrib['indent'] = self.blockquote_indent
		builder.append(OBJECT, attrib, body)

	def parse_table(self, builder, headerline, alignstyle, body):
		headerrow = split_escaped_string(headerline.strip().strip('|'), '|')
		rows = [
			split_escaped_string(line.strip().strip('|'), '|')
				for line in body.strip().split('\n') if line.strip()
		]

		n_cols = max(len(headerrow), max(len(r) for r in rows) if rows else 0)

		aligns = []
		for celltext in alignstyle.strip().strip('|').split('|'):
			celltext = celltext.strip()
			if celltext.startswith(':') and celltext.endswith(':'):
				alignment = 'center'
			elif celltext.startswith(':'):
				alignment = 'left'
			elif celltext.endswith(':'):
				alignment = 'right'
			else:
				alignment = 'normal'
			aligns.append(alignment)

		while len(aligns) < n_cols:
			aligns.append('normal')

		headers = []
		wraps = []
		for celltext in headerrow:
			if celltext.rstrip().endswith('<'):
				celltext = celltext.rstrip().rstrip('<')
				wraps.append(1)
			else:
				wraps.append(0)
			headers.append(celltext)

		while len(headers) < n_cols:
			headers.append('')
			wraps.append(0)

		attrib = {'aligns': ','.join(aligns), 'wraps': ','.join(map(str, wraps))}
		if self.blockquote_indent:
			attrib['indent'] = self.blockquote_indent
		builder.start(TABLE, attrib)

		builder.start(HEADROW)
		for celltext in headers:
			celltext = unescape_string(celltext.strip()) or ' '
			builder.append(HEADDATA, {}, celltext)
		builder.end(HEADROW)

		for bodyrow in rows:
			while len(bodyrow) < n_cols:
				bodyrow.append('')
			builder.start(TABLEROW)
			for celltext in bodyrow:
				builder.start(TABLEDATA)
				celltext = unescape_string(celltext.strip()) or ' '
				self.inline_parser(builder, celltext)
				builder.end(TABLEDATA)
			builder.end(TABLEROW)

		builder.end(TABLE)

	def parse_para(self, builder, text):
		if text.isspace():
			builder.text(text)
		else:
			for block in md_empty_lines_re.split(text):
				if not block:
					pass
				elif block.isspace():
					builder.text(block)
				else:
					block = convert_space_to_tab(block)
					builder.start(PARAGRAPH)
					self.para_parser(builder, block)
					builder.end(PARAGRAPH)

	def parse_inline_block(self, builder, text):
		if self.blockquote_indent:
			builder.start(BLOCK, {'indent': self.blockquote_indent})
			self.inline_parser(builder, text)
			builder.end(BLOCK)
		else:
			self.inline_parser(builder, text)

	def parse_list(self, builder, text):
		lines = text.splitlines(True)
		self.parse_list_lines(builder, lines)

	def parse_list_lines(self, builder, lines):
		stack = [(None, -1)]  # (list_type, indent_level)

		def get_indent(line):
			count = 0
			for ch in line:
				if ch == '\t':
					count += 4
				elif ch == ' ':
					count += 1
				else:
					break
			return count

		def start_list(number_m, my_indent):
			if self.blockquote_indent and len(stack) == 1:
				attrib = {'indent': self.blockquote_indent}
			else:
				attrib = None

			if number_m:
				l = NUMBEREDLIST
				attrib = attrib or {}
				attrib['start'] = number_m.group(1)
			else:
				l = BULLETLIST
			builder.start(l, attrib)
			stack.append((l, my_indent))

		for line in lines:
			m = md_bullet_line_re.match(line)
			if not m:
				continue  # skip malformed lines

			prefix = m.group(1)
			bullet_full = m.group(2)
			text = m.group(3)
			my_indent = get_indent(prefix)

			# Parse bullet type and optional checkbox.
			# Use bullet_full (un-stripped) so the trailing space after "]" is preserved
			# when we need to recover the checkbox text back into the item body.
			bullet_stripped = bullet_full.strip()
			number_m = None
			# raw_checkbox_m captures e.g. "[ ] " (with trailing whitespace)
			raw_checkbox_m = re.match(r'[-*+][ \t]+(\[[ xX*><]\][ \t]*)', bullet_full)
			if raw_checkbox_m and self._cfg.task_lists:
				checkbox_char = raw_checkbox_m.group(1)[1]  # char inside brackets
				checkbox_map = {
					' ': UNCHECKED_BOX,
					'x': XCHECKED_BOX,
					'X': XCHECKED_BOX,
					'*': CHECKED_BOX,
					'>': MIGRATED_BOX,
					'<': TRANSMIGRATED_BOX,
				}
				bullet_type = checkbox_map.get(checkbox_char, UNCHECKED_BOX)
			else:
				if raw_checkbox_m:
					# Checkbox syntax present but not enabled for this flavor:
					# put the captured "[ ] " (with its trailing space) back into
					# the item text so it is not silently dropped.
					text = raw_checkbox_m.group(1) + text
				# Check for numbered list
				number_m = md_number_bullet_re.match(bullet_stripped)
				if not number_m:
					bullet_type = BULLET

			if my_indent > stack[-1][-1]:
				start_list(number_m, my_indent)
			elif len(stack) > 2 and my_indent <= stack[-2][-1]:
				while len(stack) > 2 and my_indent <= stack[-2][-1]:
					l, i = stack.pop()
					builder.end(l)
			elif (stack[-1][0] == NUMBEREDLIST and number_m is None) \
				or (stack[-1][0] == BULLETLIST and number_m is not None):
					l, x = stack.pop()
					builder.end(l)
					start_list(number_m, my_indent)

			if stack[-1][0] == NUMBEREDLIST:
				attrib = None
			else:
				attrib = {'bullet': bullet_type} if bullet_type else {'bullet': BULLET}

			builder.start(LISTITEM, attrib)
			if text:
				self.inline_parser(builder, text)
			builder.end(LISTITEM)

		while len(stack) > 1:
			l, x = stack.pop()
			builder.end(l)

	# --- Inline handlers ---

	def parse_wiki_link(self, builder, text):
		text = text.strip('|') # old bug producing "[[|link]]", or "[[link|]]" or "[[||]]"
		if not text or text.isspace():
			return

		href = None
		if '|' in text:
			href, text = text.split('|', 1)
			text = text.strip('|') # stuff like "[[foo||bar]]"

		if text.endswith(']'):
			delta = text.count(']') - text.count('[')
			if delta > 0:
				self.inline_parser.backup_parser_offset(delta)
				text = text[:-delta]

		if href is None:
			builder.append(LINK, {'href': text}, text)
		else:
			builder.start(LINK, {'href': href})
			self.nested_inline_parser_below_link(builder, text)
			builder.end(LINK)

	def parse_link(self, builder, text, href):
		'''Parse [text](href) links'''
		if '(' in href or ')' in href:
			orig_href = href
			while ')' in href and not _has_valid_href_parenthesis(href):
				i = href.rfind(')')
				href = href[:i]

			if not _has_valid_href_parenthesis(href):
				builder.text('[')
				self.inline_parser.backup_parser_offset(len(orig_href) + len(text) + len(']()'))
				return
			else:
				self.inline_parser.backup_parser_offset(len(orig_href) - len(href))

			href = href.replace('\\(', '(').replace('\\)', ')')

		href = href.strip()
		text = text.strip()

		# If the href has a file extension (not .md) and is not already a URL
		# or path, prefix with './' so link_type() classifies it as 'file'
		# rather than 'page'.  Without this, [doc](file.pdf) would be treated
		# as a link to a wiki page named "file.pdf" when round-tripping through
		# the zim-wiki format.
		_, ext = os.path.splitext(href.split('?')[0].split('#')[0])
		if ext and ext.lower() != '.md' \
				and not is_url_link(href) \
				and not is_path_re.match(href):
			href = './' + href

		if text and text != href:
			builder.start(LINK, {'href': href})
			self.nested_inline_parser_below_link(builder, text)
			builder.end(LINK)
		else:
			builder.append(LINK, {'href': href}, text or href)

	def parse_image(self, builder, alt, src, props_str=None, href=None):
		'''Parse ![alt](src){props} images'''
		attrib = {'src': src.strip()}

		if alt:
			attrib['alt'] = alt

		href = href.strip() if href else None

		# Parse Pandoc-style properties: {#id width=500px height=20px}
		if props_str:
			props_str = props_str.strip('{}').strip()
			for m in re.findall('#\\w+|\\w+=(?:".*?"|\\w+)', props_str):
				if m.startswith('#'):
					attrib['id'] = m[1:]
				else:
					k, v = m.split('=')
					if k in ('width', 'height') and v.endswith('px'):
						v = v[:-2] # Strip 'px' suffix for width/height
					else:
						v = decode_xml(v.strip('"'))

					attrib[k] = v

		if attrib.get('type'):
			# Backward compatibility of image generators < zim 0.70
			attrib['type'] = 'image+' + attrib['type']
			builder.append(OBJECT, attrib)
		else:
			builder.append(IMAGE, attrib)

	def parse_url(self, builder, *a):
		text = a[0]
		url = match_url_link(text)
		if url is None:
			self.inline_parser.backup_parser_offset(len(text) - 1)
			builder.text(text[0])
		elif url != text:
			self.inline_parser.backup_parser_offset(len(text) - len(url))
			builder.append(LINK, {'href': url}, url)
		else:
			builder.append(LINK, {'href': url}, url)

	@staticmethod
	def parse_autolink(builder, href):
		'''Parse <url> autolinks'''
		builder.append(LINK, {'href': href}, href)

	@staticmethod
	def parse_tag(builder, text):
		builder.append(TAG, {'name': text[1:]}, text)

	@staticmethod
	def parse_anchor(builder, name):
		builder.append(ANCHOR, {'name': name})

	@staticmethod
	def parse_line(builder, text):
		builder.append(LINE)


_md_parser_cache = {}  #: per-flavor parser cache


def _get_md_parser(flavor):
	'''Return a cached MarkdownParser for the given flavor.'''
	if flavor not in _md_parser_cache:
		_md_parser_cache[flavor] = MarkdownParser(flavor)
	return _md_parser_cache[flavor]


class Parser(ParserClass):
	'''Parser class for reading Markdown files.

	Handles both regular markdown text and file-level input with
	YAML front matter (when file_input=True).  When file_input is True
	the Format header is used to auto-detect the flavor, overriding
	the default_flavor passed to the constructor.
	'''

	def __init__(self, default_flavor=FLAVOR_PANDOC):
		if default_flavor not in FLAVOR_CONFIGS:
			logger.warning('Unknown markdown flavor %r, defaulting to pandoc', default_flavor)
			default_flavor = FLAVOR_PANDOC
		self._default_flavor = default_flavor

	def parse(self, input, file_input=False):
		if not isinstance(input, str):
			input = ''.join(input)

		input = input.replace('\u2029', ' ')  # Unicode PARAGRAPH SEPARATOR
		input = fix_unicode_whitespace(input)

		meta = None
		flavor = self._default_flavor
		if file_input:
			input, meta = parse_yaml_front_matter(input)
			# Strip the blank-line separator between the front-matter block and
			# the page content.  Without this the leading \n ends up as a TEXT
			# node in the parse tree, and the dumper then emits it on top of its
			# own mandatory blank line (line 810: '\n'), producing a double blank
			# line on every re-serialisation.
			input = input.lstrip('\n')
			if meta:
				file_flavor = flavor_from_format_string(meta.get('Format', ''))
				if file_flavor != flavor:
					flavor = file_flavor

		md_parser = _get_md_parser(flavor)
		builder = ParseTreeBuilder()
		md_parser(builder, input)

		parsetree = builder.get_parsetree()
		if meta is not None:
			parsetree.meta.update(meta)
		return parsetree


class Dumper(TextDumper):
	'''Dumper class for writing Markdown files.

	Supports both export mode (with linker, for resolving links relative
	to export target) and native file output mode (without linker,
	using raw hrefs suitable for storage).

	@param flavor: one of FLAVOR_PANDOC, FLAVOR_GFM, FLAVOR_ORIGINAL;
	controls which markdown extensions are emitted.
	'''

	BULLETS = {
		UNCHECKED_BOX: '-',
		XCHECKED_BOX: '-',
		CHECKED_BOX: '-',
		MIGRATED_BOX: '-',
		TRANSMIGRATED_BOX: '-',
		BULLET: '-',
	}

	CHECKBOX_MARKS = {
		UNCHECKED_BOX: '[ ]',
		XCHECKED_BOX: '[x]',
		CHECKED_BOX: '[*]',
		MIGRATED_BOX: '[>]',
		TRANSMIGRATED_BOX: '[<]',
	}

	TAGS = {
		EMPHASIS: ('*', '*'),
		STRONG: ('**', '**'),
		MARK: ('__', '__'),
		STRIKE: ('~~', '~~'),
		VERBATIM: ('`', '`'),
		TAG: ('', ''),  # @tag rendered as-is
		SUBSCRIPT: ('~', '~'),
		SUPERSCRIPT: ('^', '^'),
	}

	def __init__(self, linker=None, flavor=FLAVOR_PANDOC, **kwarg):
		TextDumper.__init__(self, linker=linker, **kwarg)
		if flavor not in FLAVOR_CONFIGS:
			logger.warning('Unknown markdown flavor %r, defaulting to pandoc', flavor)
			flavor = FLAVOR_PANDOC
		self._flavor = flavor
		self._cfg = FLAVOR_CONFIGS[flavor]

		# Remove unsupported tags from TAGS so the dump_* fallbacks are called
		self.TAGS = dict(self.__class__.TAGS)
		if not self._cfg.mark:
			self.TAGS.pop(MARK, None)
		if not self._cfg.strikethrough:
			self.TAGS.pop(STRIKE, None)
		if not self._cfg.subscript:
			self.TAGS.pop(SUBSCRIPT, None)
		if not self._cfg.superscript:
			self.TAGS.pop(SUPERSCRIPT, None)

	def dump(self, tree, file_output=False):
		if file_output:
			# Dump with YAML front matter
			header_meta = {}
			if hasattr(tree, 'meta') and tree.meta:
				header_meta.update(tree.meta)

			if 'Content-Type' not in header_meta:
				header_meta['Content-Type'] = 'text/markdown'
			if 'Format' not in header_meta:
				header_meta['Format'] = format_string_for_flavor(self._flavor)

			body = TextDumper.dump(self, tree)
			if body and not body[-1].endswith('\n'):
				body[-1] = body[-1] + '\n'
			return [dump_yaml_front_matter(header_meta), '\n'] + body
		else:
			return TextDumper.dump(self, tree)

	def encode_text(self, tag, text):
		if tag in (VERBATIM, VERBATIM_BLOCK):
			return text
		else:
			return text.replace('*', '\\*')

	# ---- Flavor-guarded inline dump methods ----
	# These are called when the corresponding tag has been removed from self.TAGS
	# (i.e. the extension is not supported by the active flavor).

	def dump_mark(self, tag, attrib, strings):
		logger.warning('Underline/mark not supported in %s flavor, rendering as plain text', self._flavor)
		return strings

	def dump_strike(self, tag, attrib, strings):
		logger.warning('Strikethrough not supported in %s flavor, rendering as plain text', self._flavor)
		return strings

	def dump_sub(self, tag, attrib, strings):
		logger.warning('Subscript not supported in %s flavor, rendering as plain text', self._flavor)
		return strings

	def dump_sup(self, tag, attrib, strings):
		logger.warning('Superscript not supported in %s flavor, rendering as plain text', self._flavor)
		return strings

	def dump_indent(self, tag, attrib, strings):
		if attrib and 'indent' in attrib:
			prefix = '> ' * int(attrib['indent'])
			return self.prefix_lines(prefix, strings)
		else:
			return strings

	dump_p = dump_indent
	dump_div = dump_indent

	def dump_list(self, tag, attrib, strings):
		if 'indent' in attrib:
			# top level list with specified indent
			prefix = '> ' * int(attrib['indent'])
			return self.prefix_lines(prefix, strings)
		elif self.context[-1].tag == LISTITEM:
			# indent sub list
			prefix = '  '
			return self.prefix_lines(prefix, strings)
		else:
			# top level list, no indent
			return strings

	dump_ul = dump_list
	dump_ol = dump_list

	def dump_li(self, tag, attrib, strings):
		# In export mode, convert letter-numbered lists to digit-numbered lists
		if self.context[-1].tag in (BULLETLIST, NUMBEREDLIST):
			if self.linker and self.context[-1].tag == NUMBEREDLIST \
				and not self.context[-1].attrib.get('_iter'):
					iter = self.context[-1].attrib.get('start', '1')
					self.context[-1].attrib['_iter'] = convert_list_iter_letter_to_number(iter)

		# Get the base list item from parent
		result = TextDumper.dump_li(self, tag, attrib, strings)

		# Add checkbox syntax for task list items
		bullet_type = attrib.get('bullet', BULLET) if attrib else BULLET
		if bullet_type in self.CHECKBOX_MARKS:
			if self._cfg.task_lists:
				checkbox = self.CHECKBOX_MARKS[bullet_type]
				# Insert checkbox after "- "
				result_list = list(result)
				for i, s in enumerate(result_list):
					if s == ' ' and i > 0:
						result_list.insert(i + 1, checkbox + ' ')
						break
				return tuple(result_list)
			else:
				logger.warning(
					'Checkbox list items not supported in %s flavor, converting to plain bullet',
					self._flavor
				)
				# Fall through — result already has a plain '- ' prefix from parent

		return result

	def dump_pre(self, tag, attrib, strings):
		if not self._cfg.fenced_code:
			# Original flavor: use 4-space indented code blocks
			result = []
			for s in strings:
				for line in s.splitlines(True):
					result.append('    ' + line)
			if result and not result[-1].endswith('\n'):
				result[-1] = result[-1] + '\n'
			result.append('\n')  # blank line to end the code block
			if attrib and 'indent' in attrib:
				prefix = '> ' * int(attrib['indent'])
				return self.prefix_lines(prefix, result)
			return result

		# Fenced code blocks (GFM / pandoc)
		lang = ''
		if attrib and 'lang' in attrib:
			lang = attrib['lang']
		result = ['```%s\n' % lang]
		result.extend(strings)
		if result and not result[-1].endswith('\n'):
			result[-1] = result[-1] + '\n'
		result.append('```\n')

		if attrib and 'indent' in attrib:
			prefix = '> ' * int(attrib['indent'])
			return self.prefix_lines(prefix, result)

		return result

	def dump_h(self, tag, attrib, strings):
		level = int(attrib['level'])
		if level < 1:
			level = 1
		elif level > 6:
			level = 6
		prefix = '#' * level
		strings.insert(0, prefix + ' ')
		# Ensure heading ends with newline
		text = strings.pop()
		strings.append(text.rstrip() + '\n')
		return strings

	def dump_anchor(self, tag, attrib, strings=None):
		if not self._cfg.anchors:
			logger.warning('Anchors not supported in %s flavor, skipping {#%s}', self._flavor, attrib.get('name', ''))
			return ()
		return ('{#%s}' % attrib['name'],)

	def dump_link(self, tag, attrib, strings=None):
		assert 'href' in attrib, \
			'BUG: link misses href: %s "%s"' % (attrib, strings)

		href = attrib['href']
		text = ''.join(strings) if strings else ''

		if self.linker:
			# Export mode: resolve links through linker and export as standard markdown
			href = self.linker.link(href)
			text = text or href
		elif is_wiki_link(href):
			# Wiki link that cannot be resolved by other applications --> wiki link extension
			return ('[[', href, '|', text, ']]') if text and text != href else ('[[', href, ']]')

		if href == text:
			if is_url_link(href):
				return ('<', href, '>')
			else:
				text = ''

		if not _has_valid_href_parenthesis(href):
			href = href.replace('(', '\\(').replace(')', '\\)')

		return ['[%s](%s)' % (text, href)]

	def dump_img(self, tag, attrib, strings=None):
		if self.linker:
			src = self.linker.img(attrib['src'])
		else:
			src = attrib.get('src', '')

		text = attrib.get('alt', '')

		# Pandoc-style image attributes: ![alt](src){#id width=500px key=val}
		if self._cfg.pandoc_images:
			opts = []
			if 'id' in attrib:
				opts.append('#' + attrib['id'])
			for k, v in sorted(attrib.items()):
				if k in ('src', 'alt', 'id') or k.startswith('_'):
					continue
				elif v:  # skip None, "" and 0
					if k in ('width', 'height'):
						v = '%spx' % v
					elif k == 'href' and self.linker:
						v = self.linker.link(v)
					data = encode_xml_attrib(str(v))
					if re.match(r'^\w+$', data):
						opts.append('%s=%s' % (k, data))
					else:
						opts.append('%s="%s"' % (k, data))
			props = ('{%s}' % ' '.join(opts)) if opts else ''
		else:
			props = ''

		return ['![%s](%s)%s' % (text, src, props)]

	def dump_object_fallback(self, tag, attrib, strings=None):
		assert "type" in attrib, "Undefined type of object"

		opts = []
		for key, value in sorted(list(attrib.items())):
			if key in ('type', 'indent') or value is None:
				continue
			opts.append(' %s="%s"' % (key, str(value).replace('"', '""')))

		if not strings:
			strings = []
		return ['```{', attrib['type'], ':'] + opts + ['}\n'] + strings + ['```\n']

	def dump_table(self, tag, attrib, strings):
		if not self._cfg.tables:
			# Original flavor: render table as plain text (tab-separated)
			logger.warning('Tables not supported in %s flavor, rendering as plain text', self._flavor)
			result = []
			for row in strings:
				result.append('\t'.join(cell.strip() for cell in row) + '\n')
			result.append('\n')
			return result

		table = []
		rows = strings

		aligns, wraps = TableParser.get_options(attrib)
		maxwidths = TableParser.width2dim(rows)
		headsep = TableParser.headsep(maxwidths, aligns, x='|', y='-')
		rowline = lambda row: TableParser.rowline(row, maxwidths, aligns)

		if not self.linker:
			# Native mode: use headline with alignment markers
			table.append(TableParser.headline(rows[0], maxwidths, aligns, wraps))
		else:
			table.append(rowline(rows[0]))
		table.append(headsep)
		table += [rowline(row) for row in rows[1:]]
		return [line + "\n" for line in table]

	def dump_td(self, tag, attrib, strings):
		text = ''.join(strings) if strings else ''
		return [escape_string(text.replace('\n', '<br>'), '|')]

	dump_th = dump_td

	def dump_line(self, tag, attrib, strings=None):
		return '---\n'
