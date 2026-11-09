#!/usr/bin/env python3
"""Taxile receiver: authenticated, durable and idempotent NDJSON ingestion.
Python 3.11+; standard library only. Put behind HTTPS for use beyond a trusted LAN.
"""
import csv
import hashlib
import hmac
import io
import json
import math
import os
import re
import sqlite3
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo

MAX_BODY = 96000
ID = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")
BATCH = re.compile(r"^[a-zA-Z0-9_-]{1,100}\.ndjson$")
VIN = re.compile(r'^[A-HJ-NPR-Z0-9]{17}$')
TYPES = {'BOOT', 'CLOCK', 'START', 'SAMPLE', 'END'}


class Conflict(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def number(value, low, high, integer=False):
    return (type(value) in ((int,) if integer else (int, float))
            and math.isfinite(value) and low <= value <= high)


def vehicle_for(e):
    if e.get('schema') == 2:
        return e['vehicle_id'], e['vin']
    # Old history has no vehicle evidence. Never assign it to the newest VIN.
    return f"legacy-{e['device_id']}-{e['boot_id']}", ''


def validate_event(e, device):
    if not isinstance(e, dict) or e.get('schema') not in (1, 2) or e.get('device_id') != device:
        raise ValueError('invalid schema/device')
    if e['schema'] == 2:
        vin, vehicle = e.get('vin'), e.get('vehicle_id')
        if not isinstance(vin, str) or (vin and (not VIN.fullmatch(vin) or len(set(vin)) == 1)):
            raise ValueError('invalid VIN')
        if not isinstance(vehicle, str) or not ID.fullmatch(vehicle):
            raise ValueError('invalid vehicle identity')
        if vin:
            if vehicle != vin or e.get('vehicle_identification') != 'vin':
                raise ValueError('VIN identity mismatch')
        elif not vehicle.startswith('unknown-') or e.get('vehicle_identification') != 'unknown':
            raise ValueError('unidentified vehicle must remain unknown')
    for name in ('event_id', 'boot_id'):
        if not isinstance(e.get(name), str) or not ID.fullmatch(e[name]):
            raise ValueError('invalid identifier')
    if not number(e.get('seq'), 1, 2**32-1, True):
        raise ValueError('invalid sequence')
    if e['event_id'] != f"{e['boot_id']}-{e['seq']}":
        raise ValueError('event identity does not match sequence')
    trip = e.get('trip_id')
    if not isinstance(trip, str) or (trip and not ID.fullmatch(trip)):
        raise ValueError('invalid trip')
    if e.get('type') not in TYPES:
        raise ValueError('invalid event type')
    if e['type'] in {'START', 'SAMPLE', 'END'} and not trip:
        raise ValueError('trip required')
    for key, lo, hi, integer in [
        ('uptime_ms', 0, 2**53-1, True), ('interval_ms', 0, 2**32-1, True),
        ('delta_miles', 0, 1, False), ('trip_miles', 0, 1e7, False),
        ('missing_ms', 0, 2**53-1, True), ('speed_kph', -1, 255, True),
        ('rpm', -1, 20000, True), ('calibration', .5, 1.5, False),
    ]:
        if not number(e.get(key), lo, hi, integer):
            raise ValueError(f'invalid {key}')
    if e['type'] != 'SAMPLE' and e['delta_miles'] != 0:
        raise ValueError('only samples can add mileage')
    if e['delta_miles'] and (e['interval_ms'] == 0 or e['interval_ms'] > 5000):
        raise ValueError('mileage spans an invalid sampling gap')
    epoch = e.get('epoch_utc')
    if epoch is not None and not number(epoch, 1704067200, 4102444799, True):
        raise ValueError('invalid UTC time')
    if e['type'] == 'CLOCK' and epoch is None:
        raise ValueError('clock anchor has no time')


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS batches(
                    device TEXT, batch TEXT, digest TEXT NOT NULL,
                    received INTEGER NOT NULL, PRIMARY KEY(device,batch));
                CREATE TABLE IF NOT EXISTS events(
                    device TEXT, event TEXT, boot TEXT, seq INTEGER,
                    trip TEXT, uptime INTEGER, epoch INTEGER, kind TEXT,
                    payload TEXT NOT NULL, PRIMARY KEY(device,event));
                CREATE INDEX IF NOT EXISTS event_boot ON events(device,boot,seq);
                CREATE INDEX IF NOT EXISTS event_trip ON events(device,trip);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def ingest(self, device, batch, body):
        if not ID.fullmatch(device) or not BATCH.fullmatch(batch):
            raise ValueError('invalid upload identity')
        if len(body) > MAX_BODY or not body or not body.endswith(b'\n'):
            raise ValueError('empty, truncated or oversized batch')
        # Validate the complete batch before writing any part of it.
        lines = body.decode('utf-8').splitlines()
        if len(lines) > 60:
            raise ValueError('too many events')
        events = [json.loads(line) for line in lines]
        for e in events:
            validate_event(e, device)
        digest = hashlib.sha256(body).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT digest FROM batches WHERE device=? AND batch=?', (device,batch)).fetchone()
            if row:
                if row[0] != digest:
                    raise Conflict('batch identifier reused with different bytes')
                return {'ok': True, 'batch_id': batch, 'sha256': digest, 'duplicate': True}
            for e in events:
                payload = canonical(e)
                if e['trip_id'] and e['type'] in {'START','SAMPLE','END'}:
                    prior = db.execute("SELECT payload FROM events WHERE device=? AND trip=? AND kind IN ('START','SAMPLE','END') LIMIT 1",
                                       (device,e['trip_id'])).fetchone()
                    if prior and vehicle_for(json.loads(prior[0])) != vehicle_for(e):
                        raise Conflict('vehicle identity changed inside a trip')
                existing = db.execute('SELECT payload FROM events WHERE device=? AND event=?',
                                      (device,e['event_id'])).fetchone()
                if existing:
                    if existing[0] != payload:
                        raise Conflict('event identifier reused with different content')
                    continue
                db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)',
                           (device,e['event_id'],e['boot_id'],e['seq'],e['trip_id'],
                            e['uptime_ms'],e['epoch_utc'],e['type'],payload))
            db.execute('INSERT INTO batches VALUES(?,?,?,?)', (device,batch,digest,int(time.time())))
        # The SQLite transaction has committed before acknowledgment is returned.
        return {'ok': True, 'batch_id': batch, 'sha256': digest, 'duplicate': False}

    def iter_events(self):
        with self.connect() as db:
            for row in db.execute('SELECT payload FROM events ORDER BY device,boot,seq'):
                yield json.loads(row[0])

    def events(self):
        return list(self.iter_events())

    def report(self, tz_name='America/Chicago'):
        tz = ZoneInfo(tz_name)
        anchors = {}
        with self.connect() as db:
            for device, boot, at, epoch in db.execute(
                    "SELECT device,boot,uptime,epoch FROM events WHERE kind='CLOCK' AND epoch IS NOT NULL ORDER BY uptime"):
                anchors.setdefault((device,boot), []).append((at,epoch))
            # Allow import of a batch whose CLOCK file has not arrived yet.
            for device, boot, at, epoch in db.execute(
                    'SELECT device,boot,uptime,epoch FROM events WHERE epoch IS NOT NULL ORDER BY device,boot,seq'):
                if (device,boot) not in anchors:
                    anchors[device,boot] = [(at,epoch)]
        trips, daily = {}, defaultdict(float)
        unknown = 0.0
        count = 0
        vehicles = {}
        for e in self.iter_events():
            count += 1
            epoch = e['epoch_utc']
            source = 'recorded' if epoch is not None else 'unknown'
            if epoch is None and (e['device_id'],e['boot_id']) in anchors:
                at, stamp = min(anchors[e['device_id'],e['boot_id']],
                                key=lambda a: abs(a[0]-e['uptime_ms']))
                epoch = stamp+(e['uptime_ms']-at)/1000
                source = 'same_boot_anchor'
            vehicle_id, vin = vehicle_for(e)
            key = (e['device_id'],e['trip_id'])
            if not e['trip_id'] or e['type'] in {'BOOT','CLOCK'}:
                continue
            if key not in trips:
                trips[key] = dict(device_id=key[0],trip_id=key[1],vehicle_id=vehicle_id,vin=vin,
                                  vehicle_identification='vin' if vin else 'unknown',start_utc=None,end_utc=None,
                                  estimated_miles=0.0,missing_seconds=0.0,complete=False,
                                  has_start=False,time_quality='recorded')
            t = trips[key]
            if source == 'unknown' or (source == 'same_boot_anchor' and t['time_quality'] == 'recorded'):
                t['time_quality'] = source
            t['missing_seconds'] = max(t['missing_seconds'],e['missing_ms']/1000)
            if e['type'] == 'START':
                t['has_start'] = True
                t['start_utc'] = epoch
            if e['type'] == 'END':
                t['end_utc'] = epoch
                t['complete'] = True
            miles = e['delta_miles']
            if e['type'] != 'SAMPLE':
                continue
            t['estimated_miles'] += miles
            v = vehicles.setdefault(vehicle_id, dict(vehicle_id=vehicle_id,vin=vin,
                vehicle_identification='vin' if vin else 'unknown',estimated_miles=0.0,undated_miles=0.0))
            v['estimated_miles'] += miles
            if epoch is None:
                unknown += miles
                v['undated_miles'] += miles
                continue
            # Allocate a midnight-spanning interval proportionally, in the chosen
            # local timezone. Timedelta/date boundaries also handle DST days.
            start = epoch-e['interval_ms']/1000
            if start == epoch:
                day = datetime.fromtimestamp(epoch,timezone.utc).astimezone(tz).date().isoformat()
                daily[e['device_id'],vehicle_id,vin,day] += miles
            while start < epoch:
                local = datetime.fromtimestamp(start,timezone.utc).astimezone(tz)
                midnight = datetime.combine(local.date()+timedelta(days=1),datetime.min.time(),tz).timestamp()
                end = min(epoch,midnight)
                daily[e['device_id'],vehicle_id,vin,local.date().isoformat()] += miles*(end-start)/(e['interval_ms']/1000)
                start = end
        for t in trips.values():
            t['complete'] = t['complete'] and t.pop('has_start')
            for k in ('start_utc','end_utc'):
                if t[k] is not None:
                    t[k] = datetime.fromtimestamp(t[k],timezone.utc).isoformat()
        return {'timezone':tz_name,'daily':[{'device_id':d,'vehicle_id':v,'vin':vin,'date':day,'estimated_miles':m}
                 for (d,v,vin,day),m in sorted(daily.items())], 'trips':list(trips.values()),
                'vehicles':list(vehicles.values()),'undated_miles':unknown,'event_count':count}


