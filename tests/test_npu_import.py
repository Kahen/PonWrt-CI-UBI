"""Prevent regressions in the Airoha NPU plugin import origin."""
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class NpuImportTests(unittest.TestCase):
    def setUp(self):
        self.script = (ROOT / "scripts/customize.sh").read_text()

    def test_bash_syntax(self):
        subprocess.run(["bash", "-n", str(ROOT / "scripts/customize.sh")], check=True)

    def test_pinned_upstream_and_correct_origin(self):
        self.assertIn('local repo="rchen14b/luci-app-airoha-npu"', self.script)
        self.assertIn('local revision="14521b8414da1e98517a295d8ec267087c7dde8e"', self.script)
        self.assertIn('git -C "$dest" remote add origin "https://github.com/${repo}.git"', self.script)
        self.assertIn('git -C "$dest" remote get-url origin', self.script)
        self.assertNotIn('remote add origin "https://github.com/Kahen/PonWrt-CI-UBI.git"', self.script)

    def test_import_uses_pinned_commit(self):
        self.assertIn('git -C "$dest" fetch --depth=1 origin "$revision"', self.script)
        self.assertIn('record_commit "$repo" "$dest"', self.script)


if __name__ == "__main__":
    unittest.main()
