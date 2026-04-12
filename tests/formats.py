
# Copyright 2008-2012 Jaap Karssenberg <jaap.karssenberg@gmail.com>

'''Test cases for the zim.formats module.'''




import tests

from zim.formats import *
from zim.parse.links import is_url_link
from zim.parse.tokenlist import skip_to_end_token
from zim.notebook import Path
from zim.templates import Template


class TestFormatMixin(object):
	'''Mixin for testing formats, uses data in C{tests/data/formats/}'''

	reference_xml = tests.TEST_DATA_FOLDER.file('formats/parsetree.xml').read().rstrip('\n')

	reference_data = {
		'wiki': 'wiki.txt',
		'plain': 'plain.txt',
		'html': 'export.html',
		'latex': 'export.tex',
		'markdown': 'export.markdown',
		'markdown-native': 'markdown.md',
		'reST': 'export.rst',
	}

	def testFormatInfo(self):
		for key in ('name', 'desc', 'mimetype', 'extension'):
			self.assertIsInstance(self.format.info[key], str,
				msg='Invalid key "%s" in format info' % key)

		for key in ('native', 'import', 'export'):
			self.assertIsInstance(self.format.info[key], bool,
				msg='Invalid key "%s" in format info' % key)

		if self.format.info['native'] or self.format.info['import']:
			self.assertTrue(hasattr(self.format, 'Parser'))

		if self.format.info['native'] or self.format.info['export']:
			self.assertTrue(hasattr(self.format, 'Dumper'))

	def getReferenceData(self, name=None):
		'''Returns reference data from C{tests/data/formats/} for the
		format being tested.
		'''
		name = name if name else self.format.info['name']
		assert name in self.reference_data, 'No reference data for format "%s"' % name
		basename = self.reference_data[name]
		text = tests.TEST_DATA_FOLDER.file('formats/' + basename).read()

		# No absolute paths ended up in reference
		pwd = tests.ZIM_SRC_FOLDER
		self.assertFalse(pwd.path in text, 'Absolute path ended up in reference')
		self.assertFalse(pwd.userpath in text, 'Absolute path ended up in reference')

		return text

	def getDumper(self):
		linker = StubLinker(tests.TEST_DATA_FOLDER.folder('formats'))
		return self.format.Dumper(linker=linker)

	def testFormat(self):
		'''Test if formats supports full syntax
		Uses data in C{tests/data/formats} as reference data.
		'''
		# Dumper
		wanted = self.getReferenceData()
		reftree = tests.new_parsetree_from_xml(self.reference_xml)
		dumper = self.getDumper()
		result = ''.join(dumper.dump(reftree))
		#~ print('\n' + '>'*80 + '\n' + result + '\n' + '<'*80 + '\n')
		self.assertMultiLineEqual(result, wanted)
		#import ipdb; ipdb.set_trace()
		self.assertNoTextMissing(result, reftree)

		# Check that dumper did not modify the tree
		self.assertMultiLineEqual(reftree.tostring(), self.reference_xml)

		# partial dumper
		parttree = tests.new_parsetree_from_xml("<?xml version='1.0' encoding='utf-8'?>\n<zim-tree>try these <strong>bold</strong>, <emphasis>italic</emphasis></zim-tree>")
		result = ''.join(dumper.dump(parttree))
		#~ print(">>>%s<<<" % result)
		self.assertFalse(result.endswith('\n')) # partial should not end with "\n"

		# Parser
		if not hasattr(self.format, 'Parser'):
			return
		input = wanted
		parser = self.format.Parser()
		result = parser.parse(input)
		if self.format.info['native']:
			my_reference_xml = self.hackRoundtripReference(self.reference_xml)
			self.assertMultiLineEqual(result.tostring(), my_reference_xml)
		else:
			self.assertTrue(len(result.tostring().splitlines()) > 10)
				# Quick check that we got back *something*
			string = ''.join(dumper.dump(result))
				# now we may have loss of formatting, but text should all be there
				#~ print('\n' + '>'*80 + '\n' + string + '\n' + '<'*80 + '\n')
			self.assertNoTextMissing(string, reftree)

	def hackRoundtripReference(self, xml):
		return xml

	_nonalpha_re = re.compile(r'\W')

	def assertNoTextMissing(self, text, tree):
		'''Assert that no plain text from C{tree} is missing in C{text}
		intended to make sure that even for lossy formats all information
		is preserved.
		'''
		# TODO how to handle objects ??
		assert isinstance(text, str)

		def check_text(wanted, offset):
			if not wanted:
				return

			wanted = self._nonalpha_re.sub(' ', wanted)
			# Non-alpha chars may be replaced with escapes
			# so no way to hard test them

			if wanted.isspace():
				return

			for piece in wanted.strip().split():
				# ~ print("| >>%s<< @ offset %i" % (piece, offset))
				try:
					start = text.index(piece, offset)
				except ValueError:
					self.fail('Could not find text piece "%s" in text after offset %i\n>>>%s<<<' % (
						piece, offset, text[offset:offset + 100]))
				else:
					offset = start + len(piece)

			return offset

		offset = 0
		token_iter = tree.iter_tokens()
		for t in token_iter:
			if t[0] == TEXT:
				offset = check_text(t[1], offset)
			elif t[0] == IMAGE:
				skip_to_end_token(token_iter, IMAGE) # img text is optional
			else:
				pass

	def assertParseEquals(self, text, xml):
		xml = '<?xml version=\'1.0\' encoding=\'utf-8\'?>\n<zim-tree>%s</zim-tree>' % xml
		tree = self.format.Parser().parse(text)
		self.assertEqual(tree.tostring(), xml, 'Parsing: %r' % text)

	def assertDumpEquals(self, xml, text):
		myxml = '<?xml version=\'1.0\' encoding=\'utf-8\'?>\n<zim-tree>%s</zim-tree>' % xml
		tree = ParseTree().fromstring(myxml)
		lines = self.format.Dumper().dump(tree)
		self.assertEqual(''.join(lines), text, 'Dumping: %r' % xml)

	def assertParseAndDumpEquals(self, text, xml):
		self.assertParseEquals(text, xml)
		self.assertDumpEquals(xml, text)


class TestListFormats(tests.TestCase):

	def runTest(self):
		for desc in list_formats(EXPORT_FORMAT):
			name = canonical_name(desc)
			format = get_format(name)
			self.assertTrue(format.info['export'])

		for desc in list_formats(TEXT_FORMAT):
			name = canonical_name(desc)
			format = get_format(name)
			self.assertTrue(format.info['export'])
			self.assertTrue(format.info['mimetype'].startswith('text/'))


class TestParseTree(tests.TestCase):

	def setUp(self):
		self.xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree>
<h level="1">Head 1
</h><h level="2">Head 2
</h><h level="3">Head 3
</h><h level="2">Head 4
</h><h level="5">Head 5
</h><h level="4">Head 6
</h><h level="5">Head 7
</h><h level="6">Head 8
</h></zim-tree>'''

	def teststring(self):
		'''Test ParseTree.fromstring() and .tostring()'''
		tree = ParseTree()
		r = tree.fromstring(self.xml)
		self.assertEqual(id(r), id(tree)) # check return value
		text = tree.tostring()
		self.assertEqual(text, self.xml)

	def testcleanup_headings(self):
		'''Test ParseTree.cleanup_headings()'''
		tree = ParseTree().fromstring(self.xml)
		wanted = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree>
<h level="2">Head 1
</h><h level="3">Head 2
</h><h level="4">Head 3
</h><h level="3">Head 4
</h><h level="4">Head 5
</h><h level="4">Head 6
</h><h level="4">Head 7
</h><h level="4">Head 8
</h></zim-tree>'''
		tree.cleanup_headings(offset=1, max=4)
		text = tree.tostring()
		self.assertEqual(text, wanted)

	def testGetHeadingText(self):
		tree = ParseTree().fromstring(self.xml)
		self.assertEqual(tree.get_heading_text(), "Head 1")

	def testGetHeadingTextNestedFormat(self):
		xml = '''<?xml version='1.0' encoding='utf-8'?>
		<zim-tree>
		<h level="1">Head 1 <strong>BOLD</strong> <link>URL</link>
		</h><h level="2">Head 2
		</h></zim-tree>
		'''
		tree = ParseTree().fromstring(xml)
		self.assertEqual(tree.get_heading_text(), "Head 1 BOLD URL")

	def testSetHeadingText(self):
		tree = ParseTree().fromstring(self.xml)
		tree.set_heading_text('Foo')
		wanted = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree>
