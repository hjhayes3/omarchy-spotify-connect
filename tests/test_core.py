import unittest

from spotify_connect.core import Device, apply_playback_device, merge_remembered_devices, parse_devices, resolve_device, token_expired


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.devices = [
            Device("a1", "Kitchen", "speaker", False, False),
            Device("b2", "Kitchen", "computer", False, False),
            Device("c3", "Whole House", "speaker", True, True),
        ]

    def test_parse_devices_skips_missing_ids(self):
        parsed = parse_devices({"devices": [{"id": "x", "name": "Desk", "type": "computer", "is_active": True}, {"id": None, "name": "Bad"}]})
        self.assertEqual(["Desk"], [d.name for d in parsed])
        self.assertTrue(parsed[0].is_active)

    def test_invalid_device_response(self):
        with self.assertRaises(ValueError):
            parse_devices({"unexpected": []})

    def test_unique_name_is_case_insensitive(self):
        self.assertEqual("c3", resolve_device(self.devices, "whole house").id)

    def test_duplicate_name_is_rejected(self):
        with self.assertRaisesRegex(LookupError, "ambiguous"):
            resolve_device(self.devices, "Kitchen")

    def test_id_selection_handles_duplicates(self):
        self.assertEqual("b2", resolve_device(self.devices, "b2", by_id=True).id)

    def test_missing_device(self):
        with self.assertRaisesRegex(LookupError, "not found"):
            resolve_device(self.devices, "Bedroom")

    def test_playback_state_overrides_active_flag(self):
        updated = apply_playback_device(self.devices, {"device": {"id": "a1"}})
        self.assertEqual([True, False, False], [d.is_active for d in updated])

    def test_active_playback_device_is_added_when_devices_endpoint_omits_it(self):
        updated = apply_playback_device([], {"device": {"id": "google1", "name": "Living Room", "type": "speaker", "is_restricted": False}})
        self.assertEqual(["Living Room"], [d.name for d in updated])
        self.assertTrue(updated[0].is_active)
        self.assertTrue(updated[0].is_available)

    def test_remembered_device_is_merged_as_unavailable(self):
        merged = merge_remembered_devices([], [{"id": "old1", "name": "Whole House", "type": "speaker"}])
        self.assertEqual("Whole House", merged[0].name)
        self.assertTrue(merged[0].is_remembered)
        self.assertFalse(merged[0].is_available)

    def test_live_remembered_device_keeps_live_state(self):
        live = [Device("a1", "Kitchen", "speaker", True, False)]
        merged = merge_remembered_devices(live, [{"id": "a1", "name": "Old name", "type": "speaker"}])
        self.assertEqual("Kitchen", merged[0].name)
        self.assertTrue(merged[0].is_active)
        self.assertTrue(merged[0].is_available)
        self.assertTrue(merged[0].is_remembered)

    def test_token_expiration_with_leeway(self):
        self.assertTrue(token_expired({"expires_at": 1050}, now=1000, leeway=60))
        self.assertFalse(token_expired({"expires_at": 1061}, now=1000, leeway=60))
        self.assertTrue(token_expired({}, now=1000))


if __name__ == "__main__":
    unittest.main()