def csv_bytes(rows, fields):
    text = io.StringIO(newline='')
    writer = csv.DictWriter(text, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode('utf-8-sig')


def handler_for(store, token, default_tz):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'Taxile/0.4'
        def setup(self):
            super().setup()
            self.connection.settimeout(15)
        def log_message(self, fmt, *args):
            # Do not print tokens, request bodies or trip history.
            pass
        def send(self, code, value, content_type='application/json'):
            body = canonical(value).encode() if content_type == 'application/json' else value
            self.send_response(code)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            self.wfile.write(body)
        def authorized(self):
            supplied = self.headers.get('Authorization','')
            if not hmac.compare_digest(supplied.encode(),('Bearer '+token).encode()):
                self.send(401,{'error':'unauthorized'})
                return False
            return True
        def send_events_csv(self, fields):
            # Raw history can grow to gigabytes. Spool to disk rather than
            # loading every event and the complete export into server RAM.
            with tempfile.TemporaryFile(mode='w+',encoding='utf-8-sig',newline='') as output:
                writer = csv.DictWriter(output,fieldnames=fields,extrasaction='ignore')
                writer.writeheader()
                writer.writerows(store.iter_events())
                output.flush()
                size = os.fstat(output.fileno()).st_size
                output.seek(0)
                self.send_response(200)
                self.send_header('Content-Type','text/csv; charset=utf-8')
                self.send_header('Content-Length',str(size))
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                while True:
                    chunk = output.buffer.read(65536)
                    if not chunk: break
                    self.wfile.write(chunk)
        def do_POST(self):
            if not self.authorized(): return
            if urlparse(self.path).path != '/v1/batches':
                self.send(404,{'error':'not found'}); return
            try:
                if self.headers.get('Transfer-Encoding'):
                    raise ValueError('Content-Length required')
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= MAX_BODY:
                    self.send(413,{'error':'invalid body size'}); return
                body = self.rfile.read(size)
                if len(body) != size: raise ValueError('incomplete upload')
                result = store.ingest(self.headers.get('X-Taxile-Device',''),
                                      self.headers.get('X-Taxile-Batch',''),body)
                self.send(200,result)
            except Conflict as exc:
                self.send(409,{'error':str(exc)})
            except (ValueError,UnicodeError,TypeError) as exc:
                self.send(400,{'error':str(exc)})
            except sqlite3.Error:
                self.send(503,{'error':'database unavailable; retry later'})
        def do_GET(self):
            path = urlparse(self.path)
            if path.path == '/health':
                self.send(200,{'ok':True}); return
            if not self.authorized(): return
            tz = parse_qs(path.query).get('tz',[default_tz])[0]
            try:
                if path.path == '/v1/events.csv':
                    fields = ['vehicle_id','vin','vehicle_identification','device_id','boot_id','event_id','seq','trip_id','type','uptime_ms',
                              'epoch_utc','interval_ms','speed_kph','rpm','delta_miles','trip_miles','missing_ms','calibration']
                    self.send_events_csv(fields); return
                r = store.report(tz)
                if path.path == '/v1/summary': self.send(200,r)
                elif path.path == '/v1/daily.csv':
                    self.send(200,csv_bytes(r['daily'],['vehicle_id','vin','device_id','date','estimated_miles']),'text/csv; charset=utf-8')
                elif path.path == '/v1/trips.csv':
                    self.send(200,csv_bytes(r['trips'],['vehicle_id','vin','vehicle_identification','device_id','trip_id','start_utc','end_utc',
                              'estimated_miles','missing_seconds','complete','time_quality']),'text/csv; charset=utf-8')
                else: self.send(404,{'error':'not found'})
            except (ValueError,KeyError): self.send(400,{'error':'invalid timezone or request'})
    return Handler


def main():
    token = os.environ.get('TAXILE_TOKEN','')
    if len(token)<32 or token.startswith('replace_') or '\n' in token or '\r' in token:
        raise SystemExit('Set TAXILE_TOKEN to a random secret of at least 32 characters')
    tz = os.environ.get('TAXILE_TZ','America/Chicago')
    ZoneInfo(tz)
    store = Store(os.environ.get('TAXILE_DB','data/taxile.sqlite3'))
    server = ThreadingHTTPServer((os.environ.get('TAXILE_BIND','0.0.0.0'),
                                 int(os.environ.get('TAXILE_PORT','8098'))),handler_for(store,token,tz))
    print(f'Taxile receiver listening on port {server.server_port}',flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
