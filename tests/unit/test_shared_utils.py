import os
import shutil
import tempfile
import unittest
from core.utils import find_po_files

class TestCoreUtils(unittest.TestCase):
    def setUp(self):
        """Set up a temporary directory structure for file discovery tests."""
        self.test_dir = tempfile.mkdtemp()
        
        # Create some test files with different cases
        # 1. Top-level files
        with open(os.path.join(self.test_dir, "test1.po"), "w") as f: f.write("")
        with open(os.path.join(self.test_dir, "test2.PO"), "w") as f: f.write("")
        with open(os.path.join(self.test_dir, "test3.txt"), "w") as f: f.write("")
        
        # 2. Sub-directory files
        self.sub_dir = os.path.join(self.test_dir, "subdir")
        os.makedirs(self.sub_dir)
        with open(os.path.join(self.sub_dir, "test4.Po"), "w") as f: f.write("")
        with open(os.path.join(self.sub_dir, "test5.pO"), "w") as f: f.write("")
        with open(os.path.join(self.sub_dir, "test6.csv"), "w") as f: f.write("")

    def tearDown(self):
        """Clean up the test directory."""
        shutil.rmtree(self.test_dir)

    def test_find_po_files_top_level(self):
        """Verify that non-recursive search only finds .po files at the top level and is case-insensitive."""
        files = find_po_files(self.test_dir, recursive=False)
        
        self.assertEqual(len(files), 2)
        # Should find .po and .PO files
        filenames = [os.path.basename(f) for f in files]
        self.assertIn("test1.po", filenames)
        self.assertIn("test2.PO", filenames)

    def test_find_po_files_recursive(self):
        """Verify that recursive search finds .po files in subdirectories as well, ignoring non-po files."""
        files = find_po_files(self.test_dir, recursive=True)
        
        self.assertEqual(len(files), 4)
        filenames = [os.path.basename(f) for f in files]
        
        # Verify it found standard and all weirdly cased .po files
        self.assertIn("test1.po", filenames)
        self.assertIn("test2.PO", filenames)
        self.assertIn("test4.Po", filenames)
        self.assertIn("test5.pO", filenames)
        
        # Ensure it didn't pick up .txt or .csv
        self.assertNotIn("test3.txt", filenames)
        self.assertNotIn("test6.csv", filenames)

if __name__ == "__main__":
    unittest.main()
