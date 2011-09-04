# encoding: utf-8

from __future__ import unicode_literals, print_function

import string

from cStringIO import StringIO

from functools import partial

from marrow.util.convert import array
from marrow.util.bunch import Bunch
from marrow.tags import html5 as tag


class Signature(Bunch):
    def __repr__(self):
        return b'Signature(' + str(self.block) + \
                ((', #' + self.id) if self.id else '') + \
                ((', class="' + ', '.join(self.classes) + '"') if self.classes else '') + ')'


class BlockRegistry(object):
    def __init__(self):
        self.tokens = []
    
    def register(self, block, fn):
        self.tokens.append((block, fn))


class InlineToken(object):
    def __repr__(self):
        return "Token(%s)" % (self.tag, )
    
    def __init__(self, start, end=None, tag=None):
        super(InlineToken, self).__init__()
        
        self.start = start
        self.end = end if end else start
        self.tag = tag
    
    def validate(self, stream):
        return stream[0] == self.start and stream.find(self.end, 1) > 1
    
    def enter(self, stream):
        yield stream
        yield ('enter', self.tag())
    
    def exit(self, stream):
        yield stream
        yield ('exit', None)


class LongInlineToken(InlineToken):
    def validate(self, stream):
        return stream.startswith(self.start) and stream.find(self.end, len(self.start)) > 0


class UnformattedToken(LongInlineToken):
    """No substitutions should appear within this token."""
    
    def enter(self, stream):
        end = 0
        while True:
            end = stream.index(self.end, end + 1)
            if stream[end-1] != '\\':
                break
            
            stream = stream[:end-1] + stream[end:]
            end -= 1
        
        yield stream[end:]
        yield ('enter', self.tag())
        yield ('text', stream[:end])
    
    def exit(self, stream):
        yield stream
        yield ('exit', None)


class LinkToken(InlineToken):
    """No substitutions should appear within this token."""
    
    def enter(self, stream):
        #print("Entering link: {0!r}".format(stream))
        yield stream
        yield ('enter', self.tag())
    
    def exit(self, stream):
        linkbreak = string.ascii_letters + string.digits + '.-_:/@#'
        
        for i, c in enumerate(stream):
            if c not in linkbreak:
                yield stream[i:]
                yield ('attr', ('href', stream[:i]))
                break
        
        else:
            if stream[-1] == '.':
                yield '.'
                yield ('attr', ('href', stream[:-1]))
            
            else:
                yield ""
                yield ('attr', ('href', stream))
        
        yield ('exit', None)


class FootnoteToken(InlineToken):
    def enter(self, stream):
        end = 0
        while True:
            end = stream.index(self.end, end + 1)
            if stream[end-1] != '\\':
                break
            
            stream = stream[:end-1] + stream[end:]
            end -= 1
        
        fn = stream[:end]
        if not fn.isdigit():
            # TODO: Store the footnote in the current parser and get index.
            fn = '0'
        
        yield stream[end:]
        yield ('enter', tag.sup())
        yield ('enter', tag.a())
        yield ('attr', ('href', '#fn' + fn))
        yield ('attr', ('rel', 'footnote'))
        yield ('text', fn)
    
    def exit(self, stream):
        yield stream
        yield ('exit', None) # a
        yield ('exit', None) # sup


class InlineRegistry(object):
    def __init__(self):
        super(InlineRegistry, self).__init__()
        self.tokens = dict()
    
    def register(self, token, symbol=None):
        if symbol:
            start, end = (symbol if isinstance(symbol, tuple) == 2 else (symbol, None))
            token = InlineToken(start, end, token) if len(start) == 1 else LongInlineToken(start, end, token)
        
        if token.start[0] not in self.tokens:
            self.tokens[token.start[0]] = []
        
        self.tokens[token.start[0]].append(token)


