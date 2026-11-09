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
        self.keyboard_target = None
        self.keyboard_window = None
        root.title('Taxile • ONE+ Diagnostics')
        root.geometry(f'{min(1000, root.winfo_screenwidth()-40)}x{min(850, root.winfo_screenheight()-80)}')
        root.minsize(440, 360)
        root.option_add('*Font', ('Segoe UI', 14))
        style = ttk.Style(); style.theme_use('clam')
        style.configure('TLabel', font=('Segoe UI', 14))
        style.configure('TEntry', font=('Segoe UI', 16), padding=12)
        style.configure('Touch.TButton', font=('Segoe UI', 14), padding=(14, 15))
        style.configure('Key.TButton', font=('Segoe UI', 15), padding=(3, 10))
        style.configure('Touch.TCheckbutton', font=('Segoe UI', 14), padding=12)
        style.configure('Vertical.TScrollbar', width=30, arrowsize=26)
        outer = ttk.Frame(root); outer.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(outer, highlightthickness=0, background='#f1f4f2')
        scroll = ttk.Scrollbar(outer, orient='vertical', command=self.canvas.yview)
        scroll.pack(side='right', fill='y'); self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        frame = ttk.Frame(self.canvas, padding=18)
        window = self.canvas.create_window(0, 0, window=frame, anchor='nw')
        frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        def resize(event):
            self.canvas.itemconfigure(window, width=event.width)
            for label in self.wrapped_labels:
                label.configure(wraplength=max(300, event.width-40))
        self.wrapped_labels = []
        self.canvas.bind('<Configure>', resize)
        def label(text, **kw):
            widget=ttk.Label(frame, text=text, wraplength=700, **kw)
            self.wrapped_labels.append(widget); widget.pack(anchor='w', pady=(0, 10)); return widget
        label('TAXILE  /  VEHICLE DIAGNOSTICS', font=('Segoe UI', 20, 'bold'))
        label('Ignition ON • Engine OFF • Vehicle stationary')
        label('Device address')
        self.address=ttk.Entry(frame, font=('Segoe UI', 16))
        self.address.insert(0, '192.168.4.1'); self.address.pack(fill='x', pady=(0, 14))
        label('Device admin password')
        self.password=ttk.Entry(frame, font=('Segoe UI', 16), show='•')
        self.password.pack(fill='x', pady=(0, 4))
        for entry in (self.address, self.password):
            entry.bind('<FocusIn>', lambda e: self.set_keyboard_target(e.widget))
        self.keyboard_target=self.address
        self.reveal=tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='Show password', style='Touch.TCheckbutton', variable=self.reveal,
                        command=lambda: self.password.configure(show='' if self.reveal.get() else '•')).pack(anchor='w')
        tools=ttk.Frame(frame); tools.pack(fill='x', pady=(4, 12))
        for col, (text, command) in enumerate((('Touch keyboard', self.open_keyboard), ('Full screen', self.toggle_fullscreen))):
            tools.columnconfigure(col, weight=1, uniform='tools')
            ttk.Button(tools, text=text, command=command, style='Touch.TButton').grid(row=0, column=col, sticky='ew', padx=(0, 8) if col==0 else (0, 0))
        actions=ttk.Frame(frame); actions.pack(fill='x', pady=(0, 12))
        actions.columnconfigure(0, weight=1, uniform='actions'); actions.columnconfigure(1, weight=1, uniform='actions')
        self.buttons=[]
        for i, (text, command) in enumerate((('Connect / Status', lambda: self.run('status')), ('Read codes', lambda: self.run('read')), ('Save scan', self.save), ('Clear codes…', self.confirm_clear))):
            button=ttk.Button(actions, text=text, command=command, style='Touch.TButton')
            button.grid(row=i//2, column=i%2, sticky='ew', padx=(0, 8) if i%2==0 else (0, 0), pady=5)
            self.buttons.append(button)
        self.status=tk.StringVar(value='Connect over home Wi-Fi using the device IP, or join its Taxile hotspot.')
        status=ttk.Label(frame, textvariable=self.status, wraplength=700)
        status.pack(anchor='w', pady=(0, 12)); self.wrapped_labels.append(status)
        result=ttk.Frame(frame); result.pack(fill='both', expand=True)
        self.output=tk.Text(result, wrap='word', font=('Segoe UI', 16), state='disabled', height=9,
                            padx=14, pady=14, relief='flat', background='#152d23', foreground='#f1f7f3')
        result_scroll=ttk.Scrollbar(result, orient='vertical', command=self.output.yview)
        result_scroll.pack(side='right', fill='y'); self.output.pack(side='left', fill='both', expand=True)
        self.output.configure(yscrollcommand=result_scroll.set)
        self.output.bind('<ButtonPress-1>', lambda e: setattr(self, 'drag_y', e.y))
        self.output.bind('<B1-Motion>', self.drag_results)
        navigation=ttk.Frame(frame); navigation.pack(fill='x', pady=(10, 0))
        for col,(text,direction) in enumerate((('Results ↑',-1),('Results ↓',1))):
            navigation.columnconfigure(col,weight=1,uniform='navigation')
            ttk.Button(navigation,text=text,style='Touch.TButton',command=lambda d=direction:self.output.yview_scroll(d,'pages')).grid(row=0,column=col,sticky='ew',padx=(0,8) if col==0 else (0,0))
        self.canvas.bind('<ButtonPress-1>', lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind('<B1-Motion>', lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        # Background labels can be dragged without interfering with entry editing.
        for widget in (frame, *self.wrapped_labels):
            widget.bind('<ButtonPress-1>', lambda e: self.canvas.scan_mark(0, e.y_root))
            widget.bind('<B1-Motion>', lambda e: self.canvas.scan_dragto(0, e.y_root, gain=1))
        root.bind('<F11>', lambda e:self.toggle_fullscreen())
        root.bind('<Escape>', lambda e:root.attributes('-fullscreen',False))
        self.show('Read stored generic OBD-II emissions trouble codes. ABS, airbag and body modules are not included.\n\nSave your scan before clearing. Clearing resets emissions readiness and freeze-frame data. Permanent codes may remain.\n\nTap a connection field, then Touch keyboard to type. Swipe the results or use the large scroll controls.')
        root.after(100, self.poll)
    def set_keyboard_target(self, widget):
        self.keyboard_target=widget
    def toggle_fullscreen(self):
        self.root.attributes('-fullscreen', not bool(self.root.attributes('-fullscreen')))
    def drag_results(self, event):
        delta=getattr(self,'drag_y',event.y)-event.y
        if abs(delta)>=10:
            self.output.yview_scroll(int(delta/10),'units'); self.drag_y=event.y
        return 'break'
    def open_keyboard(self):
        if self.keyboard_window is not None and self.keyboard_window.winfo_exists():
            self.keyboard_window.lift(); return
        window=tk.Toplevel(self.root); self.keyboard_window=window
        window.title('Taxile touch keyboard')
        window.geometry(f'{min(760,self.root.winfo_screenwidth()-30)}x420')
        window.transient(self.root)
        frame=ttk.Frame(window,padding=10); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Typing into the last selected connection field',wraplength=600).pack(anchor='w',pady=(0,8))
        keys=ttk.Frame(frame); keys.pack(fill='both',expand=True)
        shifted=tk.BooleanVar(value=False); symbols=tk.BooleanVar(value=False)
        def insert(value):
            target=self.keyboard_target
            if target is None: return
            if value=='BACK':
                try: target.delete('sel.first','sel.last')
                except tk.TclError:
                    at=target.index('insert')
                    if at: target.delete(at-1,at)
            else:
                try: target.delete('sel.first','sel.last')
                except tk.TclError: pass
                target.insert('insert',value)
        def draw():
            for child in keys.winfo_children(): child.destroy()
            rows=['1234567890','qwertyuiop','asdfghjkl','zxcvbnm.-_']
            if symbols.get(): rows=['!@#$%^&*()','[]{}<>/\\|=',"+;:'\"`,?~",'0123456789']
            for col in range(10): keys.columnconfigure(col,weight=1,uniform='key')
            for row,chars in enumerate(rows):
                keys.rowconfigure(row,weight=1)
                for col,char in enumerate(chars):
                    value=char.upper() if shifted.get() else char
                    ttk.Button(keys,text=value,style='Key.TButton',command=lambda v=value:insert(v)).grid(row=row,column=col,sticky='nsew',padx=2,pady=2)
        controls=ttk.Frame(frame); controls.pack(fill='x',pady=(8,0))
        def toggle(variable): variable.set(not variable.get()); draw()
        for col,(text,command) in enumerate((('Shift',lambda:toggle(shifted)),('Symbols',lambda:toggle(symbols)),('Space',lambda:insert(' ')),('⌫',lambda:insert('BACK')),('Done',window.destroy))):
            controls.columnconfigure(col,weight=1)
            ttk.Button(controls,text=text,style='Key.TButton',command=command).grid(row=0,column=col,sticky='ew',padx=2)
        draw()
    def confirm_clear(self):
        dialog=tk.Toplevel(self.root); dialog.title('Confirm code clearing')
        dialog.transient(self.root); dialog.geometry(f'{min(600,self.root.winfo_screenwidth()-30)}x{min(560,self.root.winfo_screenheight()-70)}')
        frame=ttk.Frame(dialog,padding=20); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Clear vehicle codes?',font=('Segoe UI',19,'bold')).pack(anchor='w',pady=(0,12))
        ttk.Label(frame,text='This resets emissions readiness and clears freeze-frame data. It does not repair the fault. Permanent codes may remain. Save your scan first.',wraplength=min(540,self.root.winfo_screenwidth()-80)).pack(fill='x',pady=(0,20))
        ttk.Button(frame,text='Cancel — keep codes',style='Touch.TButton',command=dialog.destroy).pack(fill='x',pady=5)
        def clear(): dialog.destroy(); self.run('clear')
        ttk.Button(frame,text='Yes, clear codes',style='Touch.TButton',command=clear).pack(fill='x',pady=5)
        dialog.bind('<Escape>',lambda e:dialog.destroy()); dialog.grab_set()
    def show(self, text):
        self.output.config(state='normal'); self.output.delete('1.0', 'end'); self.output.insert('end', text); self.output.config(state='disabled')
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
