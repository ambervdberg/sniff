#!/usr/bin/env python3
"""Find the largest blocks of duplicated code, ranked by size.

no-duplicate-string finds repeated *literals*; this detector finds repeated
*logic*: copy-pasted methods, sync/async twins, the same guard clause written
out in three subclasses. It is the file-metric engine, not ast-grep: every file
is turned into a normalised token stream, and equal token windows are found with
a rolling hash (the Rabin-Karp scheme jscpd uses), so sniff stays a
self-contained Python CLI with no node dependency.

Normalising the tokens is what makes this more than a text diff:

  * identifiers collapse to `ID`, so a clone survives renaming,
  * literals collapse to `STR` / `NUM`, so a clone survives retuned constants,
  * `async` and `await` are dropped, so a sync method and its async twin match.

Keywords and punctuation are kept verbatim, so the *shape* of the code still has
to agree: two blocks match only when they do the same thing in the same order.

Usage:
    python -m sniff.detectors.duplicate_code [PATH] [--min-tokens N] [--min-lines N]
                                             [--top N] [--include-tests]

PATH defaults to '.'.
"""

from __future__ import annotations

import argparse
import bisect
import re
import sys
from collections import defaultdict
from dataclasses import dataclass

from sniff import harness as h

NAME = "duplicate-code"
TITLE = "Duplicated code blocks"
DEFAULT_ARGS: "list[str]" = []

# Tokenisation is regex-based, not parser-based, so every language the file walk
# recognizes is covered.
LANGUAGES = list(h.ALL_LANGUAGES)

# No parser involved, so this one still runs when ast-grep is missing.
NEEDS_AST_GREP = False

# A clone must be at least this long to be worth a row. Defaults are deliberately
# lower than jscpd's 50 tokens: the duplicates that matter in practice (a
# copy-pasted `peek()`, a repeated timeout callback) sit just under that line.
DEFAULT_MIN_TOKENS = 30
DEFAULT_MIN_LINES = 5

# Guards against ranking boilerplate above real duplication. A block whose lines
# are mostly imports, or that says almost nothing (a repeated data table of the
# same three tokens), is duplication a reader already expects.
MIN_UNIQUE_TOKENS = 8
MAX_IMPORT_LINE_RATIO = 0.5

# Any line this long means the file is generated, not written (see _looks_minified).
MINIFIED_LINE_LENGTH = 1000

# How many copies of one clone get their locations printed.
MAX_LOCATIONS_SHOWN = 3

# Comparing an anchor against every member of a huge bucket is quadratic on
# repetitive corpora, and the 30th copy tells the reader nothing the 12th did not.
MAX_GROUP_MEMBERS = 12


# --- token model ------------------------------------------------------------

# One pass over the source. Order matters: `skip` must come first so `//` is a
# comment rather than two punctuation tokens, and triple-quoted strings must be
# tried before their single-quoted prefixes.
TOKEN_RE = re.compile(
    r"""
      (?P<skip>
          \s+
        | //[^\n]*                  # C-family line comment
        | \#[^\n]*                  # Python / Ruby / PHP line comment
        | /\*.*?\*/                 # C-family block comment
      )
    | (?P<string>
          [A-Za-z]{0,2}\"\"\"(?:\\.|(?!\"\"\").)*\"\"\"    # Python triple-quoted
        | [A-Za-z]{0,2}'''(?:\\.|(?!''').)*'''
        | [A-Za-z]{0,2}"(?:\\.|[^"\\\n])*"
        | [A-Za-z]{0,2}'(?:\\.|[^'\\\n])*'
        | `(?:\\.|[^`\\])*`                                # JS template literal
      )
    | (?P<number>\d[A-Za-z0-9_.]*)
    | (?P<name>[A-Za-z_$][A-Za-z0-9_$]*)
    | (?P<punct>[^\s\w])
    """,
    re.VERBOSE | re.DOTALL,
)

# Kept verbatim, so structure still has to match. The union across supported
# languages: a keyword one language does not have simply never appears there.
KEYWORDS = frozenset("""
    if elif else for while do switch case default break continue return
    try catch except finally raise throw with using defer guard match when
    def class function func fn fun lambda struct interface enum impl trait
    import from export require include package namespace module
    const let var static final public private protected abstract override
    new delete yield in is of as not and or
    this self super null nil none true false undefined void
    None True False
""".split())

# Dropped entirely, so a method and its async twin produce the same token stream.
# The bead that asked for this detector calls that case out by name.
IGNORED_KEYWORDS = frozenset({"async", "await"})

# Line-leading keywords that make a line an import rather than logic.
IMPORT_KEYWORDS = frozenset({"import", "from", "require", "include", "using",
                             "package", "use", "export"})

