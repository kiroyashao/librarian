# Librarian

> A sub-project of [Forge](https://github.com/kiroyashao/forge.git) 

Librarian is an AI Skills management system built on LangGraph/LangChain. It automates the organization, deduplication, evaluation, and maintenance of AI skills with support for human review workflows, scheduled jobs, and a REST API.

---

## Why Librarian?

In the Forge project, skills are organized using a folder-based classification system. While this approach provides clear categorization, it introduces several significant problems:

- **Redundancy**: Skills often contain overlapping or duplicate content across different folders, leading to maintenance nightmares and inconsistent behavior.
- **Rigid Structure**: Flat folder hierarchies cannot express complex relationships between skills, making it difficult to navigate and discover related capabilities.
- **Inefficient Management**: As the number of skills grows, manual organization becomes unsustainable. Pruning outdated skills, detecting duplicates, and maintaining cross-references require constant human intervention.
- **Lack of Dynamic Adaptation**: The static folder structure cannot evolve with the skill ecosystem. New skills are added without intelligent routing, and obsolete skills linger without automatic cleanup.

**Librarian solves these problems** by introducing a multi-agent system that transforms the flat skill collection into a **nested, hierarchical skills tree**. This tree structure is dynamically managed by specialized agents that handle:

- Intelligent skill routing and categorization
- Automatic deduplication and quality evaluation
- Cross-link maintenance between related skills
- Pruning of obsolete or low-quality skills
- Tool synthesis and safety guardianship

The result is a self-organizing, self-maintaining skills ecosystem that scales gracefully and eliminates the redundancy and inefficiency of the original folder-based approach.

---

## Architecture

Librarian employs a multi-agent architecture with specialized workers:

| Worker | Responsibility |
|--------|---------------|
| `SkillRouter` | Routes incoming skills to appropriate categories |
| `SkillEvaluator` | Evaluates skill quality with configurable thresholds |
| `SkillDeduplicator` | Detects and removes duplicate skills |
| `SkillSplitter` | Splits large skills into manageable chunks |
| `SkillPruner` | Removes obsolete or low-quality skills |
| `SkillLinkMaintainer` | Maintains cross-references between skills |
| `ToolSynthesizer` | Synthesizes tools from skill capabilities |
| `ToolGuardian` | Ensures tool safety with optional human review |

---

## Installation

```bash
# Clone the repository
git clone https://github.com/kiroyashao/librarian.git
cd librarian

# Install dependencies
uv pip install -e .

```

---

## Configuration

Librarian uses a YAML configuration file (`librarian.yaml`) for system settings and environment variables for sensitive credentials.

### Key Configuration Options

```yaml
llms:
  - name: llm-1
    model: <MODEL>
    apiKey: <API_KEY>
    apiBase: <API_BASE>
  ...
workers:
  SkillEvaluator:
    llm: llm-1
    qualityThreshold: 0.7
    requireHumanReview: false
    categories:
      - data_analysis
      - web_scraping
      - file_management
  ...
skillTriggerThreshold: 10  # Skills needed to trigger workflow
maxRejectionCount: 3       # Max rejections before discarding

api:
  port: 9112
  host: "0.0.0.0"
```

See [librarian.yaml](librarian.yaml) for the full configuration template.

---

## Usage

### Starting the Server

```bash
python main.py
```

The API server will start on `http://localhost:9112` by default.

---

## API Reference

### Skills Management

#### Get a Single Skill

```http
GET /skills/{skill_name}
```

**Response:**
```json
{
  "record": { ... },
  "frontmatter": { ... },
  "content": "# Skill content..."
}
```

#### Get Skill Links

```http
GET /skills/{skill_name}/links
```

---

### Human Review

#### Get Pending Reviews

```http
GET /reviews
```

#### Submit a Review

```http
POST /reviews/{review_id}
Content-Type: application/json

{
  "approved": true,
  "comment": "Looks good!"
}
```

## Cronjobs

Librarian includes a built-in scheduler for periodic maintenance tasks:

```yaml
cronjobs:
  enabled: true
  jobs:
    cleaner:
      schedule: "0 0 */3 * *"  # Every 3 days at midnight
    merger:
      schedule: "0 0 */3 * *"
```

Cron expressions follow standard Unix cron format.

---

## Project Structure

```
librarian/
├── src/
│   ├── api/              # FastAPI server
│   ├── config/           # Configuration management
│   ├── db/               # Database manager
│   ├── git_manager/      # Git version control
│   ├── models/           # Data models
│   ├── tools/            # Built-in tools
│   ├── workers/          # Multi-agent workers
│   └── workflows/        # Workflow definitions
├── tests/                # Unit and integration tests
├── data/                 # SQLite database
├── librarian.yaml        # Configuration file
└── main.py               # Entry point
```

---

## License

This project is part of the Forge ecosystem.
