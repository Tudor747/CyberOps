"""FIIRBots portrait touchscreen client for the local monitoring service."""
import json
import re
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import webbrowser


BASE = 'http://127.0.0.1:8000'
BG, PANEL, TEXT, ACCENT = '#101519', '#213039', '#edf5f5', '#b8f065'
FIELDS = ('ip', 'name', 'zone', 'role', 'model', 'firmware', 'criticality')


def request(path, method='GET', data=None):
    headers = {}
    if method != 'GET':
        with urlopen(BASE, timeout=5) as page:
            token = re.search(r'name="action-token" content="([a-f0-9]+)"', page.read().decode())
        if not token:
            raise ValueError('Action token missing. Check the FIIRBots service.')
        headers = {'X-FIIRBots-Token': token[1], 'Content-Type': 'application/json'}
    body = json.dumps(data).encode() if data is not None else None
    try:
        with urlopen(Request(BASE + '/api/' + path, body, headers, method=method), timeout=8) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = json.load(exc).get('detail', exc.reason)
        if isinstance(detail, list):
            detail = '\n'.join(f"{item['loc'][-1]} · {item['msg']}" for item in detail)
        raise ValueError(detail) from exc


class Desktop:
    def __init__(self, root):
        self.root = root
        root.title('FIIRBots | OT / IIoT')
        root.geometry('480x800')
        root.configure(bg=BG, padx=12, pady=8)
        root.option_add('*Font', 'TkDefaultFont 14')
        ttk.Style(root).configure('TCombobox', padding=7)
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.closed = False
        self.view = ''
        self.generation = 0
        self.watching = False
        self.header = tk.Label(root, text='FIIRBots   /   OT FIELD ASSESSMENT', bg=BG, fg=ACCENT,
                               font=('TkDefaultFont', 14, 'bold'), anchor='w')
        self.header.pack(fill='x', pady=(0, 8))
        self.nav = tk.Frame(root, bg=BG)
        self.nav.pack(fill='x')
        for name in ('Wi-Fi', 'Assets', 'Report'):
            self.button(self.nav, name, lambda view=name: self.show(view)).pack(side='left', expand=True, fill='x', padx=2)
        self.status = tk.Label(root, text='Connecting…', bg=BG, fg=TEXT, justify='left', anchor='w')
        self.status.pack(side='bottom', fill='x', pady=(6, 0))
        self.status.bind('<Configure>', lambda event: self.status.configure(wraplength=max(100, event.width - 12)))
        self.body = tk.Frame(root, bg=BG)
        self.body.pack(fill='both', expand=True, pady=(10, 0))
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.show('Wi-Fi')

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def button(self, parent, label, action, primary=False):
        return tk.Button(parent, text=label, command=action, borderwidth=0, pady=13, padx=4,
                         bg=ACCENT if primary else PANEL, fg=BG if primary else TEXT,
                         activebackground='#cde892', activeforeground=BG)

    def label(self, parent, text):
        return tk.Label(parent, text=text, bg=BG, fg=TEXT, anchor='w', justify='left')

    def async_request(self, path, done, method='GET', data=None, *, on_error=None, scoped=True):
        generation = self.generation
        future = self.pool.submit(request, path, method, data)

        def poll():
            if self.closed:
                return
            if not future.done():
                self.root.after(80, poll)
                return
            if scoped and generation != self.generation:
                return
            try:
                result = future.result()
            except Exception as exc:
                self.status.configure(text=str(exc))
                if on_error:
                    on_error()
            else:
                done(result)

        self.root.after(80, poll)

    def show(self, view):
        self.view = view
        self.generation += 1
        for child in self.body.winfo_children():
            child.destroy()
        self.status.configure(text='Loading…')
        actions = tk.Frame(self.body, bg=BG)
        actions.pack(fill='x')
        if view == 'Wi-Fi':
            self.button(actions, 'Scan nearby Wi-Fi', lambda: self.start(
                'wifi/survey', {'receiver': 'host', 'passes': 1}), True).pack(fill='x')
            self.button(actions, 'Stop scan', self.stop).pack(fill='x', pady=4)
        elif view == 'Assets':
            self.button(actions, 'Scan configured LAN', lambda: self.start('scan'), True).pack(fill='x')
            row = tk.Frame(actions, bg=BG)
            row.pack(fill='x', pady=4)
            self.button(row, 'Edit selected asset', self.edit_selected).pack(side='left', fill='x', expand=True)
            self.button(row, 'Add asset', lambda: self.edit({})).pack(side='left', fill='x', expand=True, padx=(4, 0))
            row = tk.Frame(actions, bg=BG)
            row.pack(fill='x', pady=(0, 4))
            self.button(row, 'LAN settings', lambda: self.open_page('/#network')).pack(side='left', fill='x', expand=True)
            self.button(row, 'Stop scan', self.stop).pack(side='left', fill='x', expand=True, padx=(4, 0))
        else:
            self.button(actions, 'Open printable report', lambda: self.open_page('/api/industrial/report'), True).pack(fill='x')
        area = tk.Frame(self.body, bg=PANEL)
        area.pack(fill='both', expand=True, pady=(5, 0))
        if view == 'Assets':
            self.output = tk.Listbox(area, bg=PANEL, fg=TEXT, borderwidth=0, highlightthickness=0,
                                     font=('TkDefaultFont', 16), selectbackground='#355e70')
        else:
            self.output = tk.Text(area, bg=PANEL, fg=TEXT, borderwidth=0, highlightthickness=0,
                                  padx=12, pady=10, wrap='word', spacing3=9, state='disabled')
        scrollbar = tk.Scrollbar(area, width=34, command=self.output.yview)
        scrollbar.pack(side='right', fill='y')
        self.output.configure(yscrollcommand=scrollbar.set)
        self.output.pack(side='left', fill='both', expand=True)
        self.assets = []
        self.load()

    def open_page(self, path):
        webbrowser.open(BASE + path)

    def load(self):
        path = 'wifi/survey/latest' if self.view == 'Wi-Fi' else 'industrial/assessment'
        self.async_request(path, self.render)

    def render(self, result):
        self.status.configure(text='Scan running…' if self.watching else 'Ready')
        if self.view == 'Wi-Fi':
            points = result.get('access_points', [])
            lines = [f"{len(points)} access points   ·   {result['status']}"]
            for point in points:
                title = ' / '.join(point['ssids']) or 'Hidden or unknown name'
                sample = next((row for row in reversed(point['samples']) if not row.get('from_cache')),
                              point['samples'][-1])
                frequency = sample.get('frequency_mhz')
                signal = f"{sample['rssi_dbm']} dBm" if sample.get('rssi_dbm') is not None else (
                    f"{sample['signal_percent']}%" if sample.get('signal_percent') is not None else 'Unknown signal')
                cache = ' · cached' if sample.get('from_cache') else ''
                lines.append(f"{title}\n{point['bssid']} · {sample.get('security') or 'Unknown security'}"
                             f"\nChannel {sample.get('channel') or '?'} · {frequency or '?'} MHz · {signal}{cache}")
            lines.extend(f"{source['receiver']} · {source['message']}" for source in result.get('sources', []))
        elif self.view == 'Assets':
            self.assets = result['assets']
            self.output.delete(0, 'end')
            for row in self.assets:
                profile = row['profile'] or {}
                ports = row['open_ports']
                evidence = f'{len(ports)} open TCP' if ports is not None else 'No scan evidence'
                self.output.insert('end', f"{profile.get('name') or row['ip']}   ·   {profile.get('zone') or 'Unassigned'}   ·   {evidence}")
            self.status.configure(text=f"{result['network'] or 'Configure LAN settings'} · {len(self.assets)} assets")
            return
        else:
            lines = [f"Segment · {result['network'] or 'Unconfigured'}",
                     f"LAN scan UTC · {result['scan_at'] or 'Unavailable'}"]
            for row in result['assets']:
                profile = row['profile'] or {}
                ports = ', '.join(map(str, row['open_ports'] or []))
                if not ports:
                    ports = 'Unavailable' if row['open_ports'] is None else 'None observed'
                lines.append(f"{profile.get('name') or row['ip']} · {row['priority']}"
                             f"\nOpen TCP ports · {ports}\n{row['finding']}")
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.insert('1.0', '\n\n'.join(lines))
        self.output.configure(state='disabled')

    def start(self, path, data=None):
        if self.watching:
            return
        self.watching = True
        self.status.configure(text='Starting scan…')
        self.async_request(path, lambda _: self.watch(), 'POST', data, on_error=self.stop_watching, scoped=False)

    def stop(self):
        self.async_request('stop', lambda _: self.status.configure(text='Stop requested'), 'POST')

    def stop_watching(self):
        self.watching = False

    def watch(self):
        def update(state):
            job = state['job']
            self.status.configure(text=job['message'])
            if job['status'] == 'RUNNING':
                self.root.after(1000, self.watch)
            else:
                self.stop_watching()
                if job['status'] == 'COMPLETE':
                    self.load()
        self.async_request('state', update, on_error=self.stop_watching, scoped=False)

    def edit_selected(self):
        selected = self.output.curselection()
        if not selected:
            self.status.configure(text='Touch an asset in the list first.')
            return
        row = self.assets[selected[0]]
        self.edit(row['profile'] or {'ip': row['ip']})

    def edit(self, profile):
        dialog = tk.Toplevel(self.root, bg=BG, padx=12, pady=8)
        dialog.title('Industrial asset')
        dialog.transient(self.root)
        dialog.grab_set()
        inputs = {}
        target = None

        def select_entry(event):
            nonlocal target
            target = event.widget

        def keyboard():
            if target is None:
                error.configure(text='Touch a text field first.')
                return
            pad = tk.Toplevel(dialog, bg=BG)
            pad.title('Touch keyboard')
            pad.transient(dialog)
            pad.grab_set()
            letters = []

            def close_pad():
                pad.destroy()
                dialog.grab_set()
                target.focus_set()

            def insert(button):
                target.insert('insert', button.cget('text'))

            def backspace():
                position = target.index('insert')
                if position:
                    target.delete(position - 1)

            pad.protocol('WM_DELETE_WINDOW', close_pad)
            for characters in ('1234567890', 'qwertyuiop', 'asdfghjkl', 'zxcvbnm.-/'):
                row = tk.Frame(pad, bg=BG)
                row.pack(fill='x')
                for char in characters:
                    key = self.button(row, char, None)
                    key.configure(command=lambda key=key: insert(key), width=2)
                    key.pack(side='left', expand=True, fill='x', padx=1, pady=1)
                    if char.isalpha():
                        letters.append(key)
            keys = tk.Frame(pad, bg=BG)
            keys.pack(fill='x')
            for caption, action in (
                ('Shift', lambda: [key.configure(text=key.cget('text').swapcase()) for key in letters]),
                ('Space', lambda: target.insert('insert', ' ')),
                ('Delete', backspace), ('Done', close_pad),
            ):
                self.button(keys, caption, action).pack(side='left', expand=True, fill='x', padx=1)

        for field in FIELDS:
            caption = {'ip': 'IPv4 address', 'model': 'Manufacturer / model'}.get(field, field.title())
            self.label(dialog, caption).pack(fill='x')
            variable = tk.StringVar(value=profile.get(field, 'Unknown' if field == 'criticality' else ''))
            if field == 'criticality':
                widget = ttk.Combobox(dialog, textvariable=variable, state='readonly',
                                      values=('Unknown', 'Low', 'Medium', 'High'))
            else:
                widget = ttk.Entry(dialog, textvariable=variable)
                widget.bind('<FocusIn>', select_entry)
            widget.pack(fill='x', ipady=7, pady=(0, 4))
            inputs[field] = variable

        def saved(_):
            if dialog.winfo_exists():
                dialog.destroy()
            self.load()

        def save():
            self.async_request('industrial/assets', saved, 'PUT',
                               {field: variable.get().strip() for field, variable in inputs.items()},
                               on_error=lambda: error.configure(text=self.status.cget('text')) if dialog.winfo_exists() else None)

        error = self.label(dialog, '')
        error.configure(wraplength=420)
        error.pack(fill='x')
        actions = tk.Frame(dialog, bg=BG)
        actions.pack(fill='x')
        self.button(actions, 'Keyboard', keyboard).pack(side='left', fill='x', expand=True, padx=(0, 4))
        self.button(actions, 'Save asset', save, True).pack(side='left', fill='x', expand=True)
        self.button(actions, 'Cancel', dialog.destroy).pack(side='left', fill='x', expand=True, padx=(4, 0))


if __name__ == '__main__':
    window = tk.Tk()
    Desktop(window)
    window.mainloop()
