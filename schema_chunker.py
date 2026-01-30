#!/usr/bin/env python
__author__ = "A. Laurent"
__editors__ = ["A. Laurent"]
__copyright__ = "© Préfon 2025."
__version__ = "2.0.0"

"""
Chunker specialise pour le dictionnaire des donnees ACC.
Decoupe les schemas en chunks hierarchiques optimises pour le RAG.

Structure arborescente:
- schema_summary: Identite + description + stats
- schema_fields: Tableau des champs
- schema_links: Relations avec autres schemas
- schema_indexes: Index et cles
- schema_enum_[name]: Chaque enumeration
- schema_method_[name]: Chaque methode SOAP
"""

import re
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path

from .base_chunker import BaseChunker, Chunk


class SchemaChunker(BaseChunker):
    """
    Chunker hierarchique pour le dictionnaire des donnees Adobe Campaign.
    Cree des chunks structures par type de contenu.
    """

    # Tailles cibles en tokens
    MAX_SUMMARY_TOKENS = 300
    MAX_FIELDS_TOKENS = 600
    MAX_ENUM_TOKENS = 400

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        """
        Initialise le chunker de schemas.

        Args:
            chunk_size: Taille cible des chunks (tokens).
            chunk_overlap: Chevauchement entre chunks.
        """
        super().__init__(chunk_size, chunk_overlap, doc_type="schema")

    def chunk_file(self, filepath: str) -> List[Chunk]:
        """
        Decoupe le fichier Dictionnaire_donnees.md en chunks hierarchiques.

        Args:
            filepath: Chemin vers le fichier.

        Returns:
            Liste de chunks.
        """
        path = Path(filepath)
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return self.chunk_content(content, path.name)

    def chunk_content(self, content: str, source_file: str) -> List[Chunk]:
        """
        Decoupe le dictionnaire en chunks hierarchiques par schema.

        Args:
            content: Contenu markdown du dictionnaire.
            source_file: Nom du fichier source.

        Returns:
            Liste de chunks.
        """
        chunks = []
        
        # Decoupe par schema individuel (# header)
        schemas = self._split_by_schema(content)
        
        for schema_header, schema_content in schemas:
            # Skip les sections d'introduction
            if self._is_intro_section(schema_header):
                continue
            
            schema_chunks = self._chunk_single_schema(schema_header, schema_content, source_file)
            chunks.extend(schema_chunks)
        
        return chunks

    def _is_intro_section(self, header: str) -> bool:
        """
        Verifie si c'est une section d'introduction a ignorer.
        """
        intro_patterns = [
            "dictionnaire", "documentation", "table des", "introduction",
            "statistiques", "explications", "crm prefon"
        ]
        header_lower = header.lower()
        return any(p in header_lower for p in intro_patterns)

    def _split_by_schema(self, content: str) -> List[Tuple[str, str]]:
        """
        Decoupe le contenu par schema individuel (# header).

        Args:
            content: Contenu markdown complet.

        Returns:
            Liste de tuples (header, content).
        """
        schemas = []
        
        # Pattern pour les headers de schema (# au debut de ligne, pas ##)
        pattern = r'^# ([^\n]+)$'
        
        matches = list(re.finditer(pattern, content, re.MULTILINE))
        
        for i, match in enumerate(matches):
            header = match.group(1).strip()
            start = match.start()
            
            # Fin = debut du prochain header # ou fin du fichier
            if i + 1 < len(matches):
                end = matches[i + 1].start()
            else:
                end = len(content)
            
            schema_content = content[start:end].strip()
            
            # Ignore les schemas trop courts (probablement des titres de section)
            if len(schema_content) > 200:
                schemas.append((header, schema_content))
        
        return schemas

    def _chunk_single_schema(
        self,
        schema_header: str,
        schema_content: str,
        source_file: str
    ) -> List[Chunk]:
        """
        Cree les chunks hierarchiques pour un seul schema.

        Args:
            schema_header: Nom/libelle du schema.
            schema_content: Contenu complet du schema.
            source_file: Fichier source.

        Returns:
            Liste de chunks (summary, fields, links, enums, methods).
        """
        chunks = []
        
        # Extraction des metadonnees
        metadata = self._extract_schema_metadata(schema_content)
        schema_name = metadata.get("internal_name", schema_header)
        metadata["schema_label"] = schema_header
        
        # 1. CHUNK SUMMARY (identite + description)
        summary_content = self._extract_summary(schema_header, schema_content, metadata)
        if summary_content:
            chunks.append(Chunk(
                id=self._generate_chunk_id(source_file, f"{schema_name}_summary", 0),
                content=summary_content,
                doc_type="schema",
                source_file=source_file,
                section="summary",
                metadata={**metadata, "chunk_type": "summary"}
            ))
        
        # 2. CHUNK FIELDS (tableau des champs)
        fields_chunks = self._extract_fields(schema_content, schema_name, source_file, metadata)
        chunks.extend(fields_chunks)
        
        # 3. CHUNK LINKS (relations)
        links_content = self._extract_links(schema_content, schema_name)
        if links_content:
            chunks.append(Chunk(
                id=self._generate_chunk_id(source_file, f"{schema_name}_links", 0),
                content=links_content,
                doc_type="schema",
                source_file=source_file,
                section="links",
                metadata={**metadata, "chunk_type": "links"}
            ))
        
        # 4. CHUNK INDEXES (index et cles)
        indexes_content = self._extract_indexes(schema_content, schema_name)
        if indexes_content:
            chunks.append(Chunk(
                id=self._generate_chunk_id(source_file, f"{schema_name}_indexes", 0),
                content=indexes_content,
                doc_type="schema",
                source_file=source_file,
                section="indexes",
                metadata={**metadata, "chunk_type": "indexes"}
            ))
        
        # 5. CHUNKS ENUMERATIONS (une par enum)
        enum_chunks = self._extract_enumerations(schema_content, schema_name, source_file, metadata)
        chunks.extend(enum_chunks)
        
        # 6. CHUNKS METHODS (une par methode)
        method_chunks = self._extract_methods(schema_content, schema_name, source_file, metadata)
        chunks.extend(method_chunks)
        
        return chunks

    def _extract_schema_metadata(self, content: str) -> Dict[str, Any]:
        """
        Extrait les metadonnees d'un schema.
        """
        metadata = {
            "internal_name": "",
            "namespace": "pre",
            "label": "",
            "description": "",
            "has_enumerations": False,
            "has_methods": False,
            "fields_count": 0,
            "links_count": 0,
        }
        
        # Extraction du nom interne complet (namespace:name)
        match = re.search(r'Nom interne\s*:\s*`([^`]+)`', content)
        if match:
            full_name = match.group(1)
            if ':' in full_name:
                parts = full_name.split(':')
                metadata["namespace"] = parts[0]
                metadata["internal_name"] = parts[1]
            else:
                metadata["internal_name"] = full_name
        
        # Extraction du libelle
        match = re.search(r'Libellé\s*:\s*\*\*([^*]+)\*\*', content)
        if match:
            metadata["label"] = match.group(1).strip()
        
        # Extraction de la description
        match = re.search(r'Description\s*:\s*\*\*([^*]+)\*\*', content)
        if match:
            metadata["description"] = match.group(1).strip()
        
        # Detection des enumerations
        if re.search(r'^## Énumérations', content, re.MULTILINE):
            metadata["has_enumerations"] = True
        
        # Detection des methodes
        if re.search(r'^## Méthodes', content, re.MULTILINE):
            metadata["has_methods"] = True
        
        # Comptage des champs
        fields = re.findall(r'^\|\s*`[^`]+`\s*\|', content, re.MULTILINE)
        metadata["fields_count"] = len(fields)
        
        # Comptage des liens
        links = re.findall(r'^\|\s*`[^`]+`\s*->\s*`[^`]+`', content, re.MULTILINE)
        metadata["links_count"] = len(links)
        
        return metadata

    def _extract_summary(self, header: str, content: str, metadata: Dict[str, Any]) -> str:
        """
        Extrait le resume du schema (identite + description + stats).
        """
        parts = [f"# Schema: {header}"]
        
        # Identite
        if metadata.get("internal_name"):
            ns = metadata.get("namespace", "pre")
            parts.append(f"**Nom interne**: `{ns}:{metadata['internal_name']}`")
        
        if metadata.get("label"):
            parts.append(f"**Libelle**: {metadata['label']}")
        
        if metadata.get("description"):
            parts.append(f"**Description**: {metadata['description']}")
        
        # Stats
        stats = []
        if metadata.get("fields_count"):
            stats.append(f"{metadata['fields_count']} champs")
        if metadata.get("links_count"):
            stats.append(f"{metadata['links_count']} liens")
        if metadata.get("has_enumerations"):
            stats.append("enumerations")
        if metadata.get("has_methods"):
            stats.append("methodes SOAP")
        
        if stats:
            parts.append(f"**Contient**: {', '.join(stats)}")
        
        # Extension
        extend_match = re.search(r'étend\s+`([^`]+)`', content)
        if extend_match:
            parts.append(f"**Etend**: `{extend_match.group(1)}`")
        
        return '\n\n'.join(parts)

    def _extract_fields(
        self,
        content: str,
        schema_name: str,
        source_file: str,
        metadata: Dict[str, Any]
    ) -> List[Chunk]:
        """
        Extrait le tableau des champs, subdivise si necessaire.
        """
        chunks = []
        
        # Cherche le tableau des champs
        match = re.search(
            r'(### Champs\s*\n\|[^\n]+\n\|[-:| ]+\n(?:\|[^\n]+\n)*)',
            content,
            re.MULTILINE
        )
        
        if not match:
            return chunks
        
        fields_table = match.group(1)
        
        # Contexte pour le chunk
        header = f"### Champs du schema `{metadata.get('namespace', 'pre')}:{schema_name}`\n\n"
        
        # Subdivise si trop long
        if self._estimate_tokens(fields_table) > self.MAX_FIELDS_TOKENS:
            # Decoupe par groupes de lignes
            lines = fields_table.split('\n')
            header_lines = lines[:2]  # Header + separator
            data_lines = lines[2:]
            
            chunk_idx = 0
            current_lines = header_lines.copy()
            
            for line in data_lines:
                current_lines.append(line)
                
                if self._estimate_tokens('\n'.join(current_lines)) > self.MAX_FIELDS_TOKENS:
                    chunk_content = header + '\n'.join(current_lines[:-1])
                    chunks.append(Chunk(
                        id=self._generate_chunk_id(source_file, f"{schema_name}_fields", chunk_idx),
                        content=self._clean_content(chunk_content),
                        doc_type="schema",
                        source_file=source_file,
                        section="fields",
                        metadata={**metadata, "chunk_type": "fields", "part": chunk_idx + 1}
                    ))
                    chunk_idx += 1
                    current_lines = header_lines.copy() + [line]
            
            # Dernier chunk
            if len(current_lines) > 2:
                chunk_content = header + '\n'.join(current_lines)
                chunks.append(Chunk(
                    id=self._generate_chunk_id(source_file, f"{schema_name}_fields", chunk_idx),
                    content=self._clean_content(chunk_content),
                    doc_type="schema",
                    source_file=source_file,
                    section="fields",
                    metadata={**metadata, "chunk_type": "fields", "part": chunk_idx + 1}
                ))
        else:
            # Un seul chunk
            chunk_content = header + fields_table
            chunks.append(Chunk(
                id=self._generate_chunk_id(source_file, f"{schema_name}_fields", 0),
                content=self._clean_content(chunk_content),
                doc_type="schema",
                source_file=source_file,
                section="fields",
                metadata={**metadata, "chunk_type": "fields"}
            ))
        
        return chunks

    def _extract_links(self, content: str, schema_name: str) -> str:
        """
        Extrait le tableau des liens/relations.
        """
        match = re.search(
            r'(### Liens\s*\n\|[^\n]+\n\|[-:| ]+\n(?:\|[^\n]+\n)*)',
            content,
            re.MULTILINE
        )
        
        if not match:
            return ""
        
        links_table = match.group(1)
        header = f"### Relations du schema `{schema_name}`\n\n"
        
        return self._clean_content(header + links_table)

    def _extract_indexes(self, content: str, schema_name: str) -> str:
        """
        Extrait les index et cles.
        """
        parts = []
        
        # Index
        index_match = re.search(
            r'(### Index\s*\n\|[^\n]+\n\|[-:| ]+\n(?:\|[^\n]+\n)*)',
            content,
            re.MULTILINE
        )
        if index_match:
            parts.append(index_match.group(1))
        
        # Cles
        keys_match = re.search(r'### Clés\s*\n([^\n#]+)', content)
        if keys_match:
            parts.append(f"### Cles\n{keys_match.group(1)}")
        
        if not parts:
            return ""
        
        header = f"### Index et cles du schema `{schema_name}`\n\n"
        return self._clean_content(header + '\n\n'.join(parts))

    def _extract_enumerations(
        self,
        content: str,
        schema_name: str,
        source_file: str,
        metadata: Dict[str, Any]
    ) -> List[Chunk]:
        """
        Extrait chaque enumeration individuellement.
        """
        chunks = []
        
        # Cherche la section enumerations
        enum_section_match = re.search(
            r'## Énumérations\s*\n(.*?)(?=^## [^É]|^# |$)',
            content,
            re.MULTILINE | re.DOTALL
        )
        
        if not enum_section_match:
            return chunks
        
        enum_section = enum_section_match.group(1)
        
        # Decoupe par enumeration (### nom_enum)
        enum_pattern = r'^### (\w+)\s*\n(.*?)(?=^### |\Z)'
        
        for idx, match in enumerate(re.finditer(enum_pattern, enum_section, re.MULTILINE | re.DOTALL)):
            enum_name = match.group(1)
            enum_content = match.group(2).strip()
            
            # Contexte complet
            chunk_content = f"""### Enumeration `{enum_name}` du schema `{schema_name}`

{enum_content}"""
            
            enum_metadata = {
                **metadata,
                "chunk_type": "enumeration",
                "enumeration_name": enum_name
            }
            
            chunks.append(Chunk(
                id=self._generate_chunk_id(source_file, f"{schema_name}_enum_{enum_name}", idx),
                content=self._clean_content(chunk_content),
                doc_type="schema",
                source_file=source_file,
                section="enumeration",
                metadata=enum_metadata
            ))
        
        return chunks

    def _extract_methods(
        self,
        content: str,
        schema_name: str,
        source_file: str,
        metadata: Dict[str, Any]
    ) -> List[Chunk]:
        """
        Extrait chaque methode SOAP individuellement.
        """
        chunks = []
        
        # Cherche la section methodes
        method_section_match = re.search(
            r'## Méthodes\s*\n(.*?)(?=^## |^# |$)',
            content,
            re.MULTILINE | re.DOTALL
        )
        
        if not method_section_match:
            return chunks
        
        method_section = method_section_match.group(1)
        
        # Decoupe par methode (### nom_methode ou pattern similaire)
        method_pattern = r'^### (\w+)\s*\n(.*?)(?=^### |\Z)'
        
        for idx, match in enumerate(re.finditer(method_pattern, method_section, re.MULTILINE | re.DOTALL)):
            method_name = match.group(1)
            method_content = match.group(2).strip()
            
            # Contexte complet
            chunk_content = f"""### Methode SOAP `{method_name}` du schema `{schema_name}`

{method_content}"""
            
            method_metadata = {
                **metadata,
                "chunk_type": "method",
                "method_name": method_name
            }
            
            chunks.append(Chunk(
                id=self._generate_chunk_id(source_file, f"{schema_name}_method_{method_name}", idx),
                content=self._clean_content(chunk_content),
                doc_type="schema",
                source_file=source_file,
                section="method",
                metadata=method_metadata
            ))
        
        return chunks
