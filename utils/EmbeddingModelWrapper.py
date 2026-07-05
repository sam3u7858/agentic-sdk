# -*- coding: utf-8 -*-
# Author: Keiki
# Description: EmbeddingModelWrapper – Python interface for embedding models

from typing import Protocol, List, Dict, Optional
import requests
import json
import numpy as np
from numpy.linalg import norm
import openai


class IEmbeddingBackend(Protocol):
    def embed(self, texts: List[str], task_type: Optional[str] = None, output_dimensionality: Optional[int] = None) -> List[List[float]]:
        pass


class EmbeddingModelWrapper:
    """Wrapper for embedding models with unified interface"""

    def __init__(self, backend: IEmbeddingBackend):
        self.backend = backend

    def embed(self, texts: List[str], task_type: Optional[str] = None, output_dimensionality: Optional[int] = None) -> List[List[float]]:
        """Generate embeddings for a list of texts"""
        return self.backend.embed(texts, task_type, output_dimensionality)

    def embed_single(self, text: str, task_type: Optional[str] = None, output_dimensionality: Optional[int] = None) -> List[float]:
        """Generate embedding for a single text"""
        embeddings = self.embed([text], task_type, output_dimensionality)
        return embeddings[0] if embeddings else []

    def cosine_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """Calculate cosine similarity between two embeddings"""
        # Convert to numpy arrays
        emb1 = np.array(embedding1)
        emb2 = np.array(embedding2)

        # Normalize embeddings
        emb1_norm = emb1 / norm(emb1)
        emb2_norm = emb2 / norm(emb2)

        # Calculate cosine similarity
        return float(np.dot(emb1_norm, emb2_norm))

    def normalize_embedding(self, embedding: List[float]) -> List[float]:
        """Normalize embedding vector"""
        emb = np.array(embedding)
        normalized = emb / norm(emb)
        return normalized.tolist()


class OpenAIEmbeddingWrapper:
    """OpenAI Embedding API wrapper"""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model

    def embed(self, texts: List[str], task_type: Optional[str] = None, output_dimensionality: Optional[int] = None) -> List[List[float]]:
        """Generate embeddings using OpenAI API"""
        if not texts:
            return []

        try:
            # The 'input' parameter can be a list of strings
            response = self.client.embeddings.create(
                model=self.model,
                input=texts,
                encoding_format="float",
                # Pass dimensions if specified
                dimensions=output_dimensionality if output_dimensionality else openai.NOT_GIVEN
            )

            # Extract embeddings from the response
            embeddings = [item.embedding for item in response.data]
            return embeddings

        except openai.APIError as e:
            print(f"[OpenAIEmbeddingWrapper] OpenAI API error: {e}")
            return []
        except Exception as e:
            print(
                f"[OpenAIEmbeddingWrapper] An unexpected error occurred: {e}")
            return []


class GeminiEmbeddingModelWrapper:
    """Gemini Embedding API wrapper"""

    def __init__(self, api_key: str, model: str = "gemini-embedding-001"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    def embed(self, texts: List[str], task_type: Optional[str] = None, output_dimensionality: Optional[int] = None) -> List[List[float]]:
        """Generate embeddings using Gemini API"""
        if not texts:
            return []

        all_embeddings = []

        for text in texts:
            # Prepare request payload
            payload = {
                "content": {
                    "parts": [{"text": text}]
                }
            }

            if task_type or output_dimensionality:
                embedding_config = {}
                if task_type:
                    embedding_config["task_type"] = task_type
                if output_dimensionality:
                    embedding_config["output_dimensionality"] = output_dimensionality
                payload["embedding_config"] = embedding_config

            # Make API request
            url = f"{self.base_url}/{self.model}:embedContent"
            headers = {
                "Content-Type": "application/json",
                "X-goog-api-key": self.api_key
            }

            try:
                response = requests.post(
                    url, headers=headers, data=json.dumps(payload))
                response.raise_for_status()
                data = response.json()

                if "embedding" in data:
                    all_embeddings.append(data["embedding"]["values"])

            except requests.exceptions.RequestException as e:
                print(f"[GeminiEmbeddingModelWrapper] API request failed: {e}")
                if e.response is not None:
                    print(
                        f"[GeminiEmbeddingModelWrapper] Response content: {e.response.text}")
                # Return empty list on failure for this text
            except json.JSONDecodeError as e:
                print(f"[GeminiEmbeddingModelWrapper] JSON decode error: {e}")
            except Exception as e:
                print(f"[GeminiEmbeddingModelWrapper] Unexpected error: {e}")

        return all_embeddings

    def embed_with_similarity(self, texts: List[str], task_type: str = "SEMANTIC_SIMILARITY") -> Dict:
        """Generate embeddings and calculate similarity matrix"""
        embeddings = self.embed(texts, task_type=task_type)

        if not embeddings or len(embeddings) < 2:
            return {"embeddings": embeddings, "similarities": []}

        # Calculate similarity matrix
        similarities = []
        for i in range(len(embeddings)):
            row = []
            for j in range(len(embeddings)):
                if i == j:
                    row.append(1.0)
                else:
                    # Calculate cosine similarity
                    emb1 = np.array(embeddings[i])
                    emb2 = np.array(embeddings[j])

                    # Normalize
                    emb1_norm = emb1 / norm(emb1)
                    emb2_norm = emb2 / norm(emb2)

                    similarity = float(np.dot(emb1_norm, emb2_norm))
                    row.append(similarity)
            similarities.append(row)

        return {
            "embeddings": embeddings,
            "similarities": similarities,
            "texts": texts
        }