NORMALIZED_STRING = "STR"
NORMALIZED_NUMBER = "NUM"
NORMALIZED_IDENTIFIER = "ID"


@dataclass
class Token:
    """One normalised token and the 1-based source line it came from."""

    value: str
    line: int


def tokenize(source: str) -> "list[Token]":
    """Turn source text into the normalised token stream clones are compared on."""
    line_starts = _line_starts(source)
    tokens: list[Token] = []

    for match in TOKEN_RE.finditer(source):
        value = _normalize(match)
        if value is None:
            continue
        tokens.append(Token(value, _line_of(match.start(), line_starts)))

    return tokens


def _normalize(match: "re.Match[str]") -> "str | None":
    """The normalised form of one raw token, or None when it carries no shape."""
    kind = match.lastgroup

    if kind == "skip":
        return None
    if kind == "string":
        return NORMALIZED_STRING
    if kind == "number":
        return NORMALIZED_NUMBER
    if kind == "punct":
        return match.group()

    word = match.group()
    if word in IGNORED_KEYWORDS:
        return None
    return word if word in KEYWORDS else NORMALIZED_IDENTIFIER


def _line_starts(source: str) -> "list[int]":
    """Offsets of every line start, so a token's line is a bisect away."""
    starts = [0]
    for offset, char in enumerate(source):
        if char == "\n":
            starts.append(offset + 1)
    return starts


def _line_of(offset: int, line_starts: "list[int]") -> int:
    """1-based line number for a character offset."""
    return bisect.bisect_right(line_starts, offset)


def read_tokens(path: str) -> "list[Token]":
    """Tokenise one file; an unreadable or generated file contributes nothing."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except OSError:
        return []

    return [] if _looks_minified(source) else tokenize(source)


def _looks_minified(source: str) -> bool:
    """Whether a file is a generated bundle rather than code anyone maintains.

    A committed minified bundle is thousands of tokens on a handful of lines, so
    it wins the ranking outright while telling the reader nothing they can act
    on: the duplication is the minifier's, not theirs."""
    lines = source.split("\n")
    if not lines:
        return False
    return max(len(line) for line in lines) > MINIFIED_LINE_LENGTH


# --- clone search -----------------------------------------------------------

@dataclass
class Occurrence:
    """One copy of a clone: where it sits in the source."""

    file: str
    start_line: int
    end_line: int

    @property
    def location(self) -> str:
        return f"{self.file}:{self.start_line}-{self.end_line}"


@dataclass
class Clone:
    """One duplicated block, plus every place it was found."""

    tokens: int
    occurrences: "list[Occurrence]"
    # True when the search stopped at MAX_GROUP_MEMBERS, so `copies` is a floor
    # rather than a count. The header says so, since an undercount presented as
    # a count is worse than a number the reader knows is partial.
    capped: bool = False

    @property
    def lines(self) -> int:
        """Physical line span of the first copy, the way the size detectors count."""
        first = self.occurrences[0]
        return first.end_line - first.start_line + 1

    @property
    def copies(self) -> int:
        return len(self.occurrences)


# Rolling-hash parameters. The modulus is a Mersenne prime, so collisions are
# rare; every candidate pair is still verified token by token before it counts.
_HASH_BASE = 257
_HASH_MOD = (1 << 61) - 1


class _Corpus:
    """Every file's tokens laid end to end, with the bookkeeping to stay in-file.

    Windows and clone extensions are clamped to file boundaries, so no clone can
    span two files just because they happen to be adjacent in the array."""

    def __init__(self, files: "list[str]"):
        self.ids: list[int] = []          # normalised token -> small int
        self.lines: list[int] = []        # 1-based source line per token
        self.file_of: list[str] = []      # owning file per token
        self.bounds: list[tuple[int, int]] = []  # [start, end) per file
        self.text_by_id: dict[int, str] = {}     # small int -> normalised token

        vocabulary: dict[str, int] = {}
        for path in files:
            start = len(self.ids)
            for token in read_tokens(path):
                token_id = vocabulary.setdefault(token.value, len(vocabulary))
                self.text_by_id[token_id] = token.value
                self.ids.append(token_id)
                self.lines.append(token.line)
                self.file_of.append(path)
            self.bounds.append((start, len(self.ids)))

        self._file_starts = [start for start, _ in self.bounds]

    def end_of_file_at(self, position: int) -> int:
        """Exclusive end of the file that owns `position`."""
        index = bisect.bisect_right(self._file_starts, position) - 1
        return self.bounds[index][1]

    def text_at(self, position: int) -> str:
        """The normalised token text at a position."""
        return self.text_by_id[self.ids[position]]