<h level="1">Foo
</h><h level="2">Head 2
</h><h level="3">Head 3
</h><h level="2">Head 4
</h><h level="5">Head 5
</h><h level="4">Head 6
</h><h level="5">Head 7
</h><h level="6">Head 8
</h></zim-tree>'''
		text = tree.tostring()
		self.assertEqual(text, wanted)

	def testExtend(self):
		tree1 = ParseTree().fromstring(self.xml)
		tree2 = ParseTree().fromstring(self.xml)
		tree = tree1 + tree2
		wanted = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree>
<h level="1">Head 1
</h><h level="2">Head 2
</h><h level="3">Head 3
</h><h level="2">Head 4
</h><h level="5">Head 5
</h><h level="4">Head 6
</h><h level="5">Head 7
</h><h level="6">Head 8
</h>
<h level="1">Head 1
</h><h level="2">Head 2
</h><h level="3">Head 3
</h><h level="2">Head 4
</h><h level="5">Head 5
</h><h level="4">Head 6
</h><h level="5">Head 7
</h><h level="6">Head 8
</h></zim-tree>'''
		text = tree.tostring()
		self.assertEqual(text, wanted)

	def testGetEndsWithNewline(self):
		for xml, newline in (
			('<zim-tree>foo</zim-tree>', False),
			('<zim-tree><strong>foo</strong></zim-tree>', False),
			('<zim-tree><strong>foo</strong>\n</zim-tree>', True),
			('<zim-tree><strong>foo\n</strong></zim-tree>', True),
			('<zim-tree><strong>foo</strong>\n<img src="foo"></img></zim-tree>', False),
			('<zim-tree><li bullet="unchecked-box" indent="0">foo</li></zim-tree>', True),
			('<zim-tree><li bullet="unchecked-box" indent="0"><strong>foo</strong></li></zim-tree>', True),
			('<zim-tree><li bullet="unchecked-box" indent="0"><strong>foo</strong></li></zim-tree>', True),
		):
			tree = ParseTree().fromstring(xml)
			self.assertEqual(tree.get_ends_with_newline(), newline)

	def testReplace(self):
		def replace(elt):
			# level 2 becomes 3
			# level 3 is replaced by text
			# level 4 is removed
			# level 1, 5 and 6 stay as is
			level = int(elt.attrib['level'])
			if level == 2:
				elt.attrib['level'] = 3
				return elt
			elif level == 3:
				return elt.content
			elif level == 4:
				return None
			else:
				return elt
		tree = ParseTree().fromstring(self.xml)
		wanted = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree>
<h level="1">Head 1
</h><h level="3">Head 2
</h>Head 3
<h level="3">Head 4
</h><h level="5">Head 5
</h><h level="5">Head 7
</h><h level="6">Head 8
</h></zim-tree>'''
		newtree = tree.substitute_elements((HEADING,), replace)
		self.assertIsNot(newtree, tree)
		self.assertNotEqual(newtree.tostring(), tree.tostring())
		text = newtree.tostring()
		self.assertEqual(text, wanted)


class TestWhitespaceCleanup(tests.TestCase):

	def runTest(self):
		for input, want in (
			# <b><i><space>foo</i></b> --> <space><b><i>foo</i></b>
			(
				[(STRONG, None), (EMPHASIS, None), (TEXT, ' foo'), (END, EMPHASIS), (END, STRONG)],
				[(TEXT, ' '), (STRONG, None), (EMPHASIS, None), (TEXT, 'foo'), (END, EMPHASIS), (END, STRONG)]
			),
			(
				[(STRONG, None), (EMPHASIS, None), (TEXT, ' '), (TEXT, 'foo'), (END, EMPHASIS), (END, STRONG)],
				[(TEXT, ' '), (STRONG, None), (EMPHASIS, None), (TEXT, 'foo'), (END, EMPHASIS), (END, STRONG)]
			),
			(
				[(STRONG, None), (EMPHASIS, None), (TEXT, '   foo'), (END, EMPHASIS), (END, STRONG)],
				[(TEXT, '   '), (STRONG, None), (EMPHASIS, None), (TEXT, 'foo'), (END, EMPHASIS), (END, STRONG)]
			),

			# <b><space><i>foo</i></b> --> <space><b><i>foo</i></b>
			(
				[(STRONG, None), (TEXT, ' '), (EMPHASIS, None), (TEXT, 'foo'), (END, EMPHASIS), (END, STRONG)],
				[(TEXT, ' '), (STRONG, None), (EMPHASIS, None), (TEXT, 'foo'), (END, EMPHASIS), (END, STRONG)]
			),

			# <b><i>foo<space></i></b> --> <b><i>foo</i></b><space>
			(
				[(STRONG, None), (EMPHASIS, None), (TEXT, 'foo '), (END, EMPHASIS), (END, STRONG)],
				[(STRONG, None), (EMPHASIS, None), (TEXT, 'foo'), (END, EMPHASIS), (END, STRONG), (TEXT, ' ')]
			),

			# <b><i>foo</i><space></b> --> <b><i>foo</i></b><space>
			(
				[(STRONG, None), (EMPHASIS, None), (TEXT, 'foo'), (END, EMPHASIS), (TEXT, ' '), (END, STRONG)],
				[(STRONG, None), (EMPHASIS, None), (TEXT, 'foo'), (END, EMPHASIS), (END, STRONG), (TEXT, ' ')]
			),

			# <b><space>foo<i><space>bar</i></b> --> <space><b>foo<space><i>bar</i></b>
			(
				[(STRONG, None), (TEXT, ' foo'), (EMPHASIS, None), (TEXT, ' bar'), (END, EMPHASIS), (END, STRONG)],
				[(TEXT, ' '), (STRONG, None), (TEXT, 'foo'), (TEXT, ' '), (EMPHASIS, None), (TEXT, 'bar'), (END, EMPHASIS), (END, STRONG)]
			),

			# <b><i><space></i></b> --> <space>
			(
				[(STRONG, None), (EMPHASIS, None), (TEXT, ' '), (END, EMPHASIS), (END, STRONG)],
				[(TEXT, ' ')]
			),

			# <b><i></i></b> -->  None
			(
				[(STRONG, None), (EMPHASIS, None), (END, EMPHASIS), (END, STRONG)],
				[]
			),

			# <b><i><space><img /></i></b> --> <space><b><i><img /></i></b>
			(
				[(STRONG, None), (EMPHASIS, None), (TEXT, ' '), (IMAGE, {}), (END, IMAGE), (END, EMPHASIS), (END, STRONG)],
				[(TEXT, ' '), (STRONG, None), (EMPHASIS, None), (IMAGE, {}), (END, IMAGE), (END, EMPHASIS), (END, STRONG)]
			),

		):
			got = list(strip_whitespace(iter(input)))
			self.assertEqual(got, want)


class TestTextFormat(tests.TestCase, TestFormatMixin):

	def setUp(self):
		self.format = get_format('plain')


class TestWikiFormat(tests.TestCase, TestFormatMixin):

	def setUp(self):
		self.format = get_format('wiki')

	def testFormattingInsideHeading(self):
		input = "====== heading @foo **bold** ======\n"
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><h level="1">heading <tag name="foo">@foo</tag> <strong>bold</strong>\n</h></zim-tree>'''
		t = self.format.Parser().parse(input)
		self.assertEqual(t.tostring(), xml)
		output = self.format.Dumper().dump(t)
		self.assertEqual(output, input.splitlines(True))

	def testNoFormattingInsideVerbatim(self):
		input = "test 1 2 3 ''code here **not bold!**''\n"
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p>test 1 2 3 <code>code here **not bold!**</code>\n</p></zim-tree>'''
		t = self.format.Parser().parse(input)
		self.assertEqual(t.tostring(), xml)

	def testUnicodeBullet(self):
		'''Test support for unicode bullets in source'''
		input = '''\
A list
• foo
	• bar
	• baz
'''
		text = '''\
A list
* foo
	* bar
	* baz
