"""Tokenizer for ST. Keywords and identifiers both come out as IDENT; ST is case-insensitive,
so the parser compares `tok.upper` and keeps `tok.text` for names as the author spelled them."""
from __future__ import annotations

import re
from dataclasses import dataclass


class STParseError(ValueError):
    def __init__(self, message: str, line: int = 0, column: int = 0):
        super().__init__(f"line {line}:{column}: {message}" if line else message)
        self.line = line
        self.column = column


@dataclass(frozen=True)
class Token:
    kind: str  # IDENT TIME TYPED BASED REAL INT OP END
    text: str
    line: int
    column: int

    @property
    def upper(self) -> str:
        return self.text.upper()


_SKIP = re.compile(r"\s+|\(\*.*?\*\)|//[^\n]*", re.DOTALL)
# Order matters: `T#1s` must not lex as the identifier `T`, and `1..3` must not lex `1.` as a real.
_TOKENS = [
    ("TIME", re.compile(r"(?:TIME|T)#[-+]?[0-9a-zA-Z_.]+", re.IGNORECASE)),
    ("TYPED", re.compile(r"[A-Za-z_][A-Za-z0-9_]*#[-+]?[0-9a-zA-Z_.#]+")),
    ("BASED", re.compile(r"(?:2|8|16)#[0-9a-fA-F_]+")),
    ("REAL", re.compile(r"\d[\d_]*\.\d[\d_]*(?:[eE][-+]?\d+)?|\d[\d_]*[eE][-+]?\d+")),
    ("INT", re.compile(r"\d[\d_]*")),
    ("IDENT", re.compile(r"[A-Za-z_][A-Za-z0-9_]*")),
    ("OP", re.compile(r":=|=>|<=|>=|<>|\*\*|\.\.|[-+*/=<>(),;:.&]")),
]


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    line = 1
    line_start = 0
    while pos < len(source):
        skipped = _SKIP.match(source, pos)
        if skipped:
            text = skipped.group()
            newlines = text.count("\n")
            if newlines:
                line += newlines
                line_start = pos + text.rfind("\n") + 1
            pos = skipped.end()
            continue
        if source.startswith("(*", pos):
            raise STParseError("unterminated comment", line, pos - line_start + 1)
        for kind, pattern in _TOKENS:
            match = pattern.match(source, pos)
            if match:
                tokens.append(Token(kind, match.group(), line, pos - line_start + 1))
                pos = match.end()
                break
        else:
            hint = ": arrays are outside the v1 subset" if source[pos] == "[" else ""
            raise STParseError(f"unexpected character {source[pos]!r}{hint}", line, pos - line_start + 1)
    tokens.append(Token("END", "", line, pos - line_start + 1))
    return tokens
