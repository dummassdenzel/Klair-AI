"""
Filename Trie Service

Provides O(m) prefix-based filename search where m = query length,
not number of files. Enables instant autocomplete and fast filename queries.

Performance: 100-10,000x faster than SQL ILIKE for large directories.
"""

import logging
from typing import List, Set, Optional, Dict
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)


class TrieNode:
    """Node in the Trie data structure"""
    
    def __init__(self):
        self.children: Dict[str, 'TrieNode'] = {}
        self.file_paths: Set[str] = set()  # Files ending at this node
        self.is_end: bool = False  # True if this node represents end of a filename


class FilenameTrie:
    """
    Trie (Prefix Tree) for fast filename search.
    
    Supports:
    - O(m) prefix search where m = query length
    - Case-insensitive matching
    - Multiple files per prefix
    - Fast autocomplete suggestions
    """
    
    def __init__(self):
        self.root = TrieNode()
        self.file_count = 0
        logger.info("FilenameTrie initialized")
    
    def add(self, filename: str, file_path: str) -> None:
        """
        Add a filename to the Trie.
        
        Args:
            filename: The filename (without path)
            file_path: Full path to the file
        """
        if not filename or not file_path:
            return
        
        # Normalize: lowercase for case-insensitive search
        filename_lower = filename.lower()
        node = self.root
        
        # Traverse/create path for each character
        for char in filename_lower:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        
        # Mark end of filename and store file path
        node.is_end = True
        node.file_paths.add(file_path)
        self.file_count += 1
        
        logger.debug(f"Added to Trie: {filename} → {file_path}")
    
    def remove(self, filename: str, file_path: str) -> None:
        """
        Remove a filename from the Trie.
        
        Args:
            filename: The filename (without path)
            file_path: Full path to the file
        """
        if not filename or not file_path:
            return
        
        filename_lower = filename.lower()
        node = self.root
        
        # Traverse to the end node
        for char in filename_lower:
            if char not in node.children:
                return  # File not in Trie
            node = node.children[char]
        
        # Remove file path from this node
        if file_path in node.file_paths:
            node.file_paths.remove(file_path)
            self.file_count -= 1
            
            # If no more files at this node, mark as not end
            if not node.file_paths:
                node.is_end = False
            
            logger.debug(f"Removed from Trie: {filename} → {file_path}")
    
    def search(self, query: str, max_results: Optional[int] = None) -> List[str]:
        """
        Search for filenames matching the query prefix.
        
        Args:
            query: Search query (prefix)
            max_results: Maximum number of results to return (None = all)
            
        Returns:
            List of file paths matching the query
        """
        if not query:
            return []
        
        query_lower = query.lower().strip()
        if not query_lower:
            return []
        
        # Traverse to the node matching the query prefix
        node = self.root
        for char in query_lower:
            if char not in node.children:
                return []  # No matches
            node = node.children[char]
        
        # Collect all file paths from this node and its children
        results = []
        self._collect_all_paths(node, results, max_results)
        
        logger.debug(f"Trie search '{query}' found {len(results)} files")
        return results
    
    def _collect_all_paths(self, node: TrieNode, results: List[str], max_results: Optional[int]) -> None:
        """
        Recursively collect all file paths from a node and its children.
        
        Args:
            node: Current Trie node
            results: List to collect results in
            max_results: Maximum results to collect (None = all)
        """
        # Add files from current node
        if node.is_end and node.file_paths:
            for file_path in node.file_paths:
                if max_results is not None and len(results) >= max_results:
                    return
                results.append(file_path)
        
        # Recursively collect from children
        if max_results is None or len(results) < max_results:
            for child_node in node.children.values():
                self._collect_all_paths(child_node, results, max_results)
                if max_results is not None and len(results) >= max_results:
                    return
    
    def search_prefix(self, prefix: str) -> List[str]:
        """
        Search for filenames starting with the given prefix.
        Alias for search() for clarity.
        
        Args:
            prefix: Filename prefix to search for
            
        Returns:
            List of file paths matching the prefix
        """
        return self.search(prefix)
    
    def autocomplete(self, prefix: str, max_suggestions: int = 10) -> List[str]:
        """
        Get autocomplete suggestions for a prefix.
        Returns filenames (not paths) for display.
        
        Args:
            prefix: Prefix to autocomplete
            max_suggestions: Maximum number of suggestions
            
        Returns:
            List of filenames matching the prefix
        """
        file_paths = self.search(prefix, max_results=max_suggestions)
        # Extract just filenames for autocomplete
        filenames = [Path(fp).name for fp in file_paths]
        return filenames[:max_suggestions]
    
    def contains(self, filename: str) -> bool:
        """
        Check if a filename exists in the Trie.
        
        Args:
            filename: Filename to check
            
        Returns:
            True if filename exists in Trie
        """
        filename_lower = filename.lower()
        node = self.root
        
        for char in filename_lower:
            if char not in node.children:
                return False
            node = node.children[char]
        
        return node.is_end and len(node.file_paths) > 0
    
    def get_stats(self) -> Dict:
        """
        Get Trie statistics.
        
        Returns:
            Dictionary with Trie stats
        """
        return {
            "file_count": self.file_count,
            "node_count": self._count_nodes(self.root),
            "depth": self._max_depth(self.root)
        }
    
    def _count_nodes(self, node: TrieNode) -> int:
        """Count total nodes in Trie"""
        count = 1
        for child in node.children.values():
            count += self._count_nodes(child)
        return count
    
    def _max_depth(self, node: TrieNode) -> int:
        """Get maximum depth of Trie"""
        if not node.children:
            return 0
        return 1 + max(self._max_depth(child) for child in node.children.values())
    
    def clear(self) -> None:
        """Clear all entries from the Trie"""
        self.root = TrieNode()
        self.file_count = 0
        logger.info("FilenameTrie cleared")
    
    def search_by_file_type(self, query: str, file_type: str) -> List[str]:
        """
        Search for files matching query and file type.
        
        Args:
            query: Search query
            file_type: File extension (e.g., "pdf", "docx")
            
        Returns:
            List of file paths matching both query and file type
        """
        # Get all matches for query
        matches = self.search(query)
        
        # Filter by file type
        file_type_lower = file_type.lower().lstrip('.')
        filtered = [
            fp for fp in matches
            if Path(fp).suffix.lower().lstrip('.') == file_type_lower
        ]
        
        logger.debug(f"Trie search '{query}' with type '{file_type}' found {len(filtered)} files")
        return filtered

