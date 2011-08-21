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


class Registry(object):
    def __init__(self):
        self.tokens = []
    
    def __call__(self, block):
        def inner(fn):
            self.register(block, fn)
            return fn
    
    def register(self, block, fn):
        self.tokens.append((block, fn))


class Parser(object):
    registry = Registry()
    
    registry.register('ol', lambda _, __: _[0] == '#')
    registry.register('ul', lambda _, __: _[0] in ('*', '-'))
    registry.register('menu', lambda _, __: _[0] == ':')
    registry.register('dl', lambda _, __: _[-1] == ':' and len(__) > 1 and __[1][0] in (' ', '\t'))
    registry.register('table', lambda _, __: _[0] == _[-1] == '|')
    registry.register('link', lambda _, __: _[0] == '[' and ']' in _ and '/' in _ and ' ' not in _)
    
    replacements = {
            '\'': ('‘', '’'),
            '\"': ('“', '”'),
            '-': '–',
            '--': '—',
            '(c)': "©",
            '(C)': "©",
            '(r)': "®",
            '(R)': "®",
            '(tm)': "™",
            '(TM)': "™"
        }
    
    short = dict(
            bq = "blockquote",
        )
    
    lists = ('#', '*', '-', ':')
    
    def __init__(self, input, encoding='utf-8'):
        self.input = StringIO(input) if isinstance(input, unicode) else input
        self.encoding = encoding
        self.footnoes = []
        self.links = dict()
    
    def __call__(self, *args, **kw):
        self.input.seek(0)
        
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
                if __[0] in self.lists:
                    _ = __
                else:
                    signature, remainder = self._signature('bq.')
            
            for block, validate in self.registry.tokens:
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
        
        for line in (l.rstrip('\n') for l in self.input):
            if not isinstance(line, unicode):
                line = line.decode(self.encoding)
            
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
        
        for i in self.replacements:
            if isinstance(self.replacements[i], tuple):
                continue # we can't handle these yet
            
            text = text.replace(i, self.replacements[i])
        
        return text
    
    def _format(self, text):
        # Perform inline element expantion.
        
        
        
        return text
    
    def _default(self, text, signature):
        node = getattr(tag, self.short.get(signature.block, signature.block))()
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
        return "DEFINITION LIST"
    
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
        self.links[name] = link
        return ""
    
    def flush(self, chunk, signature):
        return tag.flush
    
    def bq(self, chunk, signature):
        paragraphs = [i.strip() for i in chunk if i.strip()]
        
        return tag.blockquote(
                id_ = signature.id or None,
                class_ = ' '.join(signature.classes) or None,
                style = '; '.join(signature.styles) or None
            )[ ( tag.p[self._format(p)] for p in paragraphs ) if len(paragraphs) > 1 else self._format(paragraphs[0]) ]
    
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

if __name__ == '__main__':
    main()
