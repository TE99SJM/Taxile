import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from http.server import ThreadingHTTPServer
from server.app import Store, Conflict, handler_for


def event(seq, kind='SAMPLE', **kw):
    e = dict(schema=1,device_id='testdevice',boot_id='boot1',seq=seq,event_id=f'boot1-{seq}',
             trip_id='boot1-t1',type=kind,uptime_ms=seq*1000,epoch_utc=None,speed_kph=80,
             rpm=1500,delta_miles=.01 if kind=='SAMPLE' else 0,trip_miles=.01,
             missing_ms=0,interval_ms=1000,calibration=1)
    e.update(kw)
    return e


def encode(*events):
    return ('\n'.join(json.dumps(e) for e in events)+'\n').encode()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/'test.db')
    def tearDown(self): self.tmp.cleanup()
    def ingest(self, body, batch='batch.ndjson'):
        return self.store.ingest('testdevice',batch,body)
    def test_retry_after_lost_ack_is_idempotent(self):
        body=encode(event(1))
        self.assertFalse(self.ingest(body)['duplicate'])
        # Close/reopen the database just like a server restart after committing.
        self.store=Store(self.store.path)
        self.assertTrue(self.ingest(body)['duplicate'])
        self.assertEqual(len(self.store.events()),1)
        self.assertEqual(self.store.report()['undated_miles'],.01)
    def test_batch_and_event_conflicts(self):
        self.ingest(encode(event(1)))
        with self.assertRaises(Conflict): self.ingest(encode(event(2)))
        with self.assertRaises(Conflict): self.ingest(encode(event(1,delta_miles=.02)), 'new.ndjson')
        self.assertEqual(len(self.store.events()),1)
    def test_duplicate_event_in_different_batch(self):
        body=encode(event(1))
        self.ingest(body); self.ingest(body,'other.ndjson')
        self.assertEqual(len(self.store.events()),1)
    def test_partial_or_invalid_batch_is_atomic(self):
        for body in [encode(event(1))[:-1], encode(event(1),event(2,delta_miles=float('nan'))),
                     encode(event(1),event(2,interval_ms=9000)),encode(event(1,device_id='other'))]:
            with self.assertRaises(ValueError): self.ingest(body)
        self.assertEqual(self.store.events(),[])
    def test_timestamp_recovery_and_incomplete_trip(self):
        self.ingest(encode(event(1,'START'),event(2),event(3,'CLOCK',epoch_utc=1794268800)))
        r=self.store.report('UTC')
        self.assertAlmostEqual(sum(d['estimated_miles'] for d in r['daily']),.01)
        self.assertEqual(r['undated_miles'],0)
        self.assertFalse(r['trips'][0]['complete'])
        self.assertEqual(r['trips'][0]['time_quality'],'same_boot_anchor')
        self.ingest(encode(event(4,'END')), 'end.ndjson')
        self.assertTrue(self.store.report()['trips'][0]['complete'])
    def test_new_boot_does_not_date_old_boot(self):
        self.ingest(encode(event(1),event(2,'CLOCK',boot_id='boot2',event_id='boot2-2',epoch_utc=1794268800)))
        self.assertEqual(self.store.report()['undated_miles'],.01)
    def test_midnight_allocation(self):
        midnight=int(datetime(2026,11,9,tzinfo=timezone.utc).timestamp())
        self.ingest(encode(event(1,epoch_utc=midnight+1,interval_ms=2000,delta_miles=.02)))
        r=self.store.report('UTC')
        self.assertEqual([x['date'] for x in r['daily']],['2026-11-08','2026-11-09'])
        self.assertEqual([x['estimated_miles'] for x in r['daily']],[.01,.01])
    def test_real_http_auth_upload_export(self):
        token='x'*40
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.store,token,'America/Chicago'))
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with self.assertRaises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(base+'/v1/summary')
            self.assertEqual(exc.exception.code,401)
            req=urllib.request.Request(base+'/v1/batches',data=encode(event(1)),headers={
                'Authorization':'Bearer '+token,'X-Taxile-Device':'testdevice','X-Taxile-Batch':'batch.ndjson'})
            with urllib.request.urlopen(req) as response:
                result=json.load(response)
            self.assertTrue(result['ok']); self.assertEqual(len(result['sha256']),64)
            req=urllib.request.Request(base+'/v1/trips.csv',headers={'Authorization':'Bearer '+token})
            with urllib.request.urlopen(req) as response:
                self.assertIn(b'estimated_miles',response.read())
            req=urllib.request.Request(base+'/v1/events.csv',headers={'Authorization':'Bearer '+token})
            with urllib.request.urlopen(req) as response:
                raw=response.read()
                self.assertEqual(len(raw),int(response.headers['Content-Length']))
                self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
                self.assertIn(b'boot1-1',raw)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__=='__main__': unittest.main()