'''
		tree = self.format.Parser().parse(input)
		#~ print tree.tostring()
		output = self.format.Dumper().dump(tree)
		self.assertEqual(''.join(output), text)

	def testLink(self):
		'''Test iterator function for link'''
		# + check for bugs in link encoding
		text = '[[FooBar]] [[Foo|]] [[|Foo]] [[||]]'
		tree = self.format.Parser().parse(text)
		#~ print tree.tostring()
		found = 0
		for href in tree.iter_href():
			found += 1
		self.assertEqual(found, 2) # only unique href are processed

	def testNoURLWithinLink(self):
		# Ensure nested URL is not parsed
		text = '[[http://link.com/23060.html|//http://link.com/23060.html//]]'
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><link href="http://link.com/23060.html"><emphasis>http://link.com/23060.html</emphasis></link></p></zim-tree>'''
		tree = self.format.Parser().parse(text)
		self.assertEqual(tree.tostring(), xml)

	def testBackwardVerbatim(self):
		'''Test backward compatibility for wiki format'''
		input = '''\
test 1 2 3

	Some Verbatim block
	here ....

test 4 5 6
'''
		wanted = '''\
test 1 2 3

\'''
	Some Verbatim block
	here ....
\'''

test 4 5 6
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p>test 1 2 3
</p>
<pre>	Some Verbatim block
	here ....
</pre>
<p>test 4 5 6
</p></zim-tree>'''
		t = self.format.Parser(version='Unknown').parse(input)
		self.assertEqual(t.tostring(), xml)
		output = self.format.Dumper().dump(t)
		self.assertEqual(output, wanted.splitlines(True))

	def testBackwardURLParsing(self):
		input = 'Old link: http://///foo.com\n'
		wanted = 'Old link: [[http://///foo.com]]\n'
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p>Old link: <link href="http://///foo.com">http://///foo.com</link>
</p></zim-tree>'''

		t = self.format.Parser(version='zim 0.4').parse(input)
		self.assertEqual(t.tostring(), xml)
		output = self.format.Dumper().dump(t)
		self.assertEqual(output, wanted.splitlines(True))

	def testIndent(self):
		# Test some odditied pageview can give us
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><div indent="0">foo</div>
<div indent="0">bar</div>
<div indent="1">sub list</div>
<div indent="1">here</div>
<div indent="0">hmmm</div>
</zim-tree>'''
		wanted = '''\
foo
bar
	sub list
	here
hmmm
'''
		tree = ParseTree()
		tree.fromstring(xml)
		text = ''.join(self.format.Dumper().dump(tree))
		self.assertEqual(text, wanted)

	def testStringEscapeDoesNotGetEvaluated(self):
		text = "this is not a newline: \\name\n This is not a tab: \\tab \n"
		tree = self.format.Parser().parse(text)
		#~ print tree.tostring()
		output = self.format.Dumper().dump(tree)
		self.assertEqual(''.join(output), text)

	def testGFMAutolinks(self):
		text = 'Test 123 www.google.com/search?q=Markup+(business))) 456'
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p>Test 123 <link href="www.google.com/search?q=Markup+(business)">www.google.com/search?q=Markup+(business)</link>)) 456</p></zim-tree>'''
		t = self.format.Parser().parse([text])
		self.assertEqual(t.tostring(), xml)

	def testMatchingLinkBrackets(self):
		text = '[[[foo]]] [[[bar[baz]]]'
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p>[<link href="foo">foo</link>] [<link href="bar[baz]">bar[baz]</link></p></zim-tree>'''
		t = self.format.Parser().parse([text])
		self.assertEqual(t.tostring(), xml)

	def testNoNestedURLs(self):
		text = '[[http://example.com|example@example.com]]'
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><link href="http://example.com">example@example.com</link></p></zim-tree>'''
		t = self.format.Parser().parse([text])
		self.assertEqual(t.tostring(), xml)

	def testNoNestedLinks(self):
		text = '[[http://example.com|[[example@example.com]]]]'
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><link href="http://example.com">[[example@example.com]]</link></p></zim-tree>'''
		t = self.format.Parser().parse([text])
		self.assertEqual(t.tostring(), xml)

	def testLinkWithFormatting(self):
		text = '[[http://example.com| //Example// ]]' # spaces are crucial in this example - see issue #1306
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><link href="http://example.com"> <emphasis>Example</emphasis> </link></p></zim-tree>'''
		t = self.format.Parser().parse([text])
		self.assertEqual(t.tostring(), xml)

	def testAnchor(self):
		text = '{{id: test}}'
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><anchor name="test" /></p></zim-tree>'''
		tree = self.format.Parser().parse(text)
		self.assertEqual(tree.tostring(), xml)

	def testUnicodeSpecial(self):
		text = '''
		1. Some list item\u2029 with stray PARAGRAPH SEPARATOR
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree>
<p><ol indent="2" start="1"><li>Some list item  with stray PARAGRAPH SEPARATOR
</li></ol></p></zim-tree>'''
		tree = self.format.Parser().parse(text)
		self.assertEqual(tree.tostring(), xml)

	def testMissingNewline(self):
		# Partial content e.g. from copy-paste can miss trailing newline
		# for all BLOCK_LEVEL tags, need to be handled sane way on dump and parse
		input = {
			PARAGRAPH: ('<p>text 123</p>', 'text 123'),
			VERBATIM_BLOCK: ('<pre>text 123</pre>', "'''\ntext 123\n'''\n"),
			HEADING: ('<h level="3">text</h>', '==== text ====\n'),
			BLOCK: ('<p><div indent="1">text</div></p>', '\ttext'),
			LISTITEM: ('<p><ul><li bullet="*">text</li></ul></p>', '* text')
		}

		for tag in BLOCK_LEVEL:
			xml, wanted = input[tag]
			xml = "<?xml version='1.0' encoding='utf-8'?>\n<zim-tree>%s</zim-tree>" % xml
			tree = ParseTree().fromstring(xml)
			wiki = self.format.Dumper().dump(tree)
			self.assertEqual(''.join(wiki), wanted)
			if tag in (HEADING, VERBATIM_BLOCK):
				# These cannot retain the newline due to wiki formatting
				newtree = self.format.Parser().parse(wiki)
				self.assertEqual(newtree.tostring().replace('\n</', '</'), xml)
			else:
				newtree = self.format.Parser().parse(wiki)
				self.assertEqual(newtree.tostring(), xml)


