import os
from typing import List

def find_po_files(directory: str, recursive: bool = False) -> List[str]:
    """
    Finds all .po files in the specified directory, handling case-insensitive extensions
    across all platforms (e.g., .po, .PO, .Po, .pO).
    
    Args:
        directory: The directory to search in.
        recursive: Whether to search subdirectories recursively.
        
    Returns:
        A sorted list of unique absolute paths to .po files.
    """
    found_files = []
    
    if recursive:
        for root, _, files in os.walk(directory):
            for file in files:
                if file.lower().endswith('.po'):
                    found_files.append(os.path.join(root, file))
    else:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_file() and entry.name.lower().endswith('.po'):
                    found_files.append(entry.path)
                    
    return sorted(list(set(found_files)))
