"""Request ordinary Native Wi-Fi scans before reading the Windows BSSID cache."""
import ctypes as c
import threading


GUID = c.c_ubyte * 16
DWORD = c.c_uint32
ACM = 0x00000008
SCAN_COMPLETE = 7
SCAN_FAIL = 8


class InterfaceInfo(c.Structure):
    _fields_ = [('guid', GUID), ('description', c.c_wchar * 256), ('state', DWORD)]


class InterfaceList(c.Structure):
    _fields_ = [('count', DWORD), ('index', DWORD), ('first', InterfaceInfo)]


class Notification(c.Structure):
    _fields_ = [('source', DWORD), ('code', DWORD), ('guid', GUID)]


def scan_interfaces():
    """Return the per-adapter refresh outcome. A successful WlanScan only queues work."""
    wlan = c.WinDLL('wlanapi.dll', winmode=0x800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
    handle = c.c_void_p()
    version = DWORD()
    code = wlan.WlanOpenHandle(2, None, c.byref(version), c.byref(handle))
    if code:
        raise c.WinError(code)
    listing = c.POINTER(InterfaceList)()
    outcomes = {}
    condition = threading.Condition()

    @c.WINFUNCTYPE(None, c.POINTER(Notification), c.c_void_p)
    def receive(pointer, context):
        note = pointer.contents
        if note.source != ACM or note.code not in (SCAN_COMPLETE, SCAN_FAIL):
            return
        key = bytes(note.guid)
        with condition:
            if outcomes.get(key) == 'pending':
                outcomes[key] = 'complete' if note.code == SCAN_COMPLETE else 'failed'
                condition.notify_all()

    try:
        code = wlan.WlanEnumInterfaces(handle, None, c.byref(listing))
        if code:
            raise c.WinError(code)
        count = listing.contents.count
        if count == 0:
            return []
        address = c.addressof(listing.contents) + InterfaceList.first.offset
        interfaces = (InterfaceInfo * count).from_address(address)
        code = wlan.WlanRegisterNotification(handle, ACM, False, receive, None, None, None)
        if code:
            raise c.WinError(code)
        for adapter in interfaces:
            key = bytes(adapter.guid)
            with condition:
                outcomes[key] = 'pending'
            code = wlan.WlanScan(handle, c.byref(adapter.guid), None, None, None)
            if code:
                with condition:
                    outcomes[key] = f'error {code}'
        with condition:
            condition.wait_for(lambda: 'pending' not in outcomes.values(), timeout=5)
            return [{'adapter': adapter.description,
                     'state': 'timed out' if outcomes[bytes(adapter.guid)] == 'pending'
                     else outcomes[bytes(adapter.guid)]} for adapter in interfaces]
    finally:
        if listing:
            wlan.WlanFreeMemory(listing)
        # Closing unregisters the callback and waits for in-flight callbacks.
        wlan.WlanCloseHandle(handle, None)
