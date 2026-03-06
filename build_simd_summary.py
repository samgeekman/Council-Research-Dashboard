#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

SIMD_CSV = Path('simd2020v2_22062020.csv')
BOUNDARY_INDEX = Path('boundaries/index.json')
DB_JSON = Path('council_research_database.json')
DB_JS = Path('council_research_database.js')
OUT_JSON = Path('simd_summary_by_authority.json')

NAME_ALIASES = {
    'Na h-Eileanan Siar': 'Na h-Eileanan Siar (Western Isles)',
}


def pct(n: int, d: int) -> float:
    return round((n / d) * 100.0, 1) if d else 0.0


def median(values: list[int]) -> int | None:
    if not values:
        return None
    s = sorted(values)
    m = len(s) // 2
    if len(s) % 2 == 1:
        return s[m]
    return round((s[m - 1] + s[m]) / 2)


def load_code_to_name() -> dict[str, str]:
    idx = json.loads(BOUNDARY_INDEX.read_text())
    return {item['code']: item['name'] for item in idx['items']}


def build_summary() -> tuple[dict[str, dict], dict[str, dict]]:
    code_to_name = load_code_to_name()

    agg = defaultdict(lambda: {
        'count': 0,
        'ranks': [],
        'quintile_counts': defaultdict(int),
        'decile_counts': defaultdict(int),
        'most15': 0,
        'least15': 0,
    })

    with SIMD_CSV.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get('CA', '').strip()
            if not code:
                continue
            bucket = agg[code]
            bucket['count'] += 1

            try:
                bucket['ranks'].append(int(row.get('SIMD2020V2Rank', '')))
            except ValueError:
                pass

            q = row.get('SIMD2020V2CountryQuintile', '').strip()
            d = row.get('SIMD2020V2CountryDecile', '').strip()
            if q.isdigit():
                bucket['quintile_counts'][int(q)] += 1
            if d.isdigit():
                bucket['decile_counts'][int(d)] += 1

            if row.get('SIMD2020V2Most15pc', '').strip() == '1':
                bucket['most15'] += 1
            if row.get('SIMD2020V2Least15pc', '').strip() == '1':
                bucket['least15'] += 1

    by_code = {}
    by_name = {}
    for code, b in agg.items():
        total = b['count']
        name = code_to_name.get(code, code)
        summary = {
            'council_code': code,
            'datazone_count': total,
            'mean_simd_rank': round(sum(b['ranks']) / len(b['ranks']), 1) if b['ranks'] else None,
            'median_simd_rank': median(b['ranks']),
            'percent_most_deprived_15pc': pct(b['most15'], total),
            'percent_least_deprived_15pc': pct(b['least15'], total),
            'percent_in_most_deprived_20pc': pct(b['quintile_counts'].get(1, 0), total),
            'percent_in_least_deprived_20pc': pct(b['quintile_counts'].get(5, 0), total),
            'country_quintile_distribution_percent': {
                str(i): pct(b['quintile_counts'].get(i, 0), total) for i in range(1, 6)
            },
            'country_decile_distribution_percent': {
                str(i): pct(b['decile_counts'].get(i, 0), total) for i in range(1, 11)
            },
            'source': {
                'dataset': 'NHS Scotland Open Data - SIMD2020v2',
                'file': SIMD_CSV.name,
            },
        }
        by_code[code] = summary
        mapped_name = NAME_ALIASES.get(name, name)
        by_name[mapped_name] = summary

    # Add rankings across all local authorities (n=32).
    # 1) Mean SIMD rank: higher mean rank indicates less deprivation (better).
    ordered_mean = sorted(by_code.values(), key=lambda x: (x['mean_simd_rank'] is None, -(x['mean_simd_rank'] or -1)))
    for i, s in enumerate(ordered_mean, start=1):
        s['la_rank_mean_simd_rank'] = i

    # 2) % in most deprived 20%: lower is better.
    ordered_most20 = sorted(by_code.values(), key=lambda x: x['percent_in_most_deprived_20pc'])
    for i, s in enumerate(ordered_most20, start=1):
        s['la_rank_most_deprived_20pc'] = i

    # 3) % in least deprived 20%: higher is better.
    ordered_least20 = sorted(by_code.values(), key=lambda x: -x['percent_in_least_deprived_20pc'])
    for i, s in enumerate(ordered_least20, start=1):
        s['la_rank_least_deprived_20pc'] = i

    return by_code, by_name


def inject_into_council_db(by_name: dict[str, dict]) -> None:
    db = json.loads(DB_JSON.read_text())
    missing = []
    for authority in db.get('authorities', []):
        name = authority.get('local_authority')
        simd = by_name.get(name)
        if simd:
            authority['simd_summary'] = simd
        else:
            authority['simd_summary'] = None
            missing.append(name)

    db.setdefault('sources', {})
    db['sources']['simd'] = {
        'dataset': 'NHS Scotland Open Data - SIMD2020v2',
        'csv': SIMD_CSV.name,
        'download_date': '2026-03-06',
    }

    DB_JSON.write_text(json.dumps(db, indent=2, ensure_ascii=False))
    DB_JS.write_text('window.COUNCIL_DB = ' + json.dumps(db, ensure_ascii=False) + ';\n')

    if missing:
        print('Missing SIMD match for:', ', '.join(missing))


def main() -> None:
    by_code, by_name = build_summary()

    payload = {
        'authority_count': len(by_code),
        'by_council_code': by_code,
        'by_authority_name': by_name,
        'source': {
            'dataset': 'NHS Scotland Open Data - SIMD2020v2',
            'csv': SIMD_CSV.name,
            'download_date': '2026-03-06',
        },
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    inject_into_council_db(by_name)

    print(f'Wrote {OUT_JSON}')
    print(f'Updated {DB_JSON}')
    print(f'Updated {DB_JS}')
    print('SIMD summaries:', len(by_name))


if __name__ == '__main__':
    main()
