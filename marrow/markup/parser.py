# encoding: utf-8

"""Primary parser structures common to all format-specific parsers."""

from bisect import bisect


class Parser(object):
	def __init__(self):
		self.tokens = []
	
	def add(self, token):
		"""Register a token with the parser.
		
		This maintains the ordered nature of the token list by token length.
		"""
		self.tokens.insert(bisect(self.tokens, token), token)
	
	def __call__(self, text):
		"""Generate a series of annotations for the given input text."""
		
		# Version 1: exhaustive search.
		i = 0

		while i < len(text):
			for token in self.tokens:
				result = token(None, text, i)
				if result:
					i += len(token)
					yield from result
					break
			else:
				i += 1



