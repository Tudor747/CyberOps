"""BCM pin numbering. Active-low S1 is edge-triggered and requires release to re-arm."""
import threading
import os
from pathlib import Path


def pi_gpio_chip():
    configured = os.getenv('FIIRBOTS_GPIO_CHIP')
    if configured is not None:
        return int(configured)
    # Pi 5 RP1 numbering differs between kernel releases; identify by label.
    for label in Path('/sys/bus/gpio/devices').glob('gpiochip*/label'):
        if 'pinctrl-rp1' in label.read_text().strip():
            return int(label.parent.name.removeprefix('gpiochip'))
    raise RuntimeError('Pi 5 RP1 GPIO controller not found; configure FIIRBOTS_GPIO_CHIP')


class SwitchLatch:
    def __init__(self, initially_active, on_lock, on_release, on_reboot):
        self.lock = threading.Lock()
        self.armed = not initially_active
        self.fired = False
        self.on_lock, self.on_release, self.on_reboot = on_lock, on_release, on_reboot
        if initially_active:
            on_lock()
        else:
            on_release()

    def activate(self):
        with self.lock:
            self.on_lock()
            if not self.armed or self.fired:
                return
            self.armed = False
            self.fired = True
        self.on_reboot()

    def release(self):
        with self.lock:
            if self.fired:
                return  # Stay locked until the requested reboot completes.
            self.armed = True
            self.on_release()


class HardwareButtons:
    def __init__(self, controller):
        self.controller = controller
        self.buttons = []

    def start(self):
        if not self.controller.settings.gpio_enabled:
            self.controller.gpio_status = 'Disabled (development mode)'
            return
        try:
            from gpiozero import Button, Device
            from gpiozero.pins.lgpio import LGPIOFactory
            Device.pin_factory = LGPIOFactory(chip=pi_gpio_chip())
            switch = Button(21, pull_up=True, bounce_time=0.08)
            self.buttons.append(switch)
            self.latch = SwitchLatch(switch.is_pressed, self.controller.lock_operations,
                                     self.controller.unlock_operations, self.controller.request_reboot)
            switch.when_pressed = self.latch.activate
            switch.when_released = self.latch.release
            for pin, action in ((17, 'NEXT'), (27, 'PREV'), (22, 'SELECT'), (23, 'BACK'), (24, 'AI')):
                button = Button(pin, pull_up=True, bounce_time=0.08)
                button.when_pressed = lambda a=action: self.controller.button(a)
                self.buttons.append(button)
            self.controller.gpio_status = 'Connected'
        except Exception:
            self.controller.lock_operations()
            self.controller.gpio_status = 'GPIO unavailable; operations locked'
            self.close()

    def close(self):
        for button in self.buttons:
            button.close()
        self.buttons.clear()