def find_clones(files: "list[str]", min_tokens: int, min_lines: int) -> "list[Clone]":
    """The maximal duplicated blocks across `files`, largest first."""
    corpus = _Corpus(files)
    window_hashes, buckets = _index_windows(corpus, min_tokens)

    claimed = bytearray(len(corpus.ids))
    clones: list[Clone] = []

    for position in sorted(window_hashes):
        if claimed[position]:
            continue

        members = _matching_windows(corpus, buckets[window_hashes[position]],
                                    position, min_tokens, claimed)
        if not members:
            continue

        group, length = _resolve_group(corpus, position, members, min_tokens, claimed)
        if len(group) < 2:
            continue

        clone = _build_clone(corpus, group, length,
                             capped=len(members) >= MAX_GROUP_MEMBERS)
        if clone.lines < min_lines or _is_boilerplate(corpus, position, length):
            continue

        _claim(claimed, group, length)
        clones.append(clone)

    clones.sort(key=lambda c: (c.tokens, c.copies, c.lines), reverse=True)
    return clones


def _index_windows(corpus: _Corpus, width: int) -> "tuple[dict[int, int], dict[int, list[int]]]":
    """Hash every in-file window of `width` tokens; group equal hashes together.

    Returns the hash per window start and the window starts per hash."""
    window_hashes: dict[int, int] = {}
    buckets: dict[int, list[int]] = defaultdict(list)

    # Highest power of the base, used to drop the token leaving the window.
    leading_power = pow(_HASH_BASE, width - 1, _HASH_MOD)

    for start, end in corpus.bounds:
        if end - start < width:
            continue

        digest = 0
        for position in range(start, start + width):
            digest = (digest * _HASH_BASE + corpus.ids[position] + 1) % _HASH_MOD

        window_hashes[start] = digest
        buckets[digest].append(start)

        for position in range(start + 1, end - width + 1):
            leaving = (corpus.ids[position - 1] + 1) * leading_power % _HASH_MOD
            digest = ((digest - leaving) * _HASH_BASE
                      + corpus.ids[position + width - 1] + 1) % _HASH_MOD
            window_hashes[position] = digest
            buckets[digest].append(position)

    return window_hashes, buckets


def _matching_windows(corpus: _Corpus, bucket: "list[int]", anchor: int,
                      width: int, claimed: bytearray) -> "list[int]":
    """The other copies of the window at `anchor`, verified token by token.

    A shared hash is only a hint; comparing the tokens is what makes a collision
    harmless. Copies already inside a bigger clone, and copies overlapping the
    anchor itself, are left out."""
    anchor_tokens = corpus.ids[anchor:anchor + width]
    matches: list[int] = []

    for candidate in bucket:
        if candidate == anchor or claimed[candidate]:
            continue
        if abs(candidate - anchor) < width and corpus.file_of[candidate] == corpus.file_of[anchor]:
            continue
        if corpus.ids[candidate:candidate + width] != anchor_tokens:
            continue

        matches.append(candidate)
        if len(matches) >= MAX_GROUP_MEMBERS:
            break

    return matches


def _resolve_group(corpus: _Corpus, anchor: int, members: "list[int]", width: int,
                   claimed: bytearray) -> "tuple[list[int], int]":
    """The copies that really are separate copies, and the length they share.

    In repetitive code (a run of near-identical delegating methods) a window
    matches a window a few tokens further along in the same run. Once the clone
    is extended those two ranges overlap, so they are one copy, not two: without
    this pruning the same 18 lines get reported as thirteen copies of itself.
    Dropping a copy can let the rest agree for longer, so length and membership
    are settled together."""
    group = sorted([anchor, *members])

    while True:
        length = _common_length(corpus, group, width, claimed)
        pruned = _without_overlaps(group, length)
        if len(pruned) == len(group):
            return group, length
        group = pruned


def _without_overlaps(starts: "list[int]", length: int) -> "list[int]":
    """Keep the earliest copy of every overlapping pair of token ranges."""
    kept: list[int] = []
    for start in starts:
        if kept and start < kept[-1] + length:
            continue
        kept.append(start)
    return kept


def _common_length(corpus: _Corpus, starts: "list[int]", width: int,
                   claimed: bytearray) -> int:
    """How far every copy keeps agreeing, so the reported clone is maximal.

    Extension stops at a file boundary and at any token already claimed by a
    bigger clone, which is what keeps two reported clones from overlapping."""
    limits = [corpus.end_of_file_at(start) for start in starts]
    length = width

    while True:
        offsets = [start + length for start in starts]
        if any(offset >= limit for offset, limit in zip(offsets, limits)):
            return length
        if any(claimed[offset] for offset in offsets):
            return length
        if len({corpus.ids[offset] for offset in offsets}) > 1:
            return length
        length += 1


