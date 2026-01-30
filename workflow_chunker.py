#!/usr/bin/env python
__author__ = "A. Laurent"
__editors__ = ["A. Laurent"]
__copyright__ = "© Préfon 2025."
__version__ = "2.0.0"

"""
Chunker specialise pour les documents de workflows ACC.
Decoupe les fichiers markdown de workflows en chunks hierarchiques.

Structure arborescente:
- workflow_summary: Metadonnees + description (chunk parent)
- workflow_activities: Tableau des activites
- workflow_script: Chaque script JS individuellement
"""

import re
from typing import List, Dict, Any, Tuple
from pathlib import Path

from .base_chunker import BaseChunker, Chunk


class WorkflowChunker(BaseChunker):
    """
    Chunker hierarchique pour les documents de workflows Adobe Campaign.
    Cree des chunks structures par type de contenu.
    """

    # Tailles cibles en tokens
    MAX_SUMMARY_TOKENS = 400
    MAX_ACTIVITIES_TOKENS = 600
    MAX_SCRIPT_TOKENS = 800

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        """
        Initialise le chunker de workflows.

        Args:
            chunk_size: Taille cible des chunks (tokens).
            chunk_overlap: Chevauchement entre chunks.
        """
        super().__init__(chunk_size, chunk_overlap, doc_type="workflow")

    def chunk_file(self, filepath: str) -> List[Chunk]:
        """
        Decoupe un fichier workflow markdown en chunks hierarchiques.

        Args:
            filepath: Chemin vers le fichier .md du workflow.

        Returns:
            Liste de chunks.
        """
        path = Path(filepath)
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return self.chunk_content(content, path.name)

    def chunk_content(self, content: str, source_file: str) -> List[Chunk]:
        """
        Decoupe le contenu en chunks hierarchiques.
        Detecte chaque workflow (### header) et cree des chunks structures.

        Args:
            content: Contenu markdown complet.
            source_file: Nom du fichier source.

        Returns:
            Liste de chunks.
        """
        chunks = []
        
        # Decoupe par workflow individuel (### header)
        workflows = self._split_by_workflow(content)
        
        for wf_header, wf_content in workflows:
            wf_chunks = self._chunk_single_workflow(wf_header, wf_content, source_file)
            chunks.extend(wf_chunks)
        
        return chunks

    def _split_by_workflow(self, content: str) -> List[Tuple[str, str]]:
        """
        Decoupe le contenu par workflow individuel (### header).

        Args:
            content: Contenu markdown complet.

        Returns:
            Liste de tuples (header, content).
        """
        workflows = []
        
        # Pattern pour detecter les headers de workflow (### )
        pattern = r'^### (.+?)$'
        
        # Trouve tous les headers et leurs positions
        matches = list(re.finditer(pattern, content, re.MULTILINE))
        
        for i, match in enumerate(matches):
            header = match.group(1).strip()
            start = match.start()
            
            # Fin = debut du prochain header ou fin du fichier
            if i + 1 < len(matches):
                end = matches[i + 1].start()
            else:
                end = len(content)
            
            wf_content = content[start:end].strip()
            
            # Ignore les headers vides ou trop courts
            if len(wf_content) > 100:
                workflows.append((header, wf_content))
        
        return workflows

    def _chunk_single_workflow(
        self,
        wf_header: str,
        wf_content: str,
        source_file: str
    ) -> List[Chunk]:
        """
        Cree les chunks hierarchiques pour un seul workflow.

        Args:
            wf_header: Nom du workflow.
            wf_content: Contenu complet du workflow.
            source_file: Fichier source.

        Returns:
            Liste de chunks (summary, activities, scripts).
        """
        chunks = []
        
        # Extraction des metadonnees
        metadata = self._extract_workflow_metadata(wf_content)
        workflow_name = metadata.get("workflow_name", wf_header)
        metadata["workflow_label"] = wf_header
        
        # 1. CHUNK SUMMARY (metadonnees + description)
        summary_content = self._extract_summary(wf_content)
        if summary_content:
            chunks.append(Chunk(
                id=self._generate_chunk_id(source_file, f"{workflow_name}_summary", 0),
                content=summary_content,
                doc_type="workflow",
                source_file=source_file,
                section="summary",
                metadata={**metadata, "chunk_type": "summary"}
            ))
        
        # 2. CHUNK ACTIVITIES (tableau des activites)
        activities_content = self._extract_activities(wf_content, workflow_name)
        if activities_content:
            chunks.append(Chunk(
                id=self._generate_chunk_id(source_file, f"{workflow_name}_activities", 0),
                content=activities_content,
                doc_type="workflow",
                source_file=source_file,
                section="activities",
                metadata={**metadata, "chunk_type": "activities"}
            ))
        
        # 3. CHUNKS SCRIPTS (un chunk par script JS)
        scripts = self._extract_scripts(wf_content, workflow_name)
        for idx, (script_name, script_content) in enumerate(scripts):
            script_metadata = {**metadata, "chunk_type": "script", "script_name": script_name}
            
            # Subdivise si le script est trop long
            if self._estimate_tokens(script_content) > self.MAX_SCRIPT_TOKENS:
                sub_chunks = self._subdivide_script(script_content, script_name, source_file, script_metadata, idx)
                chunks.extend(sub_chunks)
            else:
                chunks.append(Chunk(
                    id=self._generate_chunk_id(source_file, f"{workflow_name}_script", idx),
                    content=script_content,
                    doc_type="workflow",
                    source_file=source_file,
                    section="script",
                    metadata=script_metadata
                ))
        
        return chunks

    def _extract_summary(self, content: str) -> str:
        """
        Extrait le resume du workflow (header + proprietes + description).

        Args:
            content: Contenu du workflow.

        Returns:
            Texte du resume.
        """
        parts = []
        
        # Header
        header_match = re.match(r'^### .+$', content, re.MULTILINE)
        if header_match:
            parts.append(header_match.group(0))
        
        # Tableau des proprietes (jusqu'a "Caracteristiques" ou "Activites")
        props_match = re.search(
            r'(\| \*\*Propri.+?\|[\s\S]*?)(?=\*\*Caract|\*\*Activit|\*\*Scripts|$)',
            content
        )
        if props_match:
            parts.append(props_match.group(1).strip())
        
        # Caracteristiques
        carac_match = re.search(
            r'(\*\*Caract.+?\*\*[\s\S]*?)(?=\*\*Description|\*\*Activit|$)',
            content
        )
        if carac_match:
            parts.append(carac_match.group(1).strip())
        
        # Description
        desc_match = re.search(
            r'\*\*Description:\*\*\s*([\s\S]*?)(?=\*\*Activit|\*\*Scripts|$)',
            content
        )
        if desc_match:
            desc_text = desc_match.group(1).strip()
            # Limite la description a 500 chars
            if len(desc_text) > 500:
                desc_text = desc_text[:500] + "..."
            parts.append(f"**Description:** {desc_text}")
        
        summary = "\n\n".join(parts)
        return self._clean_content(summary)

    def _extract_activities(self, content: str, workflow_name: str) -> str:
        """
        Extrait le tableau des activites.

        Args:
            content: Contenu du workflow.
            workflow_name: Nom du workflow (pour contexte).

        Returns:
            Texte des activites avec contexte.
        """
        # Cherche le tableau des activites
        match = re.search(
            r'(\*\*Activit.+?\*\*[\s\S]*?\|[\s\S]*?)(?=\*\*Scripts|\n## |\n### |$)',
            content
        )
        
        if not match:
            return ""
        
        activities_text = match.group(1).strip()
        
        # Ajoute le contexte du workflow
        header = f"### Activites du workflow `{workflow_name}`\n\n"
        
        return self._clean_content(header + activities_text)

    def _extract_scripts(self, content: str, workflow_name: str) -> List[Tuple[str, str]]:
        """
        Extrait tous les scripts JavaScript individuellement.

        Args:
            content: Contenu du workflow.
            workflow_name: Nom du workflow.

        Returns:
            Liste de tuples (nom_script, contenu_avec_contexte).
        """
        scripts = []
        
        # Pattern pour les scripts JS
        pattern = r'\*Script:\s*([^*]+)\*\s*```javascript([\s\S]*?)```'
        
        for match in re.finditer(pattern, content):
            script_name = match.group(1).strip()
            script_code = match.group(2).strip()
            
            # Contexte complet pour le chunk
            script_content = f"""### Script JavaScript: {script_name}
**Workflow**: `{workflow_name}`

```javascript
{script_code}
```"""
            
            scripts.append((script_name, script_content))
        
        return scripts

    def _subdivide_script(
        self,
        script_content: str,
        script_name: str,
        source_file: str,
        metadata: Dict[str, Any],
        base_idx: int
    ) -> List[Chunk]:
        """
        Subdivise un script trop long en plusieurs chunks.

        Args:
            script_content: Contenu du script.
            script_name: Nom du script.
            source_file: Fichier source.
            metadata: Metadonnees de base.
            base_idx: Index de base.

        Returns:
            Liste de chunks subdivises.
        """
        chunks = []
        
        # Decoupe par lignes avec chevauchement
        lines = script_content.split('\n')
        chunk_lines = []
        current_tokens = 0
        sub_idx = 0
        
        for line in lines:
            line_tokens = self._estimate_tokens(line)
            
            if current_tokens + line_tokens > self.MAX_SCRIPT_TOKENS and chunk_lines:
                # Cree un chunk
                chunk_content = '\n'.join(chunk_lines)
                chunks.append(Chunk(
                    id=self._generate_chunk_id(source_file, f"{script_name}_part", base_idx * 100 + sub_idx),
                    content=chunk_content,
                    doc_type="workflow",
                    source_file=source_file,
                    section="script",
                    metadata={**metadata, "part": sub_idx + 1}
                ))
                
                # Garde les dernieres lignes pour le chevauchement
                overlap_lines = chunk_lines[-3:] if len(chunk_lines) > 3 else []
                chunk_lines = overlap_lines
                current_tokens = sum(self._estimate_tokens(l) for l in chunk_lines)
                sub_idx += 1
            
            chunk_lines.append(line)
            current_tokens += line_tokens
        
        # Dernier chunk
        if chunk_lines:
            chunk_content = '\n'.join(chunk_lines)
            chunks.append(Chunk(
                id=self._generate_chunk_id(source_file, f"{script_name}_part", base_idx * 100 + sub_idx),
                content=chunk_content,
                doc_type="workflow",
                source_file=source_file,
                section="script",
                metadata={**metadata, "part": sub_idx + 1}
            ))
        
        return chunks

    def _extract_workflow_metadata(self, content: str) -> Dict[str, Any]:
        """
        Extrait les metadonnees d'un workflow depuis le markdown.

        Args:
            content: Contenu markdown.

        Returns:
            Dictionnaire de metadonnees.
        """
        metadata = {
            "workflow_name": "",
            "has_js": False,
            "has_sql": False,
            "has_delivery": False,
            "activities_count": 0,
        }
        
        # Extraction du nom interne
        match = re.search(r'\*\*Nom interne\*\*[:\s|]*`([^`]+)`', content)
        if match:
            metadata["workflow_name"] = match.group(1)
        
        # Detection de JavaScript
        if '```javascript' in content or '| O |' in content and 'JavaScript' in content:
            metadata["has_js"] = True
        
        # Detection de SQL
        if re.search(r'\|\s*O\s*\|.*SQL', content, re.IGNORECASE):
            metadata["has_sql"] = True
        
        # Detection de delivery
        if 'delivery' in content.lower() or 'diffusion' in content.lower():
            metadata["has_delivery"] = True
        
        # Comptage des activites
        activities = re.findall(r'^\|\s*\{urn:', content, re.MULTILINE)
        metadata["activities_count"] = len(activities)
        
        return metadata
