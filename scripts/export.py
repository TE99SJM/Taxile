#!/usr/bin/env python3
"""Download Excel-compatible mileage CSVs without putting secrets in a URL."""
import argparse
import os
import urllib.request
from pathlib import Path
from urllib.parse import quote

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('server',help='Receiver origin, e.g. http://192.168.50.199:8098')
p.add_argument('--out',type=Path,default=Path('exports'))
p.add_argument('--tz',default='America/Chicago')
a=p.parse_args()
token=os.environ.get('TAXILE_TOKEN','')
if not token: p.error('Set TAXILE_TOKEN in the environment')
a.out.mkdir(parents=True,exist_ok=True)
for kind in ('daily','trips','events'):
    request=urllib.request.Request(a.server.rstrip('/')+'/v1/'+kind+'.csv?tz='+quote(a.tz),
                                   headers={'Authorization':'Bearer '+token})
    with urllib.request.urlopen(request,timeout=30) as response:
        data=response.read()
    path=a.out/(kind+'.csv')
    path.write_bytes(data)
    print(path)
