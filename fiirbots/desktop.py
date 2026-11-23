"""FIIRBots portrait touchscreen client for the local monitoring service."""
import json
import re
import sys
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from app.touch_evidence import hardware_lines, tool_lines, wifi_lines


BASE = 'http://127.0.0.1:8000'
BG, PANEL, TEXT, ACCENT = '#101519', '#213039', '#edf5f5', '#b8f065'
FIELDS = ('ip', 'name', 'zone', 'role', 'model', 'firmware', 'criticality')
RECEIVERS = {'Pi + ESP32': 'both', 'Pi only': 'host', 'ESP32 only': 'esp32'}
TOOL_PATHS = {
    'Hardware': 'state', 'Bluetooth LE': 'ble/defense', 'RF spectrum': 'rf/history',
    'Wi-Fi monitor': 'wireless/latest', 'GPS track': 'gps/latest',
    'Position snapshot': 'gps/wifi-snapshot/latest', 'Diagnostics': 'diagnostics/history',
    'System info': 'system',
}
DIAGNOSTICS = {'nRF24 radio 1': 'nrf1', 'nRF24 radio 2': 'nrf2', '433 MHz receiver': 'cc1101',
               'RFID reader': 'rfid', 'IR receiver': 'ir_rx', 'IR loopback': 'ir_tx',
               'Radar': 'radar', 'W5500 Ethernet': 'ethernet'}


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
        root.geometry(f'{min(480, root.winfo_screenwidth())}x{min(800, root.winfo_screenheight() - 36)}')
        root.configure(bg=BG, padx=12, pady=8)
        root.option_add('*Font', 'TkDefaultFont 14')
        ttk.Style(root).configure('TCombobox', padding=7)
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.closed = False
        self.generation = 0
        self.watching = False
        self.receiver = tk.StringVar(root, value='Pi + ESP32')
        self.passes = tk.IntVar(root, value=1)
        self.nav_buttons = {}
        self.header = tk.Label(root, bg=BG, fg=ACCENT,
                               font=('TkDefaultFont', 14, 'bold'), anchor='w')
        self.header.pack(fill='x', pady=(0, 8))
        self.nav = tk.Frame(root, bg=BG)
        self.nav.pack(fill='x')
        for name in ('Wi-Fi', 'Assets', 'Tools', 'Report'):
            button = self.button(self.nav, name, lambda view=name: self.show(view))
            button.pack(side='left', expand=True, fill='x', padx=2)
            self.nav_buttons[name] = button
        self.status = tk.Label(root, text='Connecting…', bg=BG, fg=TEXT, justify='left', anchor='w')
        self.status.pack(side='bottom', fill='x', pady=(6, 0))
        self.status.bind('<Configure>', lambda event: self.status.configure(wraplength=max(100, event.width - 12)))
        self.body = tk.Frame(root, bg=BG)
        self.body.pack(fill='both', expand=True, pady=(10, 0))
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.show('Wi-Fi')
        self.poll_buttons(None)

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

    def async_request(self, path, done, method='GET', data=None, *, on_error=None, scoped=True, quiet=False):
        if self.closed:
            return
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
                if not quiet:
                    self.status.configure(text=str(exc))
                if on_error:
                    on_error()
            else:
                done(result)

        self.root.after(80, poll)

    def poll_buttons(self, cursor):
        def received(batch):
            if cursor is not None:
                for event in batch['events']:
                    self.physical_button(event['action'])
            self.root.after(450, lambda: self.poll_buttons(batch['cursor']))

        self.async_request(f'events?after={cursor or 0}', received, scoped=False, quiet=True,
                           on_error=lambda: self.root.after(2000, lambda: self.poll_buttons(None)))

    def physical_button(self, action):
        focused = self.root.focus_get()
        modal = self.root.grab_current()
        current = focused or modal or self.root
        if action in ('NEXT', 'PREV'):
            target = current.tk_focusNext() if action == 'NEXT' else current.tk_focusPrev()
            if target and (not modal or target.winfo_toplevel() == modal):
                target.focus_set()
        elif action == 'SELECT' and isinstance(focused, tk.Button):
            focused.invoke()
        elif action == 'BACK':
            if modal:
                modal.event_generate('<<Dismiss>>')
            else:
                self.show('Tools' if self.view in TOOL_PATHS else 'Wi-Fi')

    def show(self, view):
        self.view = view
        self.generation += 1
        for child in self.body.winfo_children():
            child.destroy()
        active = 'Tools' if view in TOOL_PATHS else view
        for name, button in self.nav_buttons.items():
            button.configure(bg='#36565b' if name == active else PANEL)
        self.status.configure(text='Loading…')
        self.header.configure(text=f'FIIRBots   /   {view}')
        actions = tk.Frame(self.body, bg=BG)
        actions.pack(fill='x')
        if view == 'Wi-Fi':
            row = tk.Frame(actions, bg=BG)
            row.pack(fill='x', pady=(0, 4))
            self.button(row, self.receiver.get(), lambda: self.choose('Wi-Fi receiver',
                        {label: label for label in RECEIVERS}, self.set_receiver)).pack(side='left', expand=True, fill='x')
            self.pass_button = self.button(row, '1 pass' if self.passes.get() == 1 else '3 passes', self.toggle_passes)
            self.pass_button.pack(side='left', expand=True, fill='x', padx=(4, 0))
            self.button(actions, 'Scan nearby Wi-Fi', lambda: self.start(
                'wifi/survey', {'receiver': RECEIVERS[self.receiver.get()], 'passes': self.passes.get()}), True).pack(fill='x')
            row = tk.Frame(actions, bg=BG)
            row.pack(fill='x', pady=4)
            self.button(row, 'Latest result', self.load).pack(side='left', expand=True, fill='x')
            self.button(row, 'Stop scan', self.stop).pack(side='left', expand=True, fill='x', padx=(4, 0))
        elif view == 'Assets':
            self.button(actions, 'Scan configured LAN', lambda: self.start('scan'), True).pack(fill='x')
            row = tk.Frame(actions, bg=BG)
            row.pack(fill='x', pady=4)
            self.button(row, 'Edit selected asset', self.edit_selected).pack(side='left', fill='x', expand=True)
            self.button(row, 'Add asset', lambda: self.edit({})).pack(side='left', fill='x', expand=True, padx=(4, 0))
            row = tk.Frame(actions, bg=BG)
            row.pack(fill='x', pady=(0, 4))
            self.button(row, 'LAN settings', lambda: self.async_request(
                'network/adapters', self.lan_settings)).pack(side='left', fill='x', expand=True)
            self.button(row, 'Stop scan', self.stop).pack(side='left', fill='x', expand=True, padx=(4, 0))
        elif view == 'Tools':
            for i, name in enumerate(TOOL_PATHS):
                self.button(actions, name, lambda selected=name: self.show(selected)).grid(
                    row=i // 2, column=i % 2, padx=2, pady=2, sticky='ew')
            for col in (0, 1):
                actions.columnconfigure(col, weight=1, uniform='tools')
            self.button(actions, 'Close window', self.close).grid(row=4, column=0, columnspan=2, sticky='ew', pady=2)
            self.status.configure(text='Choose a tool')
            return
        elif view in TOOL_PATHS:
            self.tool_actions(actions, view)
        else:
            self.button(actions, 'Save report', self.save_report, True).pack(fill='x')
        area = tk.Frame(self.body, bg=PANEL)
        area.pack(fill='both', expand=True, pady=(5, 0))
        if view == 'Assets':
            self.output = tk.Listbox(area, bg=PANEL, fg=TEXT, borderwidth=0, highlightthickness=0,
                                     font=('TkDefaultFont', 16), selectbackground='#355e70')
        else:
            self.output = tk.Text(area, bg=PANEL, fg=TEXT, borderwidth=0, highlightthickness=0,
                                  padx=12, pady=10, wrap='word', spacing3=9, state='disabled')
        if view == 'RF spectrum':
            self.waterfall = tk.Canvas(area, bg=BG, height=76, highlightthickness=0)
            self.waterfall.pack(fill='x')
            self.waterfall.bind('<Configure>', lambda _: self.draw_waterfall())
        scrollbar = tk.Scrollbar(area, width=34, command=self.output.yview)
        scrollbar.pack(side='right', fill='y')
        self.output.configure(yscrollcommand=scrollbar.set)
        self.output.pack(side='left', fill='both', expand=True)
        self.assets = []
        self.result = None
        self.load()

    def set_receiver(self, value):
        self.receiver.set(value)
        self.show('Wi-Fi')

    def draw_waterfall(self):
        canvas = self.waterfall
        canvas.delete('all')
        samples = (self.result or {}).get('samples', [])
        if not samples:
            return
        palette = ('#1a2730', '#25434c', '#305d69', '#367c82', '#459c91',
                   '#70bc8f', '#afd478', '#e1e069', '#ffe86d')
        width, height = canvas.winfo_width(), canvas.winfo_height()
        for row, sample in enumerate(samples):
            for col, value in enumerate(sample['bins']):
                canvas.create_rectangle(col * width / 81, row * height / len(samples),
                                        (col + 1) * width / 81, (row + 1) * height / len(samples),
                                        fill=palette[value], outline='')

    def toggle_passes(self):
        self.passes.set(3 if self.passes.get() == 1 else 1)
        self.pass_button.configure(text=f'{self.passes.get()} passes' if self.passes.get() == 3 else '1 pass')

    def choose(self, title, choices, selected):
        if not choices:
            self.status.configure(text='No available selections.')
            return
        dialog = tk.Toplevel(self.root, bg=BG, padx=10, pady=10)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        self.label(dialog, title).pack(fill='x')
        area = tk.Frame(dialog)
        area.pack(fill='both', expand=True, pady=6)
        options = tk.Listbox(area, bg=PANEL, fg=TEXT, height=min(7, len(choices)), width=27,
                             font=('TkDefaultFont', 16), exportselection=False)
        scroll = tk.Scrollbar(area, width=32, command=options.yview)
        scroll.pack(side='right', fill='y')
        options.configure(yscrollcommand=scroll.set)
        options.pack(side='left', expand=True, fill='both')
        labels = list(choices)
        for label in labels:
            options.insert('end', label)
        options.selection_set(0)

        def apply():
            selection = options.curselection()
            if selection:
                value = choices[labels[selection[0]]]
                dialog.destroy()
                selected(value)

        self.button(dialog, 'Use selection', apply, True).pack(fill='x')
        self.button(dialog, 'Cancel', dialog.destroy).pack(fill='x', pady=(4, 0))
        dialog.bind('<<Dismiss>>', lambda _: dialog.destroy())

    def tool_actions(self, parent, view):
        controls = []
        if view == 'Bluetooth LE':
            controls = [('Scan for 10 s', lambda: self.start('ble/scan')), ('Enroll device', self.enroll_ble)]
        elif view == 'Wi-Fi monitor':
            controls = [('Listen for 10 s', lambda: self.async_request('wireless/interfaces', self.monitor_choice))]
        elif view == 'RF spectrum':
            controls = [('Save RF baseline', lambda: self.async_request('rf/baseline', lambda _: self.load(), 'PUT'))]
        elif view == 'GPS track':
            controls = [('Record for 5 s', lambda: self.start('gps/observe', {'duration_s': 5})),
                        ('Save waypoint', self.waypoint), ('Export GeoJSON', lambda: self.async_request(
                            'gps/export', lambda result: self.save_file('GPS tracks', '.geojson', json.dumps(result, indent=2))))]
        elif view == 'Position snapshot':
            controls = [('Record GPS + Wi-Fi', lambda: self.start('gps/wifi-snapshot'))]
        elif view == 'Diagnostics':
            controls = [('Choose peripheral', lambda: self.choose('Select a peripheral', DIAGNOSTICS,
                         lambda component: self.start('diagnostics', {'component': component})))]
        controls.append(('Refresh', self.load))
        if view in ('Bluetooth LE', 'Wi-Fi monitor', 'GPS track', 'Position snapshot', 'Diagnostics'):
            controls.append(('Stop', self.stop))
        for i, (label, action) in enumerate(controls):
            self.button(parent, label, action, primary=i == 0).grid(row=i // 2, column=i % 2,
                                                                   sticky='ew', padx=2, pady=2)
        for col in (0, 1):
            parent.columnconfigure(col, weight=1, uniform='actions')

    def enroll_ble(self):
        result = self.result or {}
        devices = {f"{d.get('name') or 'Unnamed'} · {d['address']}": d['address'] for d in result.get('devices', [])}
        self.choose('Enroll observed device', devices, lambda addr: self.async_request(
            'ble/baseline', lambda _: self.load(), 'PUT', {'scan_id': result['scan_id'], 'addresses': [addr]}))

    def waypoint(self):
        result = self.result or {}
        if not result.get('points'):
            self.status.configure(text='Record a GPS fix before saving a waypoint.')
            return
        self.async_request('gps/waypoint', lambda _: self.status.configure(text='Waypoint saved'),
                           'PUT', {'track_id': result['id'], 'label': 'Fix ' + result['points'][-1]['time']})

    def monitor_choice(self, result):
        radios = {r['name']: r['name'] for r in result['interfaces'] if r['mode'] == 'monitor'}
        if not radios:
            self.status.configure(text=result['message'] if result['status'] == 'UNAVAILABLE'
                                  else 'No Wi-Fi interface is in monitor mode. Use Wi-Fi for adapter scans.')
            return
        self.choose('Monitor interface', radios, lambda name: self.start('wireless/scan', {'interface': name}))

    def save_report(self):
        contents = self.output.get('1.0', 'end-1c').strip()
        if not contents:
            self.status.configure(text='Wait for the report to load.')
            return
        self.save_file('OT assessment', '.txt', 'FIIRBots OT and IIoT assessment\n\n' + contents + '\n')

    def save_file(self, name, extension, contents):
        folder = Path.home() / 'FIIRBots Reports'
        path = folder / f"{name} {datetime.now():%Y-%m-%d %H-%M-%S-%f}{extension}"
        try:
            folder.mkdir(exist_ok=True)
            path.write_text(contents, encoding='utf-8')
        except OSError as exc:
            self.status.configure(text=str(exc))
        else:
            self.status.configure(text=f'Saved in FIIRBots Reports\n{path.name}')

    def lan_settings(self, adapters):
        choices = [(item['interface'], subnet) for item in adapters
                   for subnet in item.get('available_scopes', [item['suggested_scope']])]
        if not choices:
            self.status.configure(text='No active LAN adapter with a supported subnet.')
            return
        dialog = tk.Toplevel(self.root, bg=BG, padx=12, pady=10)
        dialog.title('LAN settings')
        dialog.transient(self.root)
        dialog.grab_set()
        self.label(dialog, 'Select a connected LAN segment').pack(fill='x')
        dialog.bind('<<Dismiss>>', lambda _: dialog.destroy())
        area = tk.Frame(dialog, bg=BG)
        area.pack(fill='both', expand=True, pady=8)
        options = tk.Listbox(area, height=min(len(choices), 7), font=('TkDefaultFont', 16),
                             bg=PANEL, fg=TEXT, selectbackground='#355e70')
        scrollbar = tk.Scrollbar(area, width=34, command=options.yview)
        scrollbar.pack(side='right', fill='y')
        options.configure(yscrollcommand=scrollbar.set)
        options.pack(side='left', fill='both', expand=True)
        for interface, subnet in choices:
            options.insert('end', f'{interface}  ·  {subnet}')
        options.selection_set(0)
        error = self.label(dialog, '')
        error.configure(wraplength=390)
        error.pack(fill='x')

        def saved(_):
            dialog.destroy()
            self.load()

        def apply():
            selected = options.curselection()
            if selected:
                interface, subnet = choices[selected[0]]
                self.async_request('network/configure', saved, 'PUT', {'interface': interface, 'network': subnet},
                                   on_error=lambda: error.configure(text=self.status.cget('text')) if dialog.winfo_exists() else None)

        self.button(dialog, 'Use selected segment', apply, True).pack(fill='x')
        self.button(dialog, 'Cancel', dialog.destroy).pack(fill='x', pady=(4, 0))

    def load(self):
        if self.view == 'Tools':
            return
        path = {'Wi-Fi': 'wifi/survey/latest', 'Report': 'industrial/assessment?include_wifi=true',
                **TOOL_PATHS}.get(self.view, 'industrial/assessment')
        generation = self.generation

        def retry():
            if generation == self.generation and not self.closed:
                self.load()

        self.async_request(path, self.render, on_error=lambda: self.root.after(3000, retry))

    def render(self, result):
        self.result = result
        self.status.configure(text='Scan running…' if self.watching else 'Ready')
        if self.view == 'Wi-Fi':
            lines = wifi_lines(result)
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
        elif self.view == 'Hardware':
            lines = hardware_lines(result['hardware'])
            lines.append(f"GPIO · {result['gpio']}\nOperations · {'Locked' if result['locked'] else 'Enabled'}")
        elif self.view in TOOL_PATHS:
            lines = tool_lines(TOOL_PATHS[self.view], result)
            if self.view == 'RF spectrum':
                self.draw_waterfall()
        else:
            lines = [f"Segment · {result['network'] or 'Unconfigured'}",
                     f"LAN scan UTC · {result['scan_at'] or 'Unavailable'}"]
            for row in result['assets']:
                profile = row['profile'] or {}
                ports = ', '.join(map(str, row['open_ports'] or []))
                if not ports:
                    ports = 'Unavailable' if row['open_ports'] is None else 'None observed'
                asset = f"{profile['name']} · {row['ip']}" if profile.get('name') else row['ip']
                baseline = {'UNAUTHORIZED': 'Address absent from enrolled inventory',
                            'CONFIG_CHANGED': 'Observed settings differ from inventory',
                            'ONLINE': 'Observed settings match inventory'}.get(row.get('baseline_status'),
                                                                               'Comparison unavailable')
                lines.append(f"{asset} · {row['priority']}\nOpen TCP ports · {ports}\n{baseline}\n{row['finding']}")
            lines.extend(wifi_lines(result.get('wifi_survey', {'status': 'NOT_TESTED'})))
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
        dialog.bind('<<Dismiss>>', lambda _: dialog.destroy())
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
            pad.bind('<<Dismiss>>', lambda _: close_pad())
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

        form = tk.Frame(dialog, bg=BG)
        form.pack(fill='both', expand=True)
        columns = 2 if self.root.winfo_screenwidth() > self.root.winfo_screenheight() else 1
        for col in range(columns):
            form.columnconfigure(col, weight=1, uniform='fields')
        for index, field in enumerate(FIELDS):
            row, col = divmod(index, columns)
            group = tk.Frame(form, bg=BG)
            group.grid(row=row, column=col, sticky='ew', padx=3)
            caption = {'ip': 'IPv4 address', 'model': 'Manufacturer / model'}.get(field, field.title())
            self.label(group, caption).pack(fill='x')
            variable = tk.StringVar(value=profile.get(field, 'Unknown' if field == 'criticality' else ''))
            if field == 'criticality':
                widget = ttk.Combobox(group, textvariable=variable, state='readonly',
                                      values=('Unknown', 'Low', 'Medium', 'High'))
            else:
                widget = ttk.Entry(group, textvariable=variable)
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
    if '--fullscreen' in sys.argv:
        window.attributes('-fullscreen', True)
    window.mainloop()
