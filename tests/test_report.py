import csv
import tempfile
import unittest
from pathlib import Path
from tools.report import summarize


class ReportTests(unittest.TestCase):
    def test_deduplication_and_missing_clock(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "log.csv"
            with path.open("w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["event", "boot_id", "trip_id", "epoch_utc",
                                 "time_valid", "uptime_ms", "rpm", "speed_kph",
                                 "delta_miles", "trip_miles"])
                writer.writerow(["SAMPLE", 1, 1, 1762128000, 1, 1000, 1000, 40, .5, .5])
                writer.writerow(["SAMPLE", 1, 1, 1762128000, 1, 1000, 1000, 40, .5, .5])
                writer.writerow(["SAMPLE", 1, 1, 0, 0, 2000, 1000, 50, .25, .75])
            daily, trips, unknown, count, dupes = summarize([path], "UTC")
            self.assertEqual(count, 2)
            self.assertEqual(dupes, 1)
            self.assertAlmostEqual(sum(daily.values()), .5)
            self.assertAlmostEqual(unknown, .25)
            self.assertAlmostEqual(sum(trips.values()), .75)


if __name__ == "__main__":
    unittest.main()

class VehicleCSVTests(unittest.TestCase):
    def test_current_receiver_csv_stays_separate_by_vehicle(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'events.csv'
            with path.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['type','device_id','event_id','boot_id','trip_id','uptime_ms','epoch_utc','delta_miles','vehicle_id','vin'])
                w.writeheader()
                for n,vin in enumerate(['1M8GDM9AXKP042788','1HGCM82633A004352'],1):
                    w.writerow(dict(type='SAMPLE',device_id='one',event_id=f'boot-{n}',boot_id='boot',trip_id=f't{n}',uptime_ms=n*1000,epoch_utc=1794268800,delta_miles=.1,vehicle_id=vin,vin=vin))
            daily,trips,*_=summarize([path],'UTC')
            self.assertEqual(len(daily),2)
            self.assertEqual({v for v,day in daily},{'1M8GDM9AXKP042788','1HGCM82633A004352'})
