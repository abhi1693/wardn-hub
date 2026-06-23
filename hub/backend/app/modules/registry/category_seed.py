from dataclasses import dataclass


@dataclass(frozen=True)
class CategorySeed:
    slug: str
    name: str
    description: str
    sort_order: int


MCP_SERVERS_CATEGORY_SEEDS: tuple[CategorySeed, ...] = (
    CategorySeed("search", "Search", "Search, retrieval, and discovery MCP servers.", 100),
    CategorySeed(
        "web-scraping",
        "Web Scraping",
        "Browser automation, scraping, and extraction servers.",
        110,
    ),
    CategorySeed(
        "communication",
        "Communication",
        "Messaging, meetings, email, and collaboration servers.",
        120,
    ),
    CategorySeed(
        "productivity",
        "Productivity",
        "Task, calendar, notes, and workflow productivity servers.",
        130,
    ),
    CategorySeed("marketing", "Marketing", "Marketing, growth, and brand operation servers.", 140),
    CategorySeed(
        "design",
        "Design",
        "Design, creative, media, and asset workflow servers.",
        150,
    ),
    CategorySeed("memory", "Memory", "Memory, context, and long-term knowledge servers.", 160),
    CategorySeed(
        "finance",
        "Finance",
        "Financial data, accounting, and market workflow servers.",
        170,
    ),
    CategorySeed(
        "development",
        "Development",
        "Developer tools, coding agents, and engineering servers.",
        180,
    ),
    CategorySeed("database", "Database", "Database, SQL, storage, and data platform servers.", 190),
    CategorySeed(
        "cloud-service",
        "Cloud Service",
        "Cloud provider and infrastructure operation servers.",
        200,
    ),
    CategorySeed(
        "file-system",
        "File System",
        "Local and remote file system access servers.",
        210,
    ),
    CategorySeed(
        "cloud-storage",
        "Cloud Storage",
        "Object storage, document storage, and drive servers.",
        220,
    ),
    CategorySeed(
        "version-control",
        "Version Control",
        "Repository, issue, pull request, and source control servers.",
        230,
    ),
    CategorySeed(
        "other",
        "Other",
        "Servers that do not fit an existing primary category.",
        1000,
    ),
)
