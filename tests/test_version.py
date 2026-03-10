from __future__ import annotations

import unittest

from codex_chat_gateway import __version__


class VersionTests(unittest.TestCase):
    def test_version_is_defined(self) -> None:
        self.assertEqual(__version__, "0.1.0")
