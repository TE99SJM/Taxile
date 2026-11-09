#!/usr/bin/env python3
"""Recover immutable, unsent microSD outbox files into a local receiver database.
Run on a COPY of the card. Files are retained; do not modify the in-car card live.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.app import Store
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('outbox',type=Path)
p.add_argument('--db',type=Path,default=Path('data/taxile.sqlite3'))
a=p.parse_args(); store=Store(a.db)
for path in sorted(a.outbox.glob('*.ndjson')):
    body=path.read_bytes()
    if not body: continue
    try:
        first=json.loads(body.splitlines()[0])
        result=store.ingest(first['device_id'],path.name,body)
        print(path.name,'already imported' if result['duplicate'] else 'imported')
    except (ValueError,KeyError) as exc:
        print(path.name,'FAILED:',exc,file=sys.stderr)
        raise SystemExit(1)
