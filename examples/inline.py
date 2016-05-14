from marrow.markup.parser import Parser
from marrow.markup.token import EnclosingToken

parse = Parser()
parse.add(EnclosingToken('font-weight:bold', '*', '*'))
parse.add(EnclosingToken('font-style:italic', '_', '_'))
parse.add(EnclosingToken('font-family:fixed', '`', '`'))

text = "This `example` is *neither* complete _nor_ complete, *though _simple_*."

