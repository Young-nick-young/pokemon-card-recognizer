#!/usr/bin/env python3
"""Read-only standard-printing discovery from a user-supplied treatment CSV.
Output is evidence for review, not an approved inventory or deployment.
"""
import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

FINISH = {'normal': 'normal', 'reverse': 'reverse-holo', 'holo': 'holo'}


def discover(path, set_name, expected, denominator):
    cards = {}
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        required = {'record_type', 'set', 'definition', 'name', 'collector_number', 'rarity', 'category', 'finish', 'patterns'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Missing required treatment CSV columns')
        for row in reader:
            if row['record_type'] == 'summary':
                continue
            if row['record_type'] != 'card' or row['set'] != set_name or row['definition'] != 'treatment':
                raise ValueError('Unexpected record type, set or definition')
            m = re.fullmatch(r'(\d+)/(\d+)', row['collector_number'].strip())
            if not m or int(m[2]) != denominator:
                raise ValueError('Unexpected numbering namespace: ' + row['collector_number'])
            number = int(m[1])
            finish = FINISH.get(row['finish'].strip().lower())
            if not finish or row['patterns'].strip():
                raise ValueError('Unmapped finish or pattern; manual reconciliation required')
            fields = {k: row[k].strip() for k in ('name', 'rarity', 'category')}
            if not all(fields.values()):
                raise ValueError('Incomplete card metadata')
            card = cards.setdefault(number, {'number': number, **fields, 'standard_variants': []})
            if any(card[k] != v for k,v in fields.items()) or finish in card['standard_variants']:
                raise ValueError('Conflicting metadata or duplicate printing: ' + str(number))
            card['standard_variants'].append(finish)
    if set(cards) != set(range(1, expected + 1)):
        raise ValueError('Collector number coverage mismatch')
    return [cards[n] for n in sorted(cards)]


def compare(cards, catalogue):
    existing = {}
    for card in catalogue['cards']:
        number = card['number']['sortKey']
        if number in existing:
            raise ValueError('Duplicate existing collector number')
        existing[number] = card
    if set(existing) != {c['number'] for c in cards}:
        raise ValueError('Existing catalogue coverage mismatch')
    diffs = []
    for c in cards:
        old = existing[c['number']]
        if old['name'] != c['name']:
            raise ValueError('Card name mismatch at ' + str(c['number']))
        before, after = set(old['variants']), set(c['standard_variants'])
        if before != after:
            diffs.append({'cardId': old['cardId'], 'unconfirmed_existing': sorted(before-after), 'missing_existing': sorted(after-before)})
    return diffs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv', type=Path)
    p.add_argument('--set-name', required=True)
    p.add_argument('--expected', required=True, type=int)
    p.add_argument('--denominator', required=True, type=int)
    p.add_argument('--catalogue', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cards = discover(a.csv, a.set_name, a.expected, a.denominator)
    counts = Counter(v for c in cards for v in c['standard_variants'])
    report = {'status': 'REVIEW_REQUIRED', 'source': 'user-supplied treatment CSV', 'set': a.set_name, 'standard_printings_only': True, 'exclusive_printings_verified': False, 'card_count': len(cards), 'printing_counts': dict(counts), 'cards': cards}
    if a.catalogue:
        report['differences'] = compare(cards, json.loads(a.catalogue.read_text(encoding='utf-8')))
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f'{len(cards)} cards; {sum(counts.values())} standard printings; REVIEW_REQUIRED')


if __name__ == '__main__':
    main()
