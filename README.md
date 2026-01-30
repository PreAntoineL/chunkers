# Chunkers RAG - Schemas & Workflows

Documentation des chunkers hierarchiques pour le systeme RAG ACC.

---

## BaseChunker

**Fichier** : `base_chunker.py`  
**Role** : Classe abstraite definissant l'interface commune et les utilitaires partages.

### Dataclass Chunk

Structure de donnees pour representer un fragment de document :

```python
@dataclass
class Chunk:
    id: str           # UUID unique (format Qdrant)
    content: str      # Contenu textuel du fragment
    doc_type: str     # Type: "schema", "workflow", "javascript"
    source_file: str  # Fichier d'origine
    section: str      # Type de section (summary, fields, script...)
    metadata: Dict    # Metadonnees contextuelles
```

### Methodes utilitaires

| Methode | Description |
|---------|-------------|
| `_generate_chunk_id()` | Genere un UUID v5 unique et deterministe (meme input = meme ID) |
| `_estimate_tokens()` | Estimation rapide : 1 token ~ 4 caracteres |
| `_split_by_headers()` | Decoupe le markdown par en-tetes (regex configurable) |
| `_merge_small_chunks()` | Fusionne les chunks <100 tokens avec le precedent |
| `_clean_content()` | Nettoie le contenu (lignes vides multiples, espaces) |

### Interface a implementer

Les classes filles **doivent** implementer :

```python
def chunk_file(self, filepath: str) -> List[Chunk]:
    """ Decoupe un fichier en chunks. """

def chunk_content(self, content: str, source_file: str) -> List[Chunk]:
    """ Decoupe un contenu textuel en chunks. """
```

### Generation des IDs

Les IDs sont generes avec `uuid.uuid5()` pour etre :
- **Deterministes** : meme fichier/section/index = meme UUID
- **Compatibles Qdrant** : format UUID valide

```python
# Namespace fixe pour le projet ACC
ACC_NAMESPACE = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

# Generation
key = f"{source_file}:{section}:{index}"
uuid.uuid5(ACC_NAMESPACE, key)
```


---

## Principe general

Les deux chunkers utilisent une **structure arborescente** pour decouper les documents en chunks semantiquement coherents. Chaque chunk possede un `section` qui identifie son type.

```
Document
  |-- summary     (identite + description)
  |-- section_1   (tableau ou bloc specifique)
  |-- section_2   (autre bloc)
  |-- ...
```

---

## SchemaChunker

**Fichier** : `schema_chunker.py`  
**Input** : Fichiers markdown du dictionnaire de donnees

### Types de chunks produits

| Section | Description | Tokens max |
|---------|-------------|------------|
| `summary` | Nom interne, libelle, description, stats | 300 |
| `fields` | Tableau des champs (subdivise si >600 tokens) | 600 |
| `links` | Relations avec autres schemas | - |
| `indexes` | Index et cles du schema | - |
| `enumeration` | Une enumeration (1 chunk par enum) | 400 |
| `method` | Une methode SOAP (1 chunk par methode) | - |

### Metadonnees extraites

```python
{
    "internal_name": "nms:recipient",
    "namespace": "nms",
    "label": "Destinataires",
    "description": "...",
    "has_enumerations": True,
    "has_methods": False,
    "fields_count": 42,
    "links_count": 8,
    "chunk_type": "summary|fields|links|..."
}
```

### Exemple de sortie

```
Schema: nms:recipient
  |-- recipient_summary       (identite + stats)
  |-- recipient_fields        (tableau des 42 champs)
  |-- recipient_links         (8 relations)
  |-- recipient_indexes       (index + cles)
  |-- recipient_enum_gender   (enumeration)
  |-- recipient_enum_status   (enumeration)
```

---

## WorkflowChunker

**Fichier** : `workflow_chunker.py`  
**Input** : Fichiers markdown des workflows

### Types de chunks produits

| Section | Description | Tokens max |
|---------|-------------|------------|
| `summary` | Proprietes, caracteristiques, description | 400 |
| `activities` | Tableau des activites du workflow | 600 |
| `script` | Un script JavaScript (subdivise si >800 tokens) | 800 |

### Metadonnees extraites

```python
{
    "workflow_name": "WKF123",
    "workflow_label": "Import quotidien",
    "has_js": True,
    "has_sql": False,
    "has_delivery": True,
    "activities_count": 12,
    "chunk_type": "summary|activities|script",
    "script_name": "enrichissement"  # si script
}
```

### Exemple de sortie

```
Workflow: WKF123 (Import quotidien)
  |-- WKF123_summary           (proprietes + description)
  |-- WKF123_activities        (12 activites)
  |-- WKF123_script_0          (script "init")
  |-- WKF123_script_1          (script "enrichissement")
```

---

## Utilisation

```python
from src.rag.chunkers import SchemaChunker, WorkflowChunker

# Schemas
schema_chunker = SchemaChunker(chunk_size=512, chunk_overlap=50)
schema_chunks = schema_chunker.chunk_file("Dictionnaire_donnees_prod.md")

# Workflows
workflow_chunker = WorkflowChunker(chunk_size=512, chunk_overlap=50)
workflow_chunks = workflow_chunker.chunk_file("workflows_documentation.md")

# Acces aux donnees
for chunk in schema_chunks:
    print(f"ID: {chunk.id}")
    print(f"Type: {chunk.section}")
    print(f"Metadata: {chunk.metadata}")
```

---

## Subdivision automatique

Les deux chunkers subdivisent automatiquement les sections trop longues :

- **SchemaChunker** : subdivise `fields` si >600 tokens
- **WorkflowChunker** : subdivise `script` si >800 tokens

Les chunks subdivises ont une metadonnee `part` pour indiquer leur position.

---

## Structure Chunk

```python
@dataclass
class Chunk:
    id: str           # UUID unique
    content: str      # Contenu textuel
    doc_type: str     # "schema" ou "workflow"
    source_file: str  # Fichier d'origine
    section: str      # Type de section
    metadata: Dict    # Metadonnees extraites
```
