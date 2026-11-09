"""Taxile PC diagnostics — local Windows/Linux/macOS Tk desktop client."""
import json
from datetime import datetime, timezone
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from urllib.parse import urlparse
import requests
from requests.auth import HTTPDigestAuth

class Client:
    def __init__(self, address, password):
        address = address.strip().rstrip('/')
        if '://' not in address:
            address = 'http://' + address
        parsed = urlparse(address)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('Enter only the Taxile IP address or hostname.')
        self.address, self.password = address, password
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.auth = HTTPDigestAuth('admin', password)
    def status(self):
        r = self.session.get(self.address + '/api/status', timeout=(5, 20), allow_redirects=False)
        r.raise_for_status()
        d = r.json()
        if d.get('version') != '0.4.0':
            raise ValueError('This app requires the matching Taxile 0.4.0 firmware.')
        return d
    def diagnostic(self, clear=False):
        status = self.status()
        r = self.session.post(self.address + '/api/diagnostics/' + ('clear' if clear else 'read'),
            headers={'X-Taxile-CSRF': status['csrf'], 'Content-Type': 'text/plain'},
            data='CLEAR' if clear else '', timeout=(5, 90), allow_redirects=False)
        if r.status_code != 200:
            raise ValueError(r.text[:1000])
        result = r.json()
        if not result.get('ok'):
            raise ValueError(result.get('error', 'ECU result unknown'))
        return result

class App:
    def __init__(self, root):
        self.root, self.events, self.report = root, queue.Queue(), None
        root.title('Taxile • ONE+ Diagnostics')
        root.geometry('790x570')
        root.minsize(650, 480)
        style = ttk.Style(); style.theme_use('clam')
        style.configure('TButton', padding=9)
        frame = ttk.Frame(root, padding=22); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='TAXILE  /  VEHICLE DIAGNOSTICS', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Ignition ON • Engine OFF • Vehicle stationary', padding=(0, 8)).pack(anchor='w')
        row = ttk.Frame(frame); row.pack(fill='x', pady=8)
        ttk.Label(row, text='Device address').grid(row=0, column=0, sticky='w')
        ttk.Label(row, text='Device admin password').grid(row=0, column=1, sticky='w')
        self.address = ttk.Entry(row, width=32); self.address.insert(0, '192.168.4.1'); self.address.grid(row=1, column=0, padx=(0, 12))
        self.password = ttk.Entry(row, width=32, show='•'); self.password.grid(row=1, column=1)
        actions = ttk.Frame(frame); actions.pack(fill='x', pady=10)
        self.buttons = []
        for label, cmd in [('Connect / Status', lambda: self.run('status')), ('Read codes', lambda: self.run('read')), ('Clear codes…', self.confirm_clear), ('Save scan', self.save)]:
            b=ttk.Button(actions, text=label, command=cmd); b.pack(side='left', padx=(0, 8)); self.buttons.append(b)
        self.status = tk.StringVar(value='Connect over home Wi-Fi using the device IP, or join its Taxile hotspot.')
        ttk.Label(frame, textvariable=self.status, wraplength=720).pack(anchor='w', pady=5)
        self.output = tk.Text(frame, wrap='word', font=('Consolas', 11), state='disabled', height=15)
        self.output.pack(fill='both', expand=True)
        self.show('Read: stored generic OBD-II emissions trouble codes.\nABS, airbags and manufacturer module scans are not included.\n\nClearing codes also clears freeze-frame data and resets emissions readiness.\nPermanent codes cannot be erased this way. Save a report before clearing.\n\nThe password is printed by Taxile on USB serial at 115200 baud.\nPasswords are kept in memory only.')
        root.after(100, self.poll)
    def show(self, text):
        self.output.config(state='normal'); self.output.delete('1.0', 'end'); self.output.insert('end', text); self.output.config(state='disabled')
    def confirm_clear(self):
        if messagebox.askyesno('Clear vehicle codes?', 'This clears generic emissions trouble codes and freeze-frame data, and resets emissions readiness monitors. It does not repair the fault. Permanent codes may remain.\n\nSave your report first. Continue?'):
            self.run('clear')
    def run(self, operation):
        try: client=Client(self.address.get(), self.password.get())
        except Exception as exc: messagebox.showerror('Connection', str(exc)); return
        for b in self.buttons: b.config(state='disabled')
        self.status.set('Working… keep ignition ON and engine OFF.')
        def worker():
            try:
                result=client.status() if operation=='status' else client.diagnostic(operation=='clear')
                self.events.put((operation, result, None))
            except Exception as exc: self.events.put((operation, None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()
    def poll(self):
        try:
            op, result, error=self.events.get_nowait()
            for b in self.buttons: b.config(state='normal')
            if error:
                self.status.set('Operation failed; no success assumed.'); self.show(error)
            elif op=='status':
                self.status.set('Connected to Taxile ' + result['version'])
                self.show('\n'.join(f'{key}: {result.get(key)}' for key in ('device','vin','vehicle_identification','trip_vin','obd','parked','rpm','speed_kph','volts','trip_miles','sync','storage')))
            else:
                if op=='read':
                    result['scanned_at_utc']=datetime.now(timezone.utc).isoformat()
                    self.report=result
                    codes=result.get('codes', [])
                    self.status.set(f'Scan complete: {len(codes)} stored generic emissions code(s).')
                    self.show(('Stored trouble codes\n\n' + '\n'.join(codes) if codes else 'No stored generic emissions codes reported.') + '\n\n' + result.get('scope', '') + '\n\nSave this scan before clearing codes.')
                else:
                    self.status.set('Clear acknowledged — read codes again to verify.')
                    self.show(result.get('message', 'ECU acknowledged clear.') + '\n\nEmissions readiness has been reset.\nYour last scan is still available with Save scan.')
        except queue.Empty: pass
        self.root.after(100, self.poll)
    def save(self):
        if self.report is None: messagebox.showinfo('Report', 'Read codes first.'); return
        path=filedialog.asksaveasfilename(defaultextension='.json', initialfile='Taxile-diagnostic-report.json')
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f: json.dump(self.report, f, indent=2)
            except OSError as exc: messagebox.showerror('Save report', str(exc))

if __name__ == '__main__':
    root=tk.Tk(); App(root); root.mainloop()