class TestWikiListParsing(tests.TestCase):

	def setUp(self):
		self.format = get_format('wiki')

	def assertListParsing(self, text, xml, wanted=None):
		if wanted is None:
			wanted = text

		tree = self.format.Parser().parse(text)
		self.assertEqual(tree.tostring(), xml)

		lines = self.format.Dumper().dump(tree)
		result = ''.join(lines)
		#~ print('>>>\n' + result + '<<<')
		self.assertEqual(result, wanted)

		# Ensure round trip for topLevelLists() & reverseTopLevelLists()
		newtree = ParseTree.new_from_tokens(tree.iter_tokens())
		self.assertEqual(newtree.tostring(), xml)

	def testBulletList(self):
		text = '''\
* foo
* bar
	* sub list
	* here
		* etc
* hmmm
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><ul><li bullet="*">foo
</li><li bullet="*">bar
</li><ul><li bullet="*">sub list
</li><li bullet="*">here
</li><ul><li bullet="*">etc
</li></ul></ul><li bullet="*">hmmm
</li></ul></p></zim-tree>'''
		self.assertListParsing(text, xml)

	def testNumberedList(self):
		text = '''\
1. foo
2. bar
	a. sub list
	b. here
3. hmmm
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><ol start="1"><li>foo
</li><li>bar
</li><ol start="a"><li>sub list
</li><li>here
</li></ol><li>hmmm
</li></ol></p></zim-tree>'''
		self.assertListParsing(text, xml)

	def testNumberedListCapitals(self):
		text = '''\
A. foo
B. bar
C. hmmm
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><ol start="A"><li>foo
</li><li>bar
</li><li>hmmm
</li></ol></p></zim-tree>'''
		self.assertListParsing(text, xml)

	def testNumberedListStartingNumber(self):
		text = '''\
10. foo
11. bar
12. hmmm
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><ol start="10"><li>foo
</li><li>bar
</li><li>hmmm
</li></ol></p></zim-tree>'''
		self.assertListParsing(text, xml)

	def testInconsistentListBulletCheckbox(self):
		text = '''\
* foo
[ ] bar
* dus
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><ul><li bullet="*">foo
</li><li bullet="unchecked-box">bar
</li><li bullet="*">dus
</li></ul></p></zim-tree>'''
		wanted = '''\
* foo
[ ] bar
* dus
'''
		self.assertListParsing(text, xml, wanted)

	def testInconsistentListNumberedBullet(self):
		# Inconsistent lists get broken in multiple lists
		text = '''\
1. foo
4. bar
* hmmm
a. dus
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><ol start="1"><li>foo
</li><li>bar
</li></ol><ul><li bullet="*">hmmm
</li></ul><ol start="a"><li>dus
</li></ol></p></zim-tree>'''
		wanted = '''\
1. foo
2. bar
* hmmm
a. dus
'''
		self.assertListParsing(text, xml, wanted)

	def testInconsistentListBulletNumbered(self):
		text = '''\
* foo
4. bar
a. hmmm
* dus
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><ul><li bullet="*">foo
</li></ul><ol start="4"><li>bar
</li><li>hmmm
</li></ol><ul><li bullet="*">dus
</li></ul></p></zim-tree>'''
		wanted = '''\
* foo
4. bar
5. hmmm
* dus
'''
		self.assertListParsing(text, xml, wanted)

	def testInconsistentSubListBreaksList(self):
		text = '''\
* parent
	* foo
	4. bar
	a. hmmm
	* dus
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><ul><li bullet="*">parent
</li><ul><li bullet="*">foo
</li></ul><ol start="4"><li>bar
</li><li>hmmm
</li></ol><ul><li bullet="*">dus
</li></ul></ul></p></zim-tree>'''
		wanted = '''\
* parent
	* foo
	4. bar
	5. hmmm
	* dus
'''
		self.assertListParsing(text, xml, wanted)

	def testBulletListWithNumberedSubList(self):
		text = '''\
* foo
* bar
	1. sub list
	2. here
* hmmm
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><ul><li bullet="*">foo
</li><li bullet="*">bar
</li><ol start="1"><li>sub list
</li><li>here
</li></ol><li bullet="*">hmmm
</li></ul></p></zim-tree>'''
		self.assertListParsing(text, xml)

	def testIndentedList(self):
		text = '''\
	* foo
	* bar
		1. sub list
		2. here
	* hmmm
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><ul indent="1"><li bullet="*">foo
</li><li bullet="*">bar
</li><ol start="1"><li>sub list
</li><li>here
</li></ol><li bullet="*">hmmm
</li></ul></p></zim-tree>'''
		self.assertListParsing(text, xml)

	def testDoubleIndentSublistCleanup(self):
		# Double indent sub-list - clean up automatically
		text = '''\
* foo
* bar
		1. sub list
		2. here
	3. half jump back is same level
* hmmm
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p><ul><li bullet="*">foo
</li><li bullet="*">bar
</li><ol start="1"><li>sub list
</li><li>here
</li><li>half jump back is same level
</li></ol><li bullet="*">hmmm
</li></ul></p></zim-tree>'''
		wanted = '''\
* foo
* bar
	1. sub list
	2. here
	3. half jump back is same level
* hmmm
'''
		self.assertListParsing(text, xml, wanted)

	def testNotAList(self):
		text = '''\
foo.
dus ja.
1.3
'''
		xml = '''\
<?xml version='1.0' encoding='utf-8'?>
<zim-tree><p>foo.
dus ja.
1.3
</p></zim-tree>'''
		self.assertListParsing(text, xml)


class TestHtmlFormat(tests.TestCase, TestFormatMixin):

	def setUp(self):
		self.format = get_format('html')

	def testEncoding(self):
		'''Test HTML encoding'''
		builder = ParseTreeBuilder()
		builder.start(FORMATTEDTEXT)
		builder.append(PARAGRAPH, None, '<foo>"foo" & "bar"</foo>\n')
		builder.end(FORMATTEDTEXT)
		tree = builder.get_parsetree()
		html = self.format.Dumper(linker=StubLinker()).dump(tree)
		self.assertEqual(''.join(html),
			'<p>\n&lt;foo&gt;"foo" &amp; "bar"&lt;/foo&gt;\n</p>\n')

	# TODO add test using http://validator.w3.org

	def testEmptyLines(self):
		builder = ParseTreeBuilder()
		builder.start(FORMATTEDTEXT)
		builder.append(HEADING, {'level': 1}, 'head1\n')
		builder.text('\n\n')
		builder.append(HEADING, {'level': 2}, 'head2\n')
		builder.text('\n')
		builder.end(FORMATTEDTEXT)
		tree = builder.get_parsetree()

		html = self.format.Dumper(
			linker=StubLinker(),
			template_options={'empty_lines': 'default'}
		).dump(tree)
		self.assertEqual(''.join(html),
			'<h1>head1<a id="head1" class="h_anchor"></a></h1>\n'
			'<br>\n'
			'<br>\n'
			'<h2>head2<a id="head2" class="h_anchor"></a></h2>\n'
			'<br>\n'
		)

		for option in ('remove', 'Remove'):
			# test also case sensitivity
			html = self.format.Dumper(
				linker=StubLinker(),
				template_options={'empty_lines': option}
			).dump(tree)
			self.assertEqual(''.join(html),
				'<h1>head1<a id="head1" class="h_anchor"></a></h1>\n'
				'\n\n'
				'<h2>head2<a id="head2" class="h_anchor"></a></h2>\n'
				'\n'
			)

	def testLineBreaks(self):
		builder = ParseTreeBuilder()
		builder.start(FORMATTEDTEXT)
		builder.append(PARAGRAPH, None,
			'bla bla bla\n'
			'bla bla bla\n'
		)
		builder.end(FORMATTEDTEXT)
		tree = builder.get_parsetree()

		html = self.format.Dumper(
			linker=StubLinker(),
			template_options={'line_breaks': 'default'}
		).dump(tree)
		self.assertEqual(''.join(html),
			'<p>\n'
			'bla bla bla<br>\n'
			'bla bla bla\n'
			'</p>\n'
		)

		html = self.format.Dumper(
			linker=StubLinker(),
			template_options={'line_breaks': 'remove'}
		).dump(tree)
		self.assertEqual(''.join(html),
			'<p>\n'
			'bla bla bla\n'
			'bla bla bla\n'
			'</p>\n'
		)



class TestMarkdownFormat(tests.TestCase, TestFormatMixin):

	def setUp(self):
		self.format = get_format('markdown')

	def testFormat(self):
		# Override: markdown is both native and export format.
		# The standard testFormat dumps with linker (export mode) then
		# expects native XML round-trip on parse-back. This does not hold
		# because linker-resolved links don't map back to internal hrefs.
		# So we test export dump and parser separately.

		# 1. Dump with linker and verify all text is present
		reftree = tests.new_parsetree_from_xml(self.reference_xml)
		linker = StubLinker(tests.TEST_DATA_FOLDER.folder('formats'))
		dumper = self.format.Dumper(linker=linker)
		result = ''.join(dumper.dump(reftree))
		self.assertNoTextMissing(result, reftree)

		# Check that dumper did not modify the tree
		self.assertMultiLineEqual(reftree.tostring(), self.reference_xml)

		# 2. Partial dumper
		parttree = tests.new_parsetree_from_xml(
			"<?xml version='1.0' encoding='utf-8'?>\n"
			"<zim-tree>try these <strong>bold</strong>, "
			"<emphasis>italic</emphasis></zim-tree>"
		)
		result2 = ''.join(dumper.dump(parttree))
		self.assertFalse(result2.endswith('\n'))

		# 3. Parser: parse export output and verify text round-trip
		parser = self.format.Parser()
		tree = parser.parse(result)
		self.assertTrue(len(tree.tostring().splitlines()) > 10)
		string = ''.join(dumper.dump(tree))
		self.assertNoTextMissing(string, reftree)


