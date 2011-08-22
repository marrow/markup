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


class InlineRegistry(object):
    def __init__(self):
        self.tokens = dict()
    
    def register(self, symbol, tag):
        if not isinstance(symbol, tuple):
            symbol = (symbol, symbol)
        
        self.tokens[symbol] = tag


class Parser(object):
    """
    
    *bold text*
    _italic text_
    *_bold italic text_*
    -strikethrough text-
    *-bold strikethrough text-*
    *_-bold italic strikethrough text-_*
    +underlined text+
    *+bold underlined text+*
    _+italic underlined text+_
    *_+bold italic underlined text+_*
    *_-+bold italic strikethrough underlined text+-_*
    %{font-size:18pt}font size%
    %{color:red}text in red%
    Brand ^TM^
    Text ~subscript~
    
    # Chapter 1
    * bulleted list
    
    |Table | with two columns |
    
    "Link to Wikipedia":http://www.wikipedia.org
    
    !http://commons.wikimedia.org/wiki/Special:Filepath/Wikipedia-logo-en.png!
    
    fn1. footnote
    
    ABC(Always Be Closing)
    
    [n]
    
    """
    
    _blocks = BlockRegistry()
    
    _blocks.register('ol', lambda _, __: _[0] == '#')
    _blocks.register('ul', lambda _, __: _[0] in ('*', '-'))
    _blocks.register('menu', lambda _, __: _[0] == ':')
    _blocks.register('dl', lambda _, __: _[-1] == ':' and len(__) > 1 and __[1][0] in (' ', '\t'))
    _blocks.register('table', lambda _, __: _[0] == _[-1] == '|')
    _blocks.register('link', lambda _, __: _[0] == '[' and ']' in _ and '/' in _ and ' ' not in _)
    
    _inline = InlineRegistry()
    
    _inline.register('%', tag.span)
    _inline.register('@', tag.code)
    _inline.register('*', tag.strong)
    _inline.register('_', tag.em)
    _inline.register('-', tag.del_)
    _inline.register('+', tag.ins)
    _inline.register('^', tag.sup)
    _inline.register('~', tag.sub)
    _inline.register('??', tag.cite)
    # _inline.register('"', lambda t: (None, '“' + t[1:-1] + '”'))
    # _inline.register("'", lambda t: (None, '‘' + t[1:-1] + '’'))
    
    def _footnote(self, text):
        if not text.isdigit():
            self._footnotes.append(text)
            text = str(len(self._footnotes))
        
        return tag.sup [ tag.a ( href = '#fn' + text ) [ text ] ], None
    
    _inline.register(('[', ']'), _footnote)
    
    _replacements = {
            '-': '–',
            '--': '—',
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
        self._input = StringIO(input) if isinstance(input, unicode) else input
        self._encoding = encoding
        self._footnotes = []
        self._links = dict()
    
    def __call__(self, *args, **kw):
        self._input.seek(0)
        
        signature, remainder = self._signature('first.')
        chunks = self._chunks
        
        while True:
            if not signature.sticky:
                signature = None
            
            try:
                chunk = chunks.next()
            except StopIteration:
                return
            
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
            
            else:
                _ = self._signature(_)
                
                if _:
                    signature, remainder = _
                    
                    if remainder:
                        chunk[0] = remainder
                    else:
                        del chunk[0]
            
            if not signature:
                signature, remainder = self._signature('p.')
            
            # print("Signature: ", signature, "\n", "Chunk: ", pformat(chunk), sep="", end="\n\n")
            
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
                # print("Appending initial line.")
                chunk.append(line)
                continue
            
            if not line:
                # print("Empty line.")
                
                if not chunk:
                    # print("No chunk.")
                    continue
                
                yield chunk
                chunk = []
                continue
            
            # print("Appending chunk.")
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
        
        line, _, remainder = line.partition('.')
        remainder = remainder.lstrip()
        
        if not _ or line[0] in (' ', '\t'):
            return None
        
        if '(' in line:
            block, _, line = line.partition('(')
            idcls, _, line = line.partition(')')
            if ' ' in idcls: return None
            classes, _, identifier = idcls.partition('#')
            classes = array(classes)
        
        if '{' in line:
            pre, _, line = line.partition('{')
            if not block: block = pre
            elif pre: return None
            styles, _, line = line.partition('}')
            styles = array(styles, ';')
        
        if '[' in line:
            pre, _, line = line.partition('[')
            if not block: block = pre
            elif pre: return None
            language, _, line = line.partition(']')
        
        if not block:
            if ' ' in line or not line.isalpha():
                return None
            
            block = line
        
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
        
        text = text.strip() + ' '
        
        # Now do everything else.
        
        generated = []
        stack = [('', tag.span(strip=True), [])] # (expects, node)
        tokens = dict((i[0], (i[1], self._inline.tokens[i])) for i in self._inline.tokens)
        last = 0
        
        for i, char in enumerate(text):
            if last > i: continue
            
            # First we determine if we're closing an existing element from the stack.
            if stack and char in stack[-1][0] and (not i or text[i-1] != '\\'):
                # Pop off the stack; this node is already a child of the parent.
                expect, token, children = stack.pop()
                
                children.append(text[last:i])
                last = i + 1
                
                token = token() [ children ]
                stack[-1][2].append(token)
                
                continue
            
            # Now we determine if we're going deeper into the stack.
            if char in tokens and (not i or text[i-1] != '\\'):
                if char in (i[0] for i in stack) and text.find(char, i+1) == -1:
                    # pre-mature close
                    pass
                
                if text.find(tokens[char][0], i+1) == -1:
                    continue
                
                stack[-1][2].append(text[last:i])
                last = i + 1
                
                expect, token = tokens[char]
                stack.append((expect, token, []))
                
                continue
        
        # Compress the stack.
        while len(stack) > 1:
            expect, token, children = stack.pop()
            token = token()
            token.children.extend(children)
            
            stack[-1][2].append(token)
        
        expect, token, children = stack.pop()
        children.append(text[last:])
        token = token()
        token.children.extend(children)
        
        return token
    
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
            
            stack[-1][0].children.append(tag.li[line])
        
        return stack[0][0](id_=signature.id or None, class_=' '.join(signature.classes) or None, style='; '.join(signature.styles) or None)
    
    def ul(self, chunk, signature):
        return self.list(chunk, signature, 'ul')
    
    def ol(self, chunk, signature):
        return self.list(chunk, signature, 'ol')
    
    def menu(self, chunk, signature):
        return self.list(chunk, signature, 'menu')
    
    def dl(self, chunk, signature):
        return "DEFINITION LIST\n"
    
    def pre(self, chunk, signature):
        return tag.pre(
                id_ = signature.id or None,
                class_ = ' '.join(signature.classes) or None,
                style = '; '.join(signature.styles) or None
            )[ "\n".join(chunk) ]
    
    def code(self, chunk, signature):
        return self.pre(chunk, signature)
    
    def table(self, chunk, signature):
        return "TABLE"
    
    def link(self, chunk, signature):
        name, _, link = chunk[0][1:].partition(']')
        self._links[name] = link
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


def main():
    texting = Parser(open('../../test.text', 'r'))
    print(unicode(tag.div[texting()]))
    
    with open('test.html', 'w') as fh:
        fh.write(unicode(tag.html [
                tag.head [
                    tag.title [ "Texting Test" ]
                ],
                tag.body [
                    texting()
                ]
            ]).encode('utf-8'))


def main2():
    texting = Parser("")
    
    print(unicode(texting._format("test *two* _bar_")))


if __name__ == '__main__':
    main()
