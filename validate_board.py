#!/usr/bin/env python3
"""Validate the committed Board transition, not mutable working-tree files.

An unchanged canonical blob passes so zero-card NHL sidecars can be published
without replacing a previously dated Board. A changed canonical blob must be
an NHL card-bearing payload and equal to the producer sidecar byte for byte.
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path


def blob(repo, revision, path):
    result = subprocess.run(['git', '-C', str(repo), 'show', f'{revision}:{path}'],
                            capture_output=True)
    if result.returncode:
        # Distinguish an absent path from an invalid revision or a git error.
        tree = subprocess.run(['git', '-C', str(repo), 'cat-file', '-e', f'{revision}^{{tree}}'],
                              capture_output=True)
        if tree.returncode:
            raise ValueError(f'cannot resolve revision {revision}')
        return None
    return result.stdout


def parse(raw):
    def unique(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise ValueError(f'duplicate JSON key: {key}')
            data[key] = value
        return data

    def nonfinite(value):
        raise ValueError(f'nonfinite JSON number: {value}')

    data = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    if not isinstance(data, dict):
        raise ValueError('dashboard must be an object')
    return data


def slate_date(data):
    meta = data.get('meta')
    meta_date = meta.get('slate_date') if isinstance(meta, dict) else None
    day = data.get('slate_date', meta_date)
    if not isinstance(day, str) or len(day) != 10:
        raise ValueError('missing ISO slate_date')
    try:
        value = dt.date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError('invalid slate_date') from exc
    if value.isoformat() != day or (meta_date is not None and meta_date != day):
        raise ValueError('conflicting or noncanonical slate_date')
    return value


def validate(repo, base, candidate):
    before = blob(repo, base, 'dashboard_data.json') if base else None
    after = blob(repo, candidate, 'dashboard_data.json')
    if after is not None and before == after:
        return 'canonical unchanged (sidecar-only commit permitted)'
    if after is None:
        raise ValueError('dashboard_data.json deleted')
    data = parse(after)
    if data.get('sport') != 'NHL':
        raise ValueError('dashboard must declare sport NHL')
    day = slate_date(data)
    arms = data.get('arms')
    if not isinstance(arms, dict) or not arms:
        raise ValueError('NHL dashboard needs nonempty arms')
    count = 0
    for name, arm in arms.items():
        if not isinstance(name, str) or not name or not isinstance(arm, dict) or not isinstance(arm.get('cards'), list):
            raise ValueError('invalid NHL arm/cards list')
        for card in arm['cards']:
            if not isinstance(card, dict) or not isinstance(card.get('legs'), list) or not card['legs']:
                raise ValueError('NHL card requires nonempty legs')
            if any(not isinstance(leg, dict) or not leg for leg in card['legs']):
                raise ValueError('NHL card has invalid leg')
            count += 1
    if not count:
        raise ValueError('zero-card dashboard overwrite refused')
    sidecar = blob(repo, candidate, 'nhl_daily.json')
    if sidecar != after:
        raise ValueError('dashboard and NHL producer sidecar must match exact bytes')
    # The sidecar and dashboard are identical bytes: this checks both dates.
    if before is not None:
        old = parse(before)
        old_day = slate_date(old)
        if day < old_day:
            raise ValueError('dashboard slate_date older than previous canonical')
    return f'NHL dashboard validated: {day}, {count} cards, exact sidecar bytes'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--base', help='base commit; omitted only on initial creation')
    parser.add_argument('--candidate', default='HEAD', help='candidate commit')
    args = parser.parse_args()
    try:
        print(validate(args.repo, args.base, args.candidate))
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        print(f'BOARD_VALIDATION_REFUSED: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
