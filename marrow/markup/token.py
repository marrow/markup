# encoding: utf-8

"""Basic token types for use by parsers."""


class Token(object):
	def __lt__(self, other):
		return self.length < len(other)
	
	def __len__(self):
		return self.length

class InlineToken(Token):
	"""Inline token definition."""
	
	__slots__ = ('annotation', 'match')
	
	def __init__(self, annotation, match):
		self.annotation = annotation if isinstance(annotation, set) else ({annotation} if isinstance(annotation, str) else set(annotation))
		self.match = match
	
	def __call__(self, context, stream, offset):
		match = self.match
		length = len(match)
		
		if not offset.startswith(match):
			return
		
		def inline_token_generator():
			yield slice(offset, offset + length), "meta:invisible"
			yield slice(offset + length, 0), self
		
		return inline_token_generator()

class EnclosingToken(Token):
	"""Token definition for tokens which surround other text."""
	# NOTE: The prototype differentiated single-character from multi-character markup; check performance.
	
	__slots__ = ('annotation', 'prefix', 'suffix', 'length')  # Don't construct a new __dict__ for each instance.
	
	def __init__(self, annotation, prefix, suffix=None):
		self.annotation = annotation
		self.prefix = prefix
		self.suffix = suffix
		self.length = len(prefix)
	
	def __repr__(self):
		return "Token({}, {}, {})".format(self.annotation, self.prefix, self.suffix)
	
	def __call__(self, context, stream, offset):
		length = self.length
		end = stream.find(self.suffix, offset+length)
		
		if stream[offset:offset+length] != self.prefix or end < 0:
			return
		
		def enclosing_token_generator():
			ol = offset + length
			yield slice(offset, ol), "meta:invisible"
			yield slice(ol, end), self
			yield slice(end, end + len(self.suffix)), "meta:invisible"
		
		return enclosing_token_generator()
	
	def partition(self, text):
		for i in range(len(text)):
			result = list(self(None, text, i))
			if result:
				break
		
		pl = i - 1
		(pr, pa), (tr, ta), (sr, sa) = result
		
		return (text[:pl], text[tr], text[sr.stop:])



