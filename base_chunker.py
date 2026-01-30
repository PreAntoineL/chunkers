#!/usr/bin/env python
__author__ = "A. Laurent"
__editors__ = ["A. Laurent"]
__copyright__ = "© Préfon 2025."
__version__ = "1.1.0"

"""
Classe de base pour les chunkers de documents.
Définit l'interface commune et les structures de données.
"""

import hashlib
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path

# Namespace UUID pour les chunks ACC (genere une fois, fixe)
ACC_NAMESPACE = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


@dataclass
class Chunk:
    """
    Représente un fragment de document indexable.
    """
    id: str
    content: str
    doc_type: str
    source_file: str
    section: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """ Convertit le chunk en dictionnaire pour l'indexation. """
        result = {
            "id": self.id,
            "content": self.content,
            "doc_type": self.doc_type,
            "source_file": self.source_file,
            "section": self.section,
        }
        result.update(self.metadata)
        return result


class BaseChunker(ABC):
    """
    Classe abstraite pour le découpage de documents en chunks.
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        doc_type: str = "generic"
    ):
        """
        Initialise le chunker.

        Args:
            chunk_size: Taille cible des chunks (en tokens approximatifs).
            chunk_overlap: Chevauchement entre chunks consécutifs.
            doc_type: Type de document (workflow, javascript, schema).
        """
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._doc_type = doc_type

    @abstractmethod
    def chunk_file(self, filepath: str) -> List[Chunk]:
        """
        Découpe un fichier en chunks.

        Args:
            filepath: Chemin vers le fichier à découper.

        Returns:
            Liste de chunks.
        """
        pass

    @abstractmethod
    def chunk_content(self, content: str, source_file: str) -> List[Chunk]:
        """
        Découpe un contenu textuel en chunks.

        Args:
            content: Contenu textuel à découper.
            source_file: Nom du fichier source (pour métadonnées).

        Returns:
            Liste de chunks.
        """
        pass

    def _generate_chunk_id(self, source_file: str, section: str, index: int) -> str:
        """
        Génère un UUID unique pour un chunk (compatible Qdrant).

        Args:
            source_file: Fichier source.
            section: Section du document.
            index: Index du chunk dans la section.

        Returns:
            UUID valide au format string.
        """
        key = f"{source_file}:{section}:{index}"
        return str(uuid.uuid5(ACC_NAMESPACE, key))

    def _estimate_tokens(self, text: str) -> int:
        """
        Estime le nombre de tokens dans un texte.
        Approximation simple : 1 token ~ 4 caractères.

        Args:
            text: Texte à analyser.

        Returns:
            Estimation du nombre de tokens.
        """
        return len(text) // 4

    def _split_by_headers(self, content: str, header_pattern: str) -> List[tuple]:
        """
        Découpe le contenu par en-têtes markdown.

        Args:
            content: Contenu markdown.
            header_pattern: Pattern regex pour les en-têtes (ex: r'^#{1,4} ').

        Returns:
            Liste de tuples (header, content).
        """
        sections = []
        lines = content.split('\n')
        current_header = ""
        current_content = []
        
        for line in lines:
            if re.match(header_pattern, line):
                if current_content:
                    sections.append((current_header, '\n'.join(current_content)))
                current_header = line.strip()
                current_content = [line]
            else:
                current_content.append(line)
        
        if current_content:
            sections.append((current_header, '\n'.join(current_content)))
        
        return sections

    def _merge_small_chunks(self, chunks: List[Chunk], min_size: int = 100) -> List[Chunk]:
        """
        Fusionne les chunks trop petits avec le précédent.

        Args:
            chunks: Liste de chunks.
            min_size: Taille minimale en tokens.

        Returns:
            Liste de chunks fusionnés.
        """
        if not chunks:
            return chunks
        
        merged = []
        buffer = None
        
        for chunk in chunks:
            if buffer is None:
                buffer = chunk
            elif self._estimate_tokens(buffer.content) < min_size:
                # Fusionne avec le chunk courant
                buffer.content = buffer.content + "\n\n" + chunk.content
                buffer.section = buffer.section  # Garde la première section
            else:
                merged.append(buffer)
                buffer = chunk
        
        if buffer is not None:
            merged.append(buffer)
        
        return merged

    def _clean_content(self, content: str) -> str:
        """
        Nettoie le contenu pour l'indexation.

        Args:
            content: Contenu brut.

        Returns:
            Contenu nettoyé.
        """
        # Supprime les lignes vides multiples
        content = re.sub(r'\n{3,}', '\n\n', content)
        # Supprime les espaces en fin de ligne
        content = re.sub(r' +\n', '\n', content)
        return content.strip()