class TestMarkdownNativeFormat(tests.TestCase, TestFormatMixin):
	'''Tests for Markdown as native storage format (without linker).'''

	def setUp(self):
		self.format = get_format('markdown')

	def getReferenceData(self, name=None):
		# Overload to ensure we get native version
		return TestFormatMixin.getReferenceData(self, name='markdown-native')

	def getDumper(self):
		# Overload to ensure we get native version - HACK native is detected by precense linker
		return self.format.Dumper(linker=None)

	def hackRoundtripReference(self, xml):
		return xml.replace(
			# HACK 1 - para broken by list indenting since we parse indent (blockquote) before para - fix with "toplevel lists"
			'<p>Indented list:\n<ul indent="1"><li bullet="*">item 1',
			'<p>Indented list:\n</p><p><ul indent="1"><li bullet="*">item 1'
		).replace(
			# HACK 2 - nesting bold and italic not parsed correctly - due to regex parsing with same symbol "*" - fix is to do parser according to commonmark appendix
			'normal <strike>strike  <strong>nested bold</strong> middle of the text <emphasis>italic <link href="https://example.org">link</link></emphasis> yet another text <strong>another bold <emphasis>yet another italic</emphasis></strong></strike> normal2',
			'normal <strike>strike  <strong>nested bold</strong> middle of the text <emphasis>italic <link href="https://example.org">link</link></emphasis> yet another text <strong>another bold *yet another italic</strong>*</strike> normal2',
		)

	def testFormatInfo(self):
		self.assertTrue(self.format.info['native'])
		self.assertTrue(self.format.info['import'])
		self.assertTrue(self.format.info['export'])
		self.assertEqual(self.format.info['extension'], 'md')

	def testParseHeadings(self):
		input = '# Heading 1\n\n## Heading 2\n\n### Heading 3\n'
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('<h level="1">Heading 1\n</h>', xml)
		self.assertIn('<h level="2">Heading 2\n</h>', xml)
		self.assertIn('<h level="3">Heading 3\n</h>', xml)

	def testParseFormatting(self):
		input = '**bold** *italic* ~~strike~~ `code` __mark__ ~sub~ ^sup^\n'
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('<strong>bold</strong>', xml)
		self.assertIn('<emphasis>italic</emphasis>', xml)
		self.assertIn('<strike>strike</strike>', xml)
		self.assertIn('<code>code</code>', xml)
		self.assertIn('<mark>mark</mark>', xml)
		self.assertIn('<sub>sub</sub>', xml)
		self.assertIn('<sup>sup</sup>', xml)

	def testParseTags(self):
		input = 'Some text @foo @bar more text\n'
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('<tag name="foo">@foo</tag>', xml)
		self.assertIn('<tag name="bar">@bar</tag>', xml)

	def testParseAnchors(self):
		input = '{#myanchor}\n'
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('<anchor name="myanchor"', xml)

	def testParseBulletList(self):
		input = '- item 1\n- item 2\n    - sub item\n- item 3\n'
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('<ul>', xml)
		self.assertIn('bullet="*"', xml)
		self.assertIn('item 1', xml)
		self.assertIn('item 2', xml)
		self.assertIn('sub item', xml)

	def testParseCheckboxList(self):
		input = '- [ ] unchecked\n- [x] checked\n'
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('bullet="unchecked-box"', xml)
		self.assertIn('bullet="xchecked-box"', xml)

	def testParseNumberedList(self):
		input = '1. first\n2. second\n3. third\n'
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('<ol', xml)

	def testParseFencedCode(self):
		input = '```python\ndef hello():\n    pass\n```\n'
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('<pre', xml)
		self.assertIn('lang="python"', xml)
		self.assertIn('def hello():', xml)

	def testParseTable(self):
		input = '| H1 | H2 |\n|---|---|\n| A | B |\n| C | D |\n'
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('<table', xml)
		self.assertIn('<th>H1</th>', xml)
		self.assertIn('<td>', xml)

	def testParseHorizontalRule(self):
		input = '---\n'
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('<line />', xml)

	def testDumperHeadings(self):
		builder = ParseTreeBuilder()
		builder.start(FORMATTEDTEXT)
		builder.append(HEADING, {'level': 1}, 'Head 1\n')
		builder.append(HEADING, {'level': 2}, 'Head 2\n')
		builder.end(FORMATTEDTEXT)
		tree = builder.get_parsetree()
		dumper = self.format.Dumper()
		result = ''.join(dumper.dump(tree))
		self.assertIn('# Head 1', result)
		self.assertIn('## Head 2', result)

	def testDumperFormatting(self):
		builder = ParseTreeBuilder()
		builder.start(FORMATTEDTEXT)
		builder.start(PARAGRAPH)
		builder.append(STRONG, {}, 'bold')
		builder.text(' ')
		builder.append(EMPHASIS, {}, 'italic')
		builder.text('\n')
		builder.end(PARAGRAPH)
		builder.end(FORMATTEDTEXT)
		tree = builder.get_parsetree()
		dumper = self.format.Dumper()
		result = ''.join(dumper.dump(tree))
		self.assertIn('**bold**', result)
		self.assertIn('*italic*', result)

	def testDumperFencedCode(self):
		builder = ParseTreeBuilder()
		builder.start(FORMATTEDTEXT)
		builder.append(VERBATIM_BLOCK, {'lang': 'python'}, 'print("hello")\n')
		builder.end(FORMATTEDTEXT)
		tree = builder.get_parsetree()
		dumper = self.format.Dumper()
		result = ''.join(dumper.dump(tree))
		self.assertIn('```python\n', result)
		self.assertIn('print("hello")\n', result)

	def testDumperCheckboxes(self):
		builder = ParseTreeBuilder()
		builder.start(FORMATTEDTEXT)
		builder.start(PARAGRAPH)
		builder.start(BULLETLIST)
		builder.append(LISTITEM, {'bullet': UNCHECKED_BOX}, 'todo\n')
		builder.append(LISTITEM, {'bullet': XCHECKED_BOX}, 'done\n')
		builder.end(BULLETLIST)
		builder.end(PARAGRAPH)
		builder.end(FORMATTEDTEXT)
		tree = builder.get_parsetree()
		dumper = self.format.Dumper()
		result = ''.join(dumper.dump(tree))
		self.assertIn('[ ]', result)
		self.assertIn('[x]', result)

	def testYAMLFrontMatter(self):
		input = (
			'---\n'
			'Creation-Date: 2024-01-01\n'
			'Content-Type: text/markdown\n'
			'Format: markdown 1.0\n'
			'---\n'
			'\n'
			'# Hello\n'
			'\n'
			'World\n'
		)
		parser = self.format.Parser()
		tree = parser.parse(input, file_input=True)
		self.assertEqual(tree.meta.get('Creation-Date'), '2024-01-01')

		# Dump back with file_output
		dumper = self.format.Dumper()
		result = ''.join(dumper.dump(tree, file_output=True))
		self.assertEqual(result, input)

	def testSimpleNativeRoundTrip(self):
		'''Test that parse -> dump -> parse gives consistent results.'''
		input = (
			'# Test Page\n'
			'\n'
			'Some **bold** and *italic* text with `code`.\n'
			'\n'
			'## Links\n'
			'\n'
			'[[Internal Page]]\n'
			'\n'
			'<http://example.com>\n'
			'\n'
			'## Lists\n'
			'\n'
			'- item 1\n'
			'- item 2\n'
			'  - sub item\n'
			'\n'
			'1. first\n'
			'2. second\n'
			'\n'
			'## Code\n'
			'\n'
			'```python\n'
			'def hello():\n'
			'    pass\n'
			'```\n'
			'\n'
			'---\n'
			'\n'
			'| H1 | H2 |\n'
			'|----|----|\n'
			'| A  | B  |\n'
		)
		parser = self.format.Parser()
		dumper = self.format.Dumper()

		# Parse
		tree1 = parser.parse(input)

		# Dump
		output = ''.join(dumper.dump(tree1))
		self.assertMultiLineEqual(output, input)

		# Parse again
		tree2 = parser.parse(output)
		self.assertMultiLineEqual(tree1.tostring(), tree2.tostring())

	def testNestedFormatting(self):
		input = '**bold and *italic* inside**\n'
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('<strong>', xml)
		self.assertIn('<emphasis>italic</emphasis>', xml)

	def testBlockquote(self):
		input = '> This is a quote\n> with more text\n'
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('<zim-tree><p><div indent="1">This is a quote\nwith more text\n</div></p></zim-tree>', xml)

	def testIndentedList(self):
		input = '''\
> - foo
> - bar
'''
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn('<zim-tree><p><ul indent="1"><li bullet="*">foo\n</li><li bullet="*">bar\n</li></ul></p></zim-tree>', xml)

	def testMixedBlockQuote(self):
		input = '''\
> My list:
> - foo
> - bar
> 
> > other block here
> > dus ja
'''
		wanted = '''\
<zim-tree><p><div indent="1">My list:
</div><ul indent="1"><li bullet="*">foo
</li><li bullet="*">bar
</li></ul></p>
<p><div indent="2">other block here
dus ja
</div></p></zim-tree>'''
		parser = self.format.Parser()
		tree = parser.parse(input)
		xml = tree.tostring()
		self.assertIn(wanted, xml)

	def testLinks(self):
		for markdown, xml in (
			('[](./foo.pdf)', '<p><link href="./foo.pdf">./foo.pdf</link></p>'),
			('[some text](./foo.pdf)', '<p><link href="./foo.pdf">some text</link></p>'),
			('[](./foo(part1).pdf)', '<p><link href="./foo(part1).pdf">./foo(part1).pdf</link></p>'), # balanced pair of ()
			('[](./foo(part1).pdf) and (this)', '<p><link href="./foo(part1).pdf">./foo(part1).pdf</link> and (this)</p>'), # balanced pair of ()
			('[](./foo\\(part1.pdf)', '<p><link href="./foo(part1.pdf">./foo(part1.pdf</link></p>'), # escaped (
			('[](./foo%20part1.pdf)', '<p><link href="./foo%20part1.pdf">./foo%20part1.pdf</link></p>'),
			('<http://example.com>', '<p><link href="http://example.com">http://example.com</link></p>'),
			('[[Page]]', '<p><link href="Page">Page</link></p>'),
			('[[Other Page|display]]', '<p><link href="Other Page">display</link></p>'),
		):
			self.assertParseAndDumpEquals(markdown, xml)

		for markdown, xml in (
			# Some test cases that should parse, but dump differently
			('[Page](Page)', '<p><link href="Page">Page</link></p>'),
			('[display](Other%20Page)', '<p><link href="Other%20Page">display</link></p>'),
		):
			self.assertParseEquals(markdown, xml)

	def testImages(self):
		for markdown, xml in (
			('![alt text](./image.png){width=500px}', '<p><img alt="alt text" src="./image.png" width="500" /></p>'),
			('![](./image.png){width=500px}', '<p><img src="./image.png" width="500" /></p>'),
			('![](./image.png){#myid width=500px}', '<p><img id="myid" src="./image.png" width="500" /></p>'),
			('![](./image.png)', '<p><img src="./image.png" /></p>'),
			('![](./image.png){href=Page}', '<p><img href="Page" src="./image.png" /></p>'),
			('![](./image.png){href="Page Foo %quot;Bar%quot;"}', '<p><img href="Page Foo %quot;Bar%quot;" src="./image.png" /></p>'),
		):
			self.assertParseAndDumpEquals(markdown, xml)


