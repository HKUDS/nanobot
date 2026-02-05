"""
EmbeddingGenerator - generate vector representation for memory

Supports multiple embedding generation methods:
1. OpenAI Embedding API
2. Local model (through Sentence Transformers)
3. Custom embedding provider
"""

from typing import List, Optional, Dict, Any
from loguru import logger
import asyncio

TAG = __name__


class EmbeddingGenerator:
    """vector generator"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        initialize vector generator
        
        Args:
            config: configuration dictionary, containing:
                - provider: "openai", "local", "custom"
                - model: model name
                - api_key: API key (if using OpenAI)
                - base_url: API base URL (optional)
                - dimension: vector dimension
        """
        self.config = config if config is not None else {}
        self.provider = self.config.get("provider", "dummy")
        self.model = self.config.get("model", "text-embedding-ada-002")
        self.dimension = self.config.get("dimension", 1536)
        self.api_key = self.config.get("api_key")
        self.base_url = self.config.get("base_url")
        
        # initialize embedding client
        self.client = None
        self._initialize_client()
        
        logger.bind(tag=TAG).info(
            f"EmbeddingGenerator initialized with provider={self.provider}, "
            f"model={self.model}, dimension={self.dimension}"
        )
    
    def _initialize_client(self):
        """initialize embedding client"""
        if self.provider == "openai":
            try:
                from openai import AsyncOpenAI
                self.client = AsyncOpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
                logger.bind(tag=TAG).info("OpenAI embedding client initialized")
            except ImportError:
                logger.bind(tag=TAG).error("OpenAI package not installed, falling back to dummy embeddings")
                self.provider = "dummy"
            except Exception as e:
                logger.bind(tag=TAG).error(f"Failed to initialize OpenAI client: {e}, falling back to dummy")
                self.provider = "dummy"
        
        elif self.provider == "local":
            try:
                from sentence_transformers import SentenceTransformer
                self.client = SentenceTransformer(self.model)
                logger.bind(tag=TAG).info(f"Local sentence-transformer model '{self.model}' loaded")
            except ImportError:
                logger.bind(tag=TAG).error("sentence-transformers not installed, falling back to dummy embeddings")
                self.provider = "dummy"
            except Exception as e:
                logger.bind(tag=TAG).error(f"Failed to load local model: {e}, falling back to dummy")
                self.provider = "dummy"
        
        elif self.provider == "dummy":
            logger.bind(tag=TAG).warning("Using dummy embeddings (random vectors)")
        
        else:
            logger.bind(tag=TAG).warning(f"Unknown provider '{self.provider}', using dummy embeddings")
            self.provider = "dummy"
    
    async def generate_embedding(self, text: str) -> List[float]:
        """
        generate vector representation for text
        
        Args:
            text: input text
        
        Returns:
            vector representation (List[float])
        """
        if not text or not text.strip():
            logger.bind(tag=TAG).warning("Empty text provided for embedding, returning zero vector")
            return [0.0] * self.dimension
        
        try:
            if self.provider == "openai":
                return await self._generate_openai_embedding(text)
            elif self.provider == "local":
                return await self._generate_local_embedding(text)
            else:
                return self._generate_dummy_embedding(text)
        except Exception as e:
            logger.bind(tag=TAG).error(f"Failed to generate embedding: {e}, using dummy embedding")
            return self._generate_dummy_embedding(text)
    
    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        generate vector representation for multiple texts (for efficiency)
        
        Args:
            texts: text list
        
        Returns:
            vector list
        """
        if self.provider == "openai":
            return await self._generate_openai_embeddings_batch(texts)
        elif self.provider == "local":
            return await self._generate_local_embeddings_batch(texts)
        else:
            return [self._generate_dummy_embedding(text) for text in texts]
    
    async def _generate_openai_embedding(self, text: str) -> List[float]:
        """generate embedding using OpenAI API"""
        if self.client is None:
            raise RuntimeError("OpenAI client not initialized")
        
        response = await self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding
    
    async def _generate_openai_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """generate OpenAI embeddings batch"""
        if self.client is None:
            raise RuntimeError("OpenAI client not initialized")
        
        response = await self.client.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [item.embedding for item in response.data]
    
    async def _generate_local_embedding(self, text: str) -> List[float]:
        """generate embedding using local model"""
        if self.client is None:
            raise RuntimeError("Local model not initialized")
        
        # SentenceTransformer's encode is synchronous, running in asyncio
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(None, self.client.encode, text)
        return embedding.tolist()
    
    async def _generate_local_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """generate local embeddings batch"""
        if self.client is None:
            raise RuntimeError("Local model not initialized")
        
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(None, self.client.encode, texts)
        return [emb.tolist() for emb in embeddings]
    
    def _generate_dummy_embedding(self, text: str) -> List[float]:
        """generate dummy embedding (for testing)"""
        import hashlib
        import numpy as np
        
        # use text hash as random seed, ensuring same text always generates same vector
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**32)
        np.random.seed(seed)
        
        # generate random vector and normalize
        vec = np.random.randn(self.dimension)
        vec = vec / np.linalg.norm(vec)
        
        return vec.tolist()
