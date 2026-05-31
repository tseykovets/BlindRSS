import unittest

from core import discovery


class TestYoutubePlayerClients(unittest.TestCase):
    def test_cli_arg_form(self):
        arg = discovery.youtube_player_client_arg()
        self.assertTrue(arg.startswith("youtube:player_client="))
        clients = arg.split("=", 1)[1].split(",")
        # Widening the client pool is the reliability fix: keep yt-dlp's maintained
        # "default" set plus the android_vr workaround that keeps packaged builds working.
        self.assertIn("default", clients)
        self.assertIn("android_vr", clients)

    def test_python_list_form(self):
        clients = discovery.youtube_player_client_list()
        self.assertIsInstance(clients, list)
        self.assertIn("default", clients)
        self.assertIn("android_vr", clients)

    def test_arg_and_list_are_consistent(self):
        arg_clients = discovery.youtube_player_client_arg().split("=", 1)[1].split(",")
        self.assertEqual(arg_clients, discovery.youtube_player_client_list())


if __name__ == "__main__":
    unittest.main()