class TestRstFormat(tests.TestCase, TestFormatMixin):

	def setUp(self):
		self.format = get_format('rst')


class TestLatexFormat(tests.TestCase, TestFormatMixin):

	def setUp(self):
		self.format = get_format('latex')

	def testEncode(self):
		'''test the escaping of certain characters'''
		format = get_format('latex')

		input = r'\foo $ % ^ \% bar < >'
		wanted = r'$\backslash$foo \$  \% \^{} $\backslash$\% bar \textless{} \textgreater{}'
		self.assertEqual(format.Dumper.encode_text(PARAGRAPH, input), wanted)

	def testDocumentType(self):
		builder = ParseTreeBuilder()
		builder.start(FORMATTEDTEXT)
		builder.append(HEADING, {'level': 1}, 'head1\n')
		builder.text('\n')
		builder.append(HEADING, {'level': 2}, 'head2\n')
		builder.end(FORMATTEDTEXT)
		tree = builder.get_parsetree()

		for type, head1 in (
			('report', 'chapter'),
			('article', 'section'),
			('book', 'part'),
		):
			lines = self.format.Dumper(
				linker=StubLinker(),
				template_options={'document_type': type}
			).dump(tree)
			self.assertIn(head1, ''.join(lines))

	def testImagesWhitelist(self):
		builder = ParseTreeBuilder()
		builder.start(FORMATTEDTEXT)
		builder.append(IMAGE, {'src': 'test.png'})
		builder.text('\n')
		builder.append(IMAGE, {'src': 'test.tiff'})
		builder.text('\n')
		builder.append(IMAGE, {'src': 'test.tiff', 'href': 'foo'})
		builder.text('\n')
		builder.end(FORMATTEDTEXT)
		tree = builder.get_parsetree()

		wanted = [
			'\\includegraphics[]{test.png}\n', '\n',
			'\\href{test.tiff}{test.tiff}\n', '\n',
			'\\href{foo}{foo}\n', '\n'
		]
		lines = self.format.Dumper(linker=StubLinker()).dump(tree)
		self.assertEqual(lines, wanted)


class StubFile(object):

	def __init__(self, path, text):
		self.path = path
		self.text = text

	def read(self):
		return self.text


