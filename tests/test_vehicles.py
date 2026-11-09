import csv
import io
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from server.app import Store, Conflict, handler_for
from test_server import event, encode
A='1M8GDM9AXKP042788'
B='1HGCM82633A004352'
def sample(seq,vin,trip=None,**kw):
 return event(seq,schema=2,vin=vin,vehicle_id=vin if vin else 'unknown-boot1-t3',
              vehicle_identification='vin' if vin else 'unknown',trip_id=trip or f'boot1-t{seq}',
              epoch_utc=1794268800,**kw)
class VehicleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'db')
 def tearDown(self): self.tmp.cleanup()
 def test_same_dongle_two_vehicles_and_unknown_stay_separate(self):
  self.store.ingest('testdevice','swap.ndjson',encode(sample(1,A),sample(2,B),sample(3,'')))
  r=self.store.report('UTC')
  self.assertEqual(len(r['daily']),3)
  self.assertEqual({v['vin'] for v in r['vehicles']},{A,B,''})
  self.assertAlmostEqual(sum(v['estimated_miles'] for v in r['vehicles']),.03)
  self.assertEqual({t['vin'] for t in r['trips']},{A,B,''})
 def test_same_vehicle_across_boots_aggregates(self):
  self.store.ingest('testdevice','a.ndjson',encode(sample(1,A)))
  self.store.ingest('testdevice','b.ndjson',encode(sample(2,A,boot_id='boot2',event_id='boot2-2',trip='boot2-t1')))
  self.assertEqual(len(self.store.report()['vehicles']),1)
  self.assertAlmostEqual(self.store.report()['vehicles'][0]['estimated_miles'],.02)
 def test_old_records_not_assigned_to_current_vehicle(self):
  self.store.ingest('testdevice','old.ndjson',encode(event(1)))
  self.store.ingest('testdevice','new.ndjson',encode(sample(2,B)))
  r=self.store.report();self.assertEqual(len(r['vehicles']),2)
  self.assertTrue(any(v['vehicle_id'].startswith('legacy-') and not v['vin'] for v in r['vehicles']))
 def test_mid_trip_vehicle_change_is_rejected_atomically(self):
  self.store.ingest('testdevice','a.ndjson',encode(sample(1,A,trip='boot1-t1')))
  with self.assertRaises(Conflict):
   self.store.ingest('testdevice','b.ndjson',encode(sample(2,A,trip='boot1-t2'),sample(3,B,trip='boot1-t1')))
  self.assertEqual(len(self.store.events()),1)
 def test_bad_vin_or_mismatched_identity_rejected(self):
  for changes in ({'vin':'INVALID'},{'vehicle_id':B},{'vin':'I'*17},{'vin':'0'*17}):
   e=sample(1,A);e.update(changes)
   with self.assertRaises(ValueError): self.store.ingest('testdevice','bad.ndjson',encode(e))
 def test_csv_exports_include_vehicle(self):
  self.store.ingest('testdevice','test.ndjson',encode(sample(1,A),sample(2,B)))
  server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.store,'x'*40,'UTC'))
  t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
  try:
   for kind in ('daily','trips','events'):
    req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/v1/{kind}.csv',headers={'Authorization':'Bearer '+'x'*40})
    with urllib.request.urlopen(req) as response: rows=list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
    self.assertEqual({r['vin'] for r in rows},{A,B})
  finally: server.shutdown();server.server_close();t.join()
if __name__=='__main__': unittest.main()
