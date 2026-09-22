"""Expand Rhasspy sentences.ini files into flat templates for autocomplete.

Only the spoken form matters here, so tags ({name}, {name:value}),
substitutions (word:sub, (a | b):sub) and converters (!int) are dropped.
Number ranges (1..100) and $slot references are not expanded -- they would
blow up the output (the alarm time alone is 24*60 combinations) -- and stay
as placeholder tokens the page fills in from what the user typed.

See https://rhasspy.readthedocs.io/en/latest/training/#sentencesini
"""
import re
from itertools import product

# Safety net against a grammar with lots of stacked optionals.
MAX_TEMPLATES = 20000

_SECTION = re.compile(r'^\[([^\]]+)\]$')
_RULE = re.compile(r'^([\w.-]+)\s*=\s*(.*)$')
_RANGE = re.compile(r'^(-?\d+)\.\.(-?\d+)(?:,(\d+))?$')
_TAG = re.compile(r'\{[^}]*\}')
_SUBSTITUTION = re.compile(r':[^\s()\[\]|<>{}]*')
_CONVERTER = re.compile(r'![\w,]+')
_TOKEN = re.compile(r'[()\[\]|]|<[^>]+>|\$[\w.-]+|[^\s()\[\]|<>]+')


def parse_ini(text):
    """Return {intent: {'sentences': [raw lines], 'rules': {name: raw body}}}."""
    intents = {}
    current = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        section = _SECTION.match(line)
        if section:
            current = intents.setdefault(section.group(1), {'sentences': [], 'rules': {}})
            continue
        if current is None:
            continue
        rule = _RULE.match(line)
        if rule:
            current['rules'][rule.group(1)] = rule.group(2)
        else:
            current['sentences'].append(line)
    return intents


class _Expander:
    def __init__(self, intents):
        self.intents = intents
        self.cache = {}

    def expand_intent(self, intent):
        variants = []
        for line in self.intents[intent]['sentences']:
            variants.extend(self._expand(line, intent))
        return variants

    def _expand(self, raw, intent):
        cleaned = _CONVERTER.sub('', _SUBSTITUTION.sub('', _TAG.sub('', raw)))
        tokens = _TOKEN.findall(cleaned)
        variants, pos = self._alt(tokens, 0, intent)
        if pos != len(tokens):
            raise ValueError(f'unbalanced brackets in [{intent}]: {raw}')
        return variants

    def _alt(self, tokens, pos, intent):
        variants, pos = self._seq(tokens, pos, intent)
        while pos < len(tokens) and tokens[pos] == '|':
            more, pos = self._seq(tokens, pos + 1, intent)
            variants = variants + more
        return variants, pos

    def _seq(self, tokens, pos, intent):
        parts = []
        while pos < len(tokens) and tokens[pos] not in ('|', ')', ']'):
            item, pos = self._item(tokens, pos, intent)
            parts.append(item)
        variants = [()]
        for item in parts:
            if len(variants) * len(item) > MAX_TEMPLATES:
                raise ValueError(f'[{intent}] expands to too many sentences')
            variants = [a + b for a, b in product(variants, item)]
        return variants, pos

    def _item(self, tokens, pos, intent):
        tok = tokens[pos]
        if tok in ('(', '['):
            closing = ')' if tok == '(' else ']'
            variants, pos = self._alt(tokens, pos + 1, intent)
            if pos >= len(tokens) or tokens[pos] != closing:
                raise ValueError(f'missing "{closing}" in [{intent}]')
            if tok == '[':
                variants = [()] + variants
            return variants, pos + 1
        if tok.startswith('<'):
            return self._rule(tok[1:-1], intent), pos + 1
        if tok.startswith('$'):
            return [({'slot': tok[1:]},)], pos + 1
        number_range = _RANGE.match(tok)
        if number_range:
            low, high, step = number_range.groups()
            return [({'min': int(low), 'max': int(high), 'step': int(step or 1)},)], pos + 1
        return [(tok.lower(),)], pos + 1

    def _rule(self, name, intent):
        # <rule> is local to the intent, <Intent.rule> reaches into another
        # one, and <Intent> alone pulls in all of that intent's sentences.
        if '.' in name:
            owner, rule = name.split('.', 1)
        elif name in self.intents.get(intent, {}).get('rules', {}):
            owner, rule = intent, name
        else:
            owner, rule = name, None
        key = (owner, rule)
        if key not in self.cache:
            self.cache[key] = []  # breaks reference cycles
            if rule is None:
                self.cache[key] = self.expand_intent(owner)
            else:
                self.cache[key] = self._expand(self.intents[owner]['rules'][rule], owner)
        return self.cache[key]


def build_templates(ini_texts):
    """Flatten one or more sentences.ini texts into
    [{'intent': name, 'tokens': [word | {'min','max','step'} | {'slot'}]}]."""
    intents = {}
    for text in ini_texts:
        intents.update(parse_ini(text))
    expander = _Expander(intents)
    templates, seen = [], set()
    for intent in intents:
        for variant in expander.expand_intent(intent):
            if not variant:
                continue
            key = (intent, repr(variant))
            if key in seen:
                continue
            seen.add(key)
            templates.append({'intent': intent, 'tokens': list(variant)})
    return templates