class TestMarkdownFlavors(tests.TestCase):
	'''Tests for markdown flavor support: parser, dumper, and lossiness detection.'''

	def _parser(self, flavor):
		from zim.formats.markdown import Parser
		return Parser(default_flavor=flavor)

	def _dumper(self, flavor):
		from zim.formats.markdown import Dumper
		return Dumper(flavor=flavor)

	# ---- flavor_from_format_string / format_string_for_flavor ----

	def testFlavorFromFormatString(self):
		from zim.formats.markdown import flavor_from_format_string, \
			FLAVOR_PANDOC, FLAVOR_GFM, FLAVOR_GLFM, FLAVOR_PHP_EXTRA, \
			FLAVOR_RMARKDOWN, FLAVOR_ORIGINAL
		# Current format strings
		self.assertEqual(flavor_from_format_string('markdown pandoc'),    FLAVOR_PANDOC)
		self.assertEqual(flavor_from_format_string('markdown gfm 0.31.2'), FLAVOR_GFM)
		self.assertEqual(flavor_from_format_string('markdown glfm'),      FLAVOR_GLFM)
		self.assertEqual(flavor_from_format_string('markdown php-extra'), FLAVOR_PHP_EXTRA)
		self.assertEqual(flavor_from_format_string('markdown rmarkdown'), FLAVOR_RMARKDOWN)
		self.assertEqual(flavor_from_format_string('markdown 1.0'),       FLAVOR_ORIGINAL)
		self.assertEqual(flavor_from_format_string(''),                   FLAVOR_PANDOC)
		# GLFM must not be swallowed by the GFM check
		self.assertNotEqual(flavor_from_format_string('markdown glfm'),   FLAVOR_GFM)

	def testFormatStringForFlavor(self):
		from zim.formats.markdown import format_string_for_flavor, \
			FLAVOR_PANDOC, FLAVOR_GFM, FLAVOR_GLFM, FLAVOR_PHP_EXTRA, \
			FLAVOR_RMARKDOWN, FLAVOR_ORIGINAL
		self.assertEqual(format_string_for_flavor(FLAVOR_PANDOC),    'markdown pandoc')
		self.assertEqual(format_string_for_flavor(FLAVOR_GFM),       'markdown gfm 0.31.2')
		self.assertEqual(format_string_for_flavor(FLAVOR_GLFM),      'markdown glfm')
		self.assertEqual(format_string_for_flavor(FLAVOR_PHP_EXTRA), 'markdown php-extra')
		self.assertEqual(format_string_for_flavor(FLAVOR_RMARKDOWN), 'markdown rmarkdown')
		self.assertEqual(format_string_for_flavor(FLAVOR_ORIGINAL),  'markdown 1.0')

	def testNewFlavorDumperHeaders(self):
		from zim.formats.markdown import FLAVOR_GLFM, FLAVOR_PHP_EXTRA, FLAVOR_RMARKDOWN
		for flavor, expected in (
			(FLAVOR_GLFM,      'Format: markdown glfm\n'),
			(FLAVOR_PHP_EXTRA, 'Format: markdown php-extra\n'),
			(FLAVOR_RMARKDOWN, 'Format: markdown rmarkdown\n'),
		):
			tree = self._parser('pandoc').parse('Hello\n')
			out = ''.join(self._dumper(flavor).dump(tree, file_output=True))
			self.assertIn(expected, out, 'Wrong header for flavor %s' % flavor)

	def testGLFMHasAnchors(self):
		# GLFM supports {#id} anchors (unlike GFM)
		from zim.formats.markdown import FLAVOR_GLFM, FLAVOR_GFM
		text = '# Heading {#my-id}\n'
		glfm_tree = self._parser(FLAVOR_GLFM).parse(text)
		self.assertIn('anchor', glfm_tree.tostring())
		gfm_tree = self._parser(FLAVOR_GFM).parse(text)
		self.assertNotIn('anchor', gfm_tree.tostring())

	def testGLFMNoSubscript(self):
		from zim.formats.markdown import FLAVOR_GLFM
		tree = self._parser('pandoc').parse('H~2~O\n')
		from unittest.mock import patch
		with patch('zim.formats.markdown.logger') as mock_log:
			out = ''.join(self._dumper(FLAVOR_GLFM).dump(tree))
		self.assertNotIn('~', out)  # subscript dropped as plain text fallback
		mock_log.warning.assert_called()

	def testPHPExtraNoTaskLists(self):
		from zim.formats.markdown import FLAVOR_PHP_EXTRA
		# PHP Extra parser has task_lists=False, so [ ] is preserved as text
		tree = self._parser(FLAVOR_PHP_EXTRA).parse('- [ ] todo\n- [x] done\n')
		xml = tree.tostring()
		self.assertNotIn('unchecked-box', xml)  # not parsed as checkbox
		self.assertIn('[ ]', xml)               # bracket text preserved in body
		# Dumper: checkbox nodes produced by pandoc parser fall back to plain text
		pandoc_tree = self._parser('pandoc').parse('- [ ] todo\n')
		self.assertIn('unchecked-box', pandoc_tree.tostring())
		from unittest.mock import patch
		with patch('zim.formats.markdown.logger'):
			out = ''.join(self._dumper(FLAVOR_PHP_EXTRA).dump(pandoc_tree))
		self.assertNotIn('[ ]', out)  # checkbox node dropped (no syntax in this flavor)

	def testPHPExtraNoStrikethrough(self):
		from zim.formats.markdown import FLAVOR_PHP_EXTRA
		tree = self._parser('pandoc').parse('~~deleted~~\n')
		self.assertIn('strike', tree.tostring())
		from unittest.mock import patch
		with patch('zim.formats.markdown.logger'):
			out = ''.join(self._dumper(FLAVOR_PHP_EXTRA).dump(tree))
		self.assertNotIn('~~', out)

	def testRMarkdownSameAsPandoc(self):
		# R Markdown inherits all Pandoc flags
		from zim.formats.markdown import FLAVOR_RMARKDOWN, FLAVOR_CONFIGS
		cfg = FLAVOR_CONFIGS[FLAVOR_RMARKDOWN]
		self.assertTrue(cfg.tables)
		self.assertTrue(cfg.subscript)
		self.assertTrue(cfg.superscript)
		self.assertTrue(cfg.mark)
		self.assertTrue(cfg.anchors)

	def testRMarkdownCodeChunkRoundtrip(self):
		# {r option=value} code fence must survive a round-trip
		from zim.formats.markdown import FLAVOR_RMARKDOWN
		text = '```{r fig.width=8, echo=FALSE}\nx <- 1:10\nmean(x)\n```\n'
		tree = self._parser(FLAVOR_RMARKDOWN).parse(text)
		out = ''.join(self._dumper(FLAVOR_RMARKDOWN).dump(tree))
		self.assertIn('{r fig.width=8, echo=FALSE}', out)

	def testNewFlavorsInFLAVORS(self):
		from zim.formats.markdown import FLAVORS, FLAVOR_GLFM, FLAVOR_PHP_EXTRA, FLAVOR_RMARKDOWN
		self.assertIn(FLAVOR_GLFM,      FLAVORS)
		self.assertIn(FLAVOR_PHP_EXTRA, FLAVORS)
		self.assertIn(FLAVOR_RMARKDOWN, FLAVORS)

	# ---- Parser flavor detection from YAML header ----

	def testParserAutoDetectFlavor(self):
		from zim.formats.markdown import FLAVOR_PANDOC, FLAVOR_GFM
		# File with GFM flavor header: subscript ~sub~ should be plain text
		text = (
			'---\n'
			'Content-Type: text/markdown\n'
			'Format: markdown 1.0 gfm\n'
			'---\n'
			'Hello ~sub~ ^sup^\n'
		)
		p = self._parser(FLAVOR_PANDOC)
		tree = p.parse(text, file_input=True)
		xml = tree.tostring()
		# In GFM mode ~sub~ and ^sup^ are NOT parsed as sub/sup
		self.assertNotIn('<sub>', xml)
		self.assertNotIn('<sup>', xml)
		self.assertIn('~sub~', xml)
		self.assertIn('^sup^', xml)

	def testParserDefaultFlavorUsedWhenNoHeader(self):
		from zim.formats.markdown import FLAVOR_GFM
		text = 'Hello ~sub~\n'
		p = self._parser(FLAVOR_GFM)
		tree = p.parse(text, file_input=False)
		xml = tree.tostring()
		self.assertNotIn('<sub>', xml)

	# ---- GFM parser: disabled extensions ----

	def testGFMParserNoSubscriptSuperscript(self):
		text = '~sub~ ^sup^\n'
		tree = self._parser('gfm').parse(text)
		xml = tree.tostring()
		self.assertNotIn('<sub>', xml)
		self.assertNotIn('<sup>', xml)
		self.assertIn('~sub~', xml)
		self.assertIn('^sup^', xml)

	def testGFMParserNoMark(self):
		text = '__marked__\n'
		tree = self._parser('gfm').parse(text)
		xml = tree.tostring()
		self.assertNotIn('<mark>', xml)

	def testGFMParserNoAnchors(self):
		text = 'text {#myanchor}\n'
		tree = self._parser('gfm').parse(text)
		xml = tree.tostring()
		self.assertNotIn('<anchor', xml)

	def testGFMParserStrikethroughStillWorks(self):
		text = '~~strike~~\n'
		tree = self._parser('gfm').parse(text)
		xml = tree.tostring()
		self.assertIn('<strike>strike</strike>', xml)

	def testGFMParserTablesStillWork(self):
		text = '| H1 | H2 |\n|---|---|\n| A | B |\n'
		tree = self._parser('gfm').parse(text)
		xml = tree.tostring()
		self.assertIn('<table', xml)

	# ---- Original flavor parser ----

	def testOriginalParserNoTables(self):
		text = '| H1 | H2 |\n|---|---|\n| A | B |\n'
		tree = self._parser('original').parse(text)
		xml = tree.tostring()
		self.assertNotIn('<table', xml)

	def testOriginalParserNoStrikethrough(self):
		text = '~~strike~~\n'
		tree = self._parser('original').parse(text)
		xml = tree.tostring()
		self.assertNotIn('<strike>', xml)
		self.assertIn('~~strike~~', xml)

	def testOriginalParserNoZimTags(self):
		text = 'Hello @tag\n'
		tree = self._parser('original').parse(text)
		xml = tree.tostring()
		self.assertNotIn('<tag', xml)
		self.assertIn('@tag', xml)

	def testOriginalParserNoFencedCode(self):
		text = '```python\ncode\n```\n'
		tree = self._parser('original').parse(text)
		xml = tree.tostring()
		# Fenced code not parsed as VERBATIM_BLOCK in original flavor
		self.assertNotIn('<pre', xml)

	def testOriginalParserTaskListTextPreserved(self):
		# When task_lists=False the "[ ] " / "[x] " marker must NOT be silently
		# dropped — it should appear as literal text in the list item.
		text = '- [ ] task 1\n- [x] task 2\n'
		tree = self._parser('original').parse(text)
		xml = tree.tostring()
		# Not rendered as checkboxes
		self.assertNotIn('unchecked-box', xml)
		self.assertNotIn('xchecked-box', xml)
		# But the bracket text must survive in the item content
		self.assertIn('[ ]', xml)
		self.assertIn('[x]', xml)

	def testOriginalParserIndentedCode(self):
		text = 'paragraph\n\n    code line 1\n    code line 2\n'
		tree = self._parser('original').parse(text)
		xml = tree.tostring()
		self.assertIn('<pre', xml)
		self.assertIn('code line 1', xml)

	# ---- Dumper: format header written correctly ----

	def testDumperWritesPandocHeader(self):
		tree = self._parser('pandoc').parse('Hello\n')
		out = ''.join(self._dumper('pandoc').dump(tree, file_output=True))
		self.assertIn('Format: markdown pandoc\n', out)

	def testDumperWritesGFMHeader(self):
		tree = self._parser('pandoc').parse('Hello\n')
		out = ''.join(self._dumper('gfm').dump(tree, file_output=True))
		self.assertIn('Format: markdown gfm 0.31.2\n', out)

	def testDumperWritesOriginalHeader(self):
		tree = self._parser('pandoc').parse('Hello\n')
		out = ''.join(self._dumper('original').dump(tree, file_output=True))
		self.assertIn('Format: markdown 1.0\n', out)

	# ---- Dumper: lossy fallbacks ----

	def testGFMDumperSubscriptFallback(self):
		tree = self._parser('pandoc').parse('~sub~\n')
		from unittest.mock import patch
		with patch('zim.formats.markdown.logger') as mock_log:
			out = ''.join(self._dumper('gfm').dump(tree))
		self.assertIn('sub', out)
		self.assertNotIn('~sub~', out)
		self.assertTrue(mock_log.warning.called)

	def testGFMDumperMarkFallback(self):
		tree = self._parser('pandoc').parse('__marked__\n')
		from unittest.mock import patch
		with patch('zim.formats.markdown.logger') as mock_log:
			out = ''.join(self._dumper('gfm').dump(tree))
		self.assertIn('marked', out)
		self.assertNotIn('__marked__', out)
		self.assertTrue(mock_log.warning.called)

	def testOriginalDumperStrikethroughFallback(self):
		tree = self._parser('pandoc').parse('~~strike~~\n')
		from unittest.mock import patch
		with patch('zim.formats.markdown.logger') as mock_log:
			out = ''.join(self._dumper('original').dump(tree))
		self.assertIn('strike', out)
		self.assertNotIn('~~', out)
		self.assertTrue(mock_log.warning.called)

	def testOriginalDumperIndentedCode(self):
		tree = self._parser('pandoc').parse('```\ncode\n```\n')
		out = ''.join(self._dumper('original').dump(tree))
		self.assertIn('    code', out)
		self.assertNotIn('```', out)

	def testGFMDumperNoPandocImageDimensions(self):
		from zim.formats import ParseTreeBuilder, IMAGE
		builder = ParseTreeBuilder()
		builder.start('zim-tree')
		builder.append(IMAGE, {'src': 'img.png', 'width': '500', 'height': '300'})
		builder.end('zim-tree')
		tree = builder.get_parsetree()
		out_pandoc = ''.join(self._dumper('pandoc').dump(tree))
		out_gfm    = ''.join(self._dumper('gfm').dump(tree))
		self.assertIn('width=500px', out_pandoc)
		self.assertNotIn('{', out_gfm)

	# ---- Round-trip: parse then dump gives back same flavor header ----

	def testGFMRoundTrip(self):
		original = (
			'---\n'
			'Content-Type: text/markdown\n'
			'Format: markdown gfm 0.31.2\n'
			'---\n\n'
			'Hello **world** ~~strike~~\n'
		)
		p = self._parser('gfm')
		tree = p.parse(original, file_input=True)
		out = ''.join(self._dumper('gfm').dump(tree, file_output=True))
		self.assertIn('Format: markdown gfm 0.31.2', out)
		self.assertIn('~~strike~~', out)

	# ---- Lossiness detection ----

	def testFindLossyElementsGFM(self):
		from zim.gui.pageformatdialog import find_lossy_elements
		tree = self._parser('pandoc').parse('~sub~ __mark__ ~~strike~~\n')
		lossy = find_lossy_elements(tree, 'markdown', 'gfm')
		self.assertIn('sub', lossy)
		self.assertIn('mark', lossy)
		self.assertNotIn('strike', lossy)  # GFM supports strikethrough

	def testFindLossyElementsOriginal(self):
		from zim.gui.pageformatdialog import find_lossy_elements
		tree = self._parser('pandoc').parse('~~strike~~ @tag\n')
		lossy = find_lossy_elements(tree, 'markdown', 'original')
		self.assertIn('strike', lossy)
		self.assertIn('tag', lossy)

	def testFindLossyElementsPandocNone(self):
		from zim.gui.pageformatdialog import find_lossy_elements
		tree = self._parser('pandoc').parse('~sub~ __mark__ ~~strike~~\n')
		lossy = find_lossy_elements(tree, 'markdown', 'pandoc')
		self.assertEqual(lossy, set())

	def testFindLossyElementsTaskList(self):
		# Checkbox items must be reported as lossy for flavors with task_lists=False
		from zim.gui.pageformatdialog import find_lossy_elements
		tree = self._parser('pandoc').parse('- [ ] unchecked\n- [x] done\n')
		for flavor in ('php-extra', 'original'):
			lossy = find_lossy_elements(tree, 'markdown', flavor)
			self.assertIn('task-list', lossy,
				'task-list not reported as lossy for flavor %s' % flavor)
		# Must NOT be reported for flavors that support task lists
		for flavor in ('pandoc', 'gfm', 'glfm', 'rmarkdown'):
			lossy = find_lossy_elements(tree, 'markdown', flavor)
			self.assertNotIn('task-list', lossy,
				'task-list falsely reported as lossy for flavor %s' % flavor)

	def testFindLossyElementsCodeLang(self):
		# Fenced code language annotations are lost in Original (uses indented code)
		from zim.gui.pageformatdialog import find_lossy_elements
		tree = self._parser('pandoc').parse('```python\ncode\n```\n')
		lossy_orig = find_lossy_elements(tree, 'markdown', 'original')
		self.assertIn('code-lang', lossy_orig)
		# Other flavors that support fenced code must NOT report this
		for flavor in ('pandoc', 'gfm', 'glfm', 'php-extra', 'rmarkdown'):
			lossy = find_lossy_elements(tree, 'markdown', flavor)
			self.assertNotIn('code-lang', lossy,
				'code-lang falsely reported as lossy for flavor %s' % flavor)
		# Plain code block with no lang attribute: not lossy even for original
		tree_nolang = self._parser('pandoc').parse('```\ncode\n```\n')
		lossy_nolang = find_lossy_elements(tree_nolang, 'markdown', 'original')
		self.assertNotIn('code-lang', lossy_nolang)

	def testGFMLossyRoundtrip(self):
		'''Page with all GFM-lossy elements converts to zim-wiki and back stably.

		GFM does not support underline/mark (__), subscript (~), superscript (^),
		named anchors ({#}), or zim tags (@).  After the first lossy conversion
		these elements become plain text; the second pass must produce identical
		output (no further degradation).  Also verifies that the YAML front-matter
		blank-line fix does not introduce extra blank lines on re-serialisation.
		'''
		from zim.formats import get_format_module
		from unittest.mock import patch

		wiki = get_format_module('wiki')

		# A pandoc source page that contains every GFM-lossy element plus
		# elements that GFM does support (bold, strike, table).
		pandoc_src = (
			'# Heading\n\n'
			'**bold** *italic* ~~strike~~\n\n'          # non-lossy in GFM
			'__mark__ ~sub~ ^sup^\n\n'                  # GFM-lossy: mark, subscript, superscript
			'{#anchor} @tag\n\n'                        # GFM-lossy: anchor, zim tag
			'| Col 1 | Col 2 |\n| --- | --- |\n| A | B |\n'  # table: OK in GFM
		)

		pandoc_tree = self._parser('pandoc').parse(pandoc_src)

		gfm_dumper = self._dumper('gfm')
		gfm_parser = self._parser('gfm')
		wiki_dumper = wiki.Dumper()
		wiki_parser = wiki.Parser()

		def one_roundtrip(tree):
			# tree → GFM → parse → zim-wiki → parse
			with patch('zim.formats.markdown.logger'):
				gfm_text = ''.join(gfm_dumper.dump(tree, file_output=True))
				gfm_tree = gfm_parser.parse(gfm_text, file_input=True)
			wiki_text = ''.join(wiki_dumper.dump(gfm_tree))
			return wiki_parser.parse(wiki_text), wiki_text

		tree1, wiki1 = one_roundtrip(pandoc_tree)
		tree2, wiki2 = one_roundtrip(tree1)

		# After the first lossy conversion the output must be stable
		self.assertEqual(wiki1, wiki2,
			'GFM lossy roundtrip is not stable after two passes')

		# Plain text of lost elements must survive (not be deleted)
		self.assertIn('mark', wiki1)
		self.assertIn('sub', wiki1)
		self.assertIn('sup', wiki1)
		# Markup syntax must NOT leak through as literal text
		self.assertNotIn('__mark__', wiki1)   # pandoc underline syntax
		self.assertNotIn('~sub~', wiki1)      # pandoc subscript syntax
		self.assertNotIn('^sup^', wiki1)      # pandoc superscript syntax


class TestParseHeaderLines(tests.TestCase):

	def runTest(self):
		text = '''\
Content-Type: text/x-zim-wiki
Wiki-Format: zim 0.4
X-Foo: Some text
	here
Creation-Date: 2010-12-14T14:15:09.134955

Blaat
'''
		body, meta = parse_header_lines(text)
		self.assertEqual(dict(meta), {
			'Content-Type': 'text/x-zim-wiki',
			'Wiki-Format': 'zim 0.4',
			'Creation-Date': '2010-12-14T14:15:09.134955',
			'X-Foo': 'Some text\nhere'
		})
		self.assertEqual(body, 'Blaat\n')

		out = dump_header_lines(meta)
		self.assertEqual(out + '\nBlaat\n', text)
