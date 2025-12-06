"""
BM25 Keyword Search Service

Provides exact keyword matching to complement semantic search.
Particularly good for:
- Exact codes (G.P.#, TCO004, etc.)
- Numbers and IDs
- Proper nouns
- Technical terms
"""

import logging
import pickle
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from rank_bm25 import BM25Okapi
import re

logger = logging.getLogger(__name__)


class BM25Service:
    """Handles keyword-based search using BM25 algorithm"""
    
    def __init__(self, persist_dir: str = "./chroma_db"):
        """
        Initialize BM25 service
        
        Args:
            persist_dir: Directory to persist BM25 index
        """
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        self.bm25_index_path = self.persist_dir / "bm25_index.pkl"
        self.documents_path = self.persist_dir / "bm25_documents.pkl"
        
        # BM25 index and corpus
        self.bm25: Optional[BM25Okapi] = None
        self.corpus: List[Dict] = []  # List of {id, text, metadata}
        self.tokenized_corpus: List[List[str]] = []
        
        # Load existing index if available
        self._load_index()
        
        logger.info(f"BM25Service initialized with {len(self.corpus)} documents")
    
    def _tokenize(self, text: str) -> List[str]:
        """
        Tokenize text for BM25
        
        Preserves:
        - Codes with dots and special chars (G.P.#, T.C.O.)
        - Alphanumeric codes (TCO004, BIP-12046)
        - Numbers
        
        Args:
            text: Input text
            
        Returns:
            List of tokens
        """
        # Convert to lowercase for case-insensitive matching
        text = text.lower()
        
        # Enhanced tokenization that preserves special codes
        # Captures: alphanumeric + optional (dot/dash/# + alphanumeric) patterns
        # Also captures standalone alphanumeric tokens
        tokens = re.findall(r'[a-z0-9]+(?:[.\-#]+[a-z0-9]*)*', text)
        
        # Additional pass: also extract individual components for partial matching
        # This ensures "g.p.#" matches both as a whole and as parts
        extended_tokens = []
        for token in tokens:
            extended_tokens.append(token)
            # If token contains special chars, also add the parts
            if any(c in token for c in '.#-'):
                # Split on special chars and add non-empty parts
                parts = re.split(r'[.\-#]+', token)
                extended_tokens.extend([p for p in parts if p])
        
        return extended_tokens
    
    def add_documents(self, documents: List[Dict]) -> None:
        """
        Add documents to BM25 index
        
        Args:
            documents: List of dicts with 'id', 'text', 'metadata'
        """
        try:
            # Add to corpus
            for doc in documents:
                self.corpus.append(doc)
                tokenized = self._tokenize(doc['text'])
                self.tokenized_corpus.append(tokenized)
            
            # Rebuild BM25 index
            if self.tokenized_corpus:
                self.bm25 = BM25Okapi(self.tokenized_corpus)
                logger.info(f"BM25 index built with {len(self.corpus)} documents")
            
            # Persist to disk
            self._save_index()
            
        except Exception as e:
            logger.error(f"Failed to add documents to BM25: {e}")
            raise
    
    def search(self, query: str, top_k: int = 15) -> List[Tuple[str, float, Dict]]:
        """
        Search documents using BM25 keyword matching
        
        Args:
            query: Search query
            top_k: Number of results to return
            
        Returns:
            List of (chunk_id, score, metadata) tuples, sorted by score (descending)
        """
        if not self.bm25 or not self.corpus:
            logger.warning("BM25 index is empty")
            return []
        
        try:
            # Tokenize query
            tokenized_query = self._tokenize(query)
            
            if not tokenized_query:
                logger.warning(f"Query tokenized to empty: '{query}'")
                return []
            
            # Get BM25 scores
            scores = self.bm25.get_scores(tokenized_query)
            
            # Get top-k indices
            top_indices = scores.argsort()[-top_k:][::-1]
            
            # Build results
            results = []
            for idx in top_indices:
                score = scores[idx]
                if score > 0:  # Only include documents with non-zero score
                    doc = self.corpus[idx]
                    results.append((
                        doc['id'],
                        float(score),
                        doc['metadata']
                    ))
            
            logger.debug(f"BM25 search for '{query}' returned {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"BM25 search failed: {e}")
            return []
    
    def clear(self) -> None:
        """Clear all BM25 data"""
        self.bm25 = None
        self.corpus = []
        self.tokenized_corpus = []
        
        # Delete persisted files
        if self.bm25_index_path.exists():
            self.bm25_index_path.unlink()
        if self.documents_path.exists():
            self.documents_path.unlink()
        
        logger.info("BM25 index cleared")
    
    def _save_index(self) -> None:
        """Persist BM25 index to disk"""
        try:
            # Save BM25 index
            with open(self.bm25_index_path, 'wb') as f:
                pickle.dump(self.bm25, f)
            
            # Save corpus and tokenized corpus
            with open(self.documents_path, 'wb') as f:
                pickle.dump({
                    'corpus': self.corpus,
                    'tokenized_corpus': self.tokenized_corpus
                }, f)
            
            logger.debug(f"BM25 index saved to {self.persist_dir}")
            
        except Exception as e:
            logger.error(f"Failed to save BM25 index: {e}")
    
    def _load_index(self) -> None:
        """Load BM25 index from disk"""
        try:
            if self.bm25_index_path.exists() and self.documents_path.exists():
                # Load BM25 index
                with open(self.bm25_index_path, 'rb') as f:
                    self.bm25 = pickle.load(f)
                
                # Load corpus
                with open(self.documents_path, 'rb') as f:
                    data = pickle.load(f)
                    self.corpus = data['corpus']
                    self.tokenized_corpus = data['tokenized_corpus']
                
                logger.info(f"BM25 index loaded from {self.persist_dir} ({len(self.corpus)} documents)")
            else:
                logger.info("No existing BM25 index found")
                
        except Exception as e:
            logger.warning(f"Failed to load BM25 index: {e}, starting fresh")
            self.bm25 = None
            self.corpus = []
            self.tokenized_corpus = []
    
    def get_stats(self) -> Dict:
        """Get BM25 index statistics"""
        return {
            "document_count": len(self.corpus),
            "index_built": self.bm25 is not None,
            "persist_dir": str(self.persist_dir)
        }

