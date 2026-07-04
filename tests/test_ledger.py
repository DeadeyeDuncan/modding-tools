import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ledger


class LedgerTestCase(unittest.TestCase):
    """Base: builds a synthetic game dir with ledger.json, manifests/, Data/, Plugins.txt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = self.root / "Data"
        self.data_dir.mkdir()
        self.manifests = self.root / "manifests"
        self.manifests.mkdir()
        self.plugins_txt = self.root / "Plugins.txt"
        self.ledger_path = self.root / "ledger.json"

    def write_ledger(self, mods, header=None):
        data = {
            "game": "Skyrim Special Edition",
            "dataDir": str(self.data_dir),
            "pluginsTxt": str(self.plugins_txt),
            "mods": mods,
        }
        if header:
            data.update(header)
        text = json.dumps(data, indent=4).replace("\n", "\r\n")
        self.ledger_path.write_bytes(text.encode("utf-8"))
        return data


if __name__ == "__main__":
    unittest.main()