def _build_clone(corpus: _Corpus, starts: "list[int]", length: int,
                 capped: bool = False) -> Clone:
    """Turn matching token ranges into the reportable clone."""
    return Clone(
        tokens=length,
        capped=capped,
        occurrences=[
            Occurrence(
                file=corpus.file_of[start],
                start_line=corpus.lines[start],
                end_line=corpus.lines[start + length - 1],
            )
            for start in starts
        ],
    )


def _claim(claimed: bytearray, starts: "list[int]", length: int) -> None:
    """Mark a clone's tokens as spoken for, so no smaller clone repeats them."""
    for start in starts:
        claimed[start:start + length] = b"\x01" * length


def _is_boilerplate(corpus: _Corpus, start: int, length: int) -> bool:
    """Whether a block is duplication a reader already expects.

    Three kinds are dropped: blocks that are mostly import lines, blocks that say
    almost nothing, and blocks with no keyword in them at all. The last one is
    data rather than logic (a lookup table long enough that one half of it
    matches the other half), and on a big front-end repo it otherwise outranks
    every copy-pasted method the ranking exists to surface."""
    window = range(start, start + length)

    unique_tokens = {corpus.ids[position] for position in window}
    if len(unique_tokens) < MIN_UNIQUE_TOKENS:
        return True

    if not any(corpus.text_at(position) in KEYWORDS for position in window):
        return True

    return _import_line_ratio(corpus, window) > MAX_IMPORT_LINE_RATIO


def _import_line_ratio(corpus: _Corpus, window: range) -> float:
    """Share of the block's lines whose first token is an import keyword."""
    first_token_of_line: dict[int, int] = {}
    for position in window:
        first_token_of_line.setdefault(corpus.lines[position], position)

    if not first_token_of_line:
        return 0.0

    import_lines = sum(1 for position in first_token_of_line.values()
                       if corpus.text_at(position) in IMPORT_KEYWORDS)
    return import_lines / len(first_token_of_line)


# --- CLI --------------------------------------------------------------------

def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find the largest blocks of duplicated code."
    )
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument(
        "--min-tokens", type=int, default=DEFAULT_MIN_TOKENS,
        help=f"smallest clone to report, in tokens (default: {DEFAULT_MIN_TOKENS})"
    )
    parser.add_argument(
        "--min-lines", type=int, default=DEFAULT_MIN_LINES,
        help=f"smallest clone to report, in lines (default: {DEFAULT_MIN_LINES})"
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="how many to show (default: 10)"
    )
    parser.add_argument(
        "--include-tests", action="store_true",
        help="include *.spec.* / *.test.* files"
    )
    parser.add_argument(
        "--extra-ignore", action="append", default=[],
        help="glob to exclude, relative to PATH (repeatable)"
    )
    args = parser.parse_args(argv)

    files = h.iter_source_files(args.path, include_tests=args.include_tests,
                                extra_ignores=args.extra_ignore)
    if not files:
        sys.exit(f"No supported source files found under {args.path!r}.")

    clones = find_clones(files, min_tokens=args.min_tokens, min_lines=args.min_lines)
    if not clones:
        print(
            f"No code blocks of {args.min_lines}+ lines duplicated "
            f"(min {args.min_tokens} tokens; tests "
            f"{'included' if args.include_tests else 'excluded'})."
        )
        return 0

    header = (
        f"Duplicated code blocks, largest first "
        f"({len(clones)} found; min {args.min_lines} lines / {args.min_tokens} tokens; "
        f"tests {'included' if args.include_tests else 'excluded'}):"
    )
    if any(clone.capped for clone in clones[:args.top]):
        header += (
            f"\nCOPIES stops counting at {MAX_GROUP_MEMBERS + 1} per block, "
            f"so the highest counts are a floor."
        )

    h.print_table(
        clones,
        columns=[
            ("TOKENS", lambda c: c.tokens),
            ("LINES", lambda c: c.lines),
            ("COPIES", lambda c: c.copies),
            ("LOCATIONS", _locations_cell),
        ],
        sort_key=lambda c: c.tokens,
        top=args.top,
        header=header,
    )
    return 0


def _locations_cell(clone: Clone) -> str:
    """Where the copies live, truncated so one clone cannot flood the table."""
    shown = [o.location for o in clone.occurrences[:MAX_LOCATIONS_SHOWN]]
    hidden = clone.copies - len(shown)
    return ", ".join(shown) + (f", +{hidden} more" if hidden else "")


if __name__ == "__main__":
    sys.exit(main())
