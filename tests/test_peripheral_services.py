import json
import subprocess
import unittest

from PySide6.QtWidgets import QApplication

from peripheral_control.classification import deduplicate_devices, device_from_mapping
from peripheral_control.discovery import PeripheralDiscovery
from peripheral_control.models import DeviceCategory
from peripheral_control.ui import PeripheralPanel


def device(**values):
    return device_from_mapping(values)


class PeripheralServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_classifies_real_input_output_types_without_usb_shortcut(self):
        touchscreen = device(
            InstanceId="HID\\TOUCH",
            FriendlyName="USB Touchscreen",
            Class="HIDClass",
        )
        storage = device(
            InstanceId="USB\\DISK",
            FriendlyName="USB Mass Storage Device",
            Class="USB",
        )
        unknown_usb = device(InstanceId="USB\\OTHER", FriendlyName="USB Adapter", Class="USB")

        self.assertIn(DeviceCategory.INPUT_OUTPUT, touchscreen.categories)
        self.assertIn(DeviceCategory.STORAGE, storage.categories)
        self.assertEqual(unknown_usb.categories, ())

    def test_keeps_input_and_output_categories(self):
        audio = device(
            InstanceId="HDAUDIO\\1",
            FriendlyName="Microphone and Headphones",
            Class="Sound",
        )
        self.assertIn(DeviceCategory.INPUT, audio.categories)
        self.assertIn(DeviceCategory.OUTPUT, audio.categories)

    def test_deduplicates_case_insensitive_instance_ids(self):
        first = device(InstanceId="USB\\ABC", FriendlyName="Device", Class="USB")
        richer = device(
            InstanceId="usb\\abc",
            FriendlyName="Device",
            Class="USB",
            LocationInfo="Port 1",
            Service="driver",
        )
        result = deduplicate_devices([first, richer])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].connection, "Port 1")

    def test_missing_instance_id_is_skipped(self):
        self.assertIsNone(device(FriendlyName="No identity", Class="USB"))

    def test_provider_parses_json_and_reports_bad_records(self):
        payload = json.dumps(
            [
                {"InstanceId": "USB\\A", "FriendlyName": "Keyboard", "Class": "Keyboard"},
                {"FriendlyName": "No ID"},
            ]
        )

        def runner(script):
            del script
            return subprocess.CompletedProcess([], 0, payload, "")

        report = PeripheralDiscovery(runner=runner).discover()
        self.assertEqual(len(report.devices), 1)
        self.assertTrue(report.errors)

    def test_provider_reports_command_failure(self):
        def runner(script):
            del script
            return subprocess.CompletedProcess([], 1, "", "access denied")

        report = PeripheralDiscovery(runner=runner).discover()
        self.assertEqual(report.devices, ())
        self.assertIn("access denied", report.errors[0])

    def test_provider_reports_timeout(self):
        def runner(script):
            del script
            raise subprocess.TimeoutExpired("powershell.exe", 30)

        report = PeripheralDiscovery(runner=runner).discover()
        self.assertIn("timed out", report.errors[0])

    def test_panel_filters_and_shows_available_details(self):
        keyboard = device(
            InstanceId="HID\\KEYBOARD",
            FriendlyName="Office Keyboard",
            Manufacturer="Example",
            Status="OK",
            Class="Keyboard",
            DriverProviderName="Example Driver",
            LocationInfo="USB Port 1",
        )
        monitor = device(
            InstanceId="DISPLAY\\MONITOR",
            FriendlyName="Office Monitor",
            Class="Monitor",
        )

        class FakeDiscovery:
            def discover(self):
                from peripheral_control.discovery import PeripheralDiscoveryReport

                return PeripheralDiscoveryReport((keyboard, monitor))

        panel = PeripheralPanel(FakeDiscovery())
        panel._devices = (keyboard, monitor)
        panel._refresh_list()
        self.assertEqual(panel._list.count(), 2)
        panel._filter.setCurrentIndex(1)
        self.assertEqual(panel._list.count(), 1)
        panel._list.setCurrentRow(0)
        self.assertIn("Office Keyboard", panel._details_label.text())
        self.assertEqual(panel._details.rowCount(), 9)
        panel.shutdown()


if __name__ == "__main__":
    unittest.main()