class Parser(object):
    _blocks = BlockRegistry()
    
    _blocks.register('ol', lambda _, __: _[0] == '#')
    _blocks.register('ul', lambda _, __: _[0] in ('*', '-'))
    _blocks.register('menu', lambda _, __: _[0] == ':')
    _blocks.register('dl', lambda _, __: _[-1] == ':' and len(__) > 1 and __[1][0] in (' ', '\t'))
    _blocks.register('table', lambda _, __: _[0] == _[-1] == '|')
    _blocks.register('link', lambda _, __: _[0] == '[' and ']' in _ and '/' in _ and ' ' not in _)
    _blocks.register('footnote', lambda _, __: _[:2] == 'fn' and _.split('.', 1)[0][2:].isdigit())
    
    _inline = InlineRegistry()
    
    _inline.register(tag.strong, '*')
    _inline.register(tag.em, '_')
    #_inline.register(tag.del_, '-')
    #_inline.register(tag.ins, '+')
    _inline.register(tag.span, '%')
    _inline.register(tag.sup, '^')
    _inline.register(tag.sub, '~')
    _inline.register(tag.cite, '??')
    _inline.register(tag.b, '**')
    _inline.register(tag.i, '__')
    _inline.register(UnformattedToken('@', tag=tag.code))
    _inline.register(LinkToken('"', '":', tag=tag.a))
    _inline.register(FootnoteToken('[', ']'))
    
    _replacements = {
            ' - ': '–',
            ' -- ': '—',
            '(c)': "©",
            '(C)': "©",
            '(r)': "®",
            '(R)': "®",
            '(tm)': "™",
            '(TM)': "™",
            '...': '…',
            ' x ': '×'
        }
    
    _short = dict(
            bq = "blockquote",
        )
    
    _lists = ('#', '*', '-', ':')
    
    def __init__(self, input, encoding='utf-8'):
        self._input = StringIO(input.encode('utf8')) if isinstance(input, unicode) else input
        self._encoding = encoding
        self._footnotes = []
        self._links = dict()
    
    def render(self, *args, **kw):
        root = tag.div(strip=True)
        root.children = list(self(*args, **kw))
        return unicode(root)
    
    def __call__(self, *args, **kw):
        self._input.seek(0)
        
        signature, remainder = self._signature('first.')
        chunks = self._chunks
        
        while True:
            if signature and not signature.sticky:
                signature = None
            
            try:
                chunk = chunks.next()
            except StopIteration:
                return
            
            #print("Chunk: {0!r}".format(chunk))
            
            _ = chunk[0]
            
            if _[0] in (' ', '\t'):
                # Leading whitespace trumps all else.
                # Possibilities: block quote, lists. (\s+\w = quote, \s+[*#-] = list)
                __ = _.lstrip()
                if __[0] in self._lists:
                    _ = __
                else:
                    signature, remainder = self._signature('bq.')
            
            for block, validate in self._blocks.tokens:
                if validate(_, chunk):
                    signature, remainder = self._signature(block + '.')
                    #print("Signature match:", signature)
                    break
            
            else:
                _ = self._signature(_)
                #print("Default signature:", _)
                
                if _:
                    signature, remainder = _
                    
                    if remainder:
                        chunk[0] = remainder
                    else:
                        del chunk[0]
            
            if not signature:
                signature, remainder = self._signature('p.')
            
            if signature.block[0] == '_':
                raise Exception("Invalid block; stop trying to mess with the parser!")
            
            processor = getattr(self, signature.block, None)
            if not processor:
                processor = self._default
                chunk = self._unformat(chunk)
            
            result = processor(chunk, signature=signature)
            
            if result:
                yield result
    
    @property
    def _chunks(self):
        # Read until we reach a blank line or a line with leading whitespace.
        chunk = []
        
        for line in (l.rstrip('\n') for l in self._input):
            if not isinstance(line, unicode):
                line = line.decode(self._encoding)
            
            if not chunk and line:
                chunk.append(line)
                continue
            
            if not line:
                if not chunk:
                    continue
                
                yield chunk
                chunk = []
                continue
            
            chunk.append(line)
        
        if chunk: yield chunk
    
    def _signature(self, line):
        """Determine if this line is a block signature.
        
        Valid block signature format:
            element(class,class#id){style:value;style:...}[lang]...
        
        (There may be one to three trailing periods.  One is standard,
        two indicate a sticky block, three indicate a sticky continuous
        block.)
        """
        block = None
        identifier = None
        classes = list()
        styles = list()
        language = None
        sticky = False
        continuous = False
        
        block, _, remainder = line.partition('.')
        remainder = remainder.lstrip()
        
        #print("Defaulting line:", block)
        #print("Defaulting remainder:", remainder)
        
        if not _ or block[0] in (' ', '\t'):
            #print("No separator or first character is whitespace.")
            return None
        
        if '(' in line:
            block, _, line = line.partition('(')
            idcls, _, line = line.partition(')')
            classes, _, identifier = idcls.partition('#')
            classes = [i.strip() for i in classes.split()]
        
        if '{' in line:
            pre, _, line = line.partition('{')
            if not block: block = pre
            elif pre:
                #print("Exiting due to presence of { prefix.")
                return None
            styles, _, line = line.partition('}')
            styles = array(styles, ';')
        
        if '[' in line:
            pre, _, line = line.partition('[')
            if not block: block = pre
            elif pre:
                #print("Exiting due to presence of [ prefix.")
                return None
            language, _, line = line.partition(']')
        
        if ' ' in block or not block.isalnum():
            #print("Exiting due to space in block: {0!r}".format(block))
            return None
        
        # level, _, remainder = line.rpartition('.')
        # 
        # if level and level.strip('.') or not (len(level) <= 2):
        #     # There is stuff left over; this doesn't match a signature!
        #     return None
        
        # sticky = len(level) >= 1
        # continuous = len(level) == 2
        
        return Signature(
                block = block,
                id = identifier or None,
                classes = classes,
                styles = styles,
                language = language or None,
                sticky = sticky,
                continuous = continuous
            ), remainder
    
    def _unformat(self, chunk, *args, **kw):
        text = " ".join(chunk).format(*args, **kw)
        
        for i in self._replacements:
            text = text.replace(i, self._replacements[i])
        
        return text
    
    def _format(self, text):
        """Perform inline element expantion."""
        
        def tokenize(source):
            source = source
            
            stack = []
            tokens = self._inline.tokens
            
            while source:
                for i, char in enumerate(source):
                    token = stack[-1] if stack else None
                    
                    # if token: print("\tLooking for {0!r} at position {1} in {2!r}...".format(token.end, i, source))
                    if token and source.find(token.end) == i:
                        # print("\tFound.")
                        
                        if i > 0:
                            if source[i-1] == '\\':
                                yield 'text', source[:i-2] + char
                                source = source[:i]
                                break
                            
                            yield 'text', source[:i]
                            source = source[i:]
                        
                        emitter = token.exit(source[len(token.end):])
                        source = emitter.next()
                        
                        for chunk in emitter:
                            if chunk[0] == 'enter':
                                stack.append(token)
                            if chunk[0] == 'exit':
                                stack.pop()
                            
                            yield chunk
                        
                        break
                    
                    if char not in tokens:
                        continue
                    
                    remainder = source if i == 0 else source[i:]
                    
                    for token in tokens[char]:
                        if token.validate(remainder):
                            break
                    else:
                        continue
                    
                    if i > 0:
                        if source[i-1] == '\\' or source[i-1] not in (' ', '\t'):
                            yield 'text', source[:i] + char
                            source = source[i+1:]
                            break
                        
                        yield 'text', source[:i]
                        source = remainder
                    
                    emitter = token.enter(source[len(token.start):])
                    source = emitter.next()
                    
                    for chunk in emitter:
                        if chunk[0] == 'enter':
                            stack.append(token)
                        elif chunk[0] == 'exit':
                            stack.pop()
                        
                        yield chunk
                    
                    break
                
                if source and i == len(source) - 1:
                    yield 'text', source
                    break
        
        stack = [tag.span(strip=True)]
        
        for action, value in tokenize(text):
            # print("Tokenized: {0} {1!r}".format(action, value))
            if action == 'enter':
                value = value()
                stack[-1].children.append(value)
                stack.append(value)
            
            elif action == 'exit':
                stack.pop()
            
            elif action == 'attr':
                name, value = value
                if name == 'href':
                    if value[0] not in ('#', '/') and ':' not in value:
                        value = self._get_link(value)
                
                stack[-1].attrs[name] = value
            
            else:
                stack[-1].children.append(value)
        
        return stack[0]
    
    def _get_link(self, name):
        def inner(context):
            return self._links.get(name, '')
        
        return inner
    
    def _default(self, text, signature):
        node = getattr(tag, self._short.get(signature.block, signature.block))()
        
        return node(
                id_ = signature.id or None,
                class_ = ' '.join(signature.classes) or None,
                style = '; '.join(signature.styles) or None
            )[ self._format(text) ]
    
    def list(self, chunk, signature, kind='ul'):
        parent = getattr(tag, kind)
        stack = []
        indentation = 0
        
        for line in chunk:
            if line.lstrip()[0] not in ('#', '*', '-', ':'):
                stack[-1].children[-1].children.append(line)
            
            if line[0] in (' ', '\t'):
                # Determine indentation level.
                level = len(line) - len(line.lstrip())
                
                if level > indentation:
                    node = parent()
                    if stack: stack[-1][0].children.append(node)
                    stack.append((node, level))
                
                elif level < indentation:
                    for i, element in enumerate(stack):
                        if element[1] == level:
                            break
                    
                    else:
                        raise Exception("Unknown list level.")
                    
                    del stack[i]
                
                indentation = level
                line = line.lstrip()
            
            symbols, _, line = line.partition(' ')
            
            if len(symbols) > len(stack) + 1:
                raise Exception("Attempted to skip list level.")
            
            if len(symbols) > len(stack):
                node = parent()
                if stack: stack[-1][0].children.append(node)
                stack.append((node, indentation))
            
            stack[-1][0].children.append(tag.li[self._format(line)])
        
        return stack[0][0](id_=signature.id or None, class_=' '.join(signature.classes) or None, style='; '.join(signature.styles) or None)
    
    def ul(self, chunk, signature):
        return self.list(chunk, signature, 'ul')
    
    def ol(self, chunk, signature):
        return self.list(chunk, signature, 'ol')
    
    def menu(self, chunk, signature):
        return self.list(chunk, signature, 'menu')
    
    def dl(self, chunk, signature):
        dl = tag.dl()
        
        for line in chunk:
            if line[0] not in (' ', '\t'):
                dl.children.append(tag.dt[self._format(line)])
            else:
                dl.children.append(tag.dd[self._format(line.lstrip())])
        
        return dl
    
    def pre(self, chunk, signature):
        return tag.pre(
                id_ = signature.id or None,
                class_ = ' '.join(signature.classes) or None,
                style = '; '.join(signature.styles) or None
            )[ "\n".join(chunk) ]
    
    def code(self, chunk, signature):
        signature.classes.insert(0, 'code')
        return self.pre(chunk, signature)
    
    def table(self, chunk, signature):
        return "TABLE"
    
    def link(self, chunk, signature):
        for line in chunk:
            name, _, link = line[1:].partition(']')
            self._links[name] = link.strip()
        
        return ""
    
    def flush(self, chunk, signature):
        return tag.flush
    
    def bq(self, chunk, signature):
        paragraphs = [[]]
        
        for line in chunk:
            if not line.strip():
                paragraphs.append([])
                continue
            
            paragraphs[-1].append(line)
        
        return tag.blockquote(
                id_ = signature.id or None,
                class_ = ' '.join(signature.classes) or None,
                style = '; '.join(signature.styles) or None
            )[ ( tag.p[self._format(self._unformat(p))] for p in paragraphs ) \
                    if len(paragraphs) > 1 else self._format(self._unformat(paragraphs[0])) ]
    
    def page(self, chunk, signature):
        return "\f"
    
    def footnote(self, chunk, signature):
        level, _, chunk[0] = chunk[0].partition('.')
        
        return tag.blockquote(
                id_ = signature.id or level,
                class_ = 'footnote' + (' ' + ' '.join(signature.classes) or ''),
                style = '; '.join(signature.styles) or None,
                rev = "footnote"
            )[ [tag.label["Footnote " + level[2:]]] + [tag.p[self._format(i)] for i in chunk if i.strip()] ]
