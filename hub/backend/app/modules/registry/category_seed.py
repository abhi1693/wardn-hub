from dataclasses import dataclass


@dataclass(frozen=True)
class CategorySeed:
    slug: str
    name: str
    description: str
    sort_order: int


MCP_SERVERS_CATEGORY_SEEDS: tuple[CategorySeed, ...] = (
    CategorySeed(
        "aggregators", "Aggregators", "Multi-source aggregation and gateway MCP servers.", 100
    ),
    CategorySeed(
        "art-culture",
        "Art & Culture",
        "Art, culture, creative collections, and media archive MCP servers.",
        110,
    ),
    CategorySeed(
        "architecture-design",
        "Architecture & Design",
        "Architecture, design systems, CAD, and spatial design MCP servers.",
        120,
    ),
    CategorySeed(
        "browser-automation",
        "Browser Automation",
        "Browser control, web automation, scraping, and extraction MCP servers.",
        130,
    ),
    CategorySeed(
        "biology-medicine-bioinformatics",
        "Biology Medicine and Bioinformatics",
        "Healthcare, biology, medicine, and bioinformatics MCP servers.",
        140,
    ),
    CategorySeed(
        "cloud-platforms",
        "Cloud Platforms",
        "Cloud provider, infrastructure, and platform operation MCP servers.",
        150,
    ),
    CategorySeed(
        "code-execution", "Code Execution", "Sandboxed code execution and runtime MCP servers.", 160
    ),
    CategorySeed(
        "coding-agents",
        "Coding Agents",
        "Agentic coding, code review, and engineering-assistant MCP servers.",
        170,
    ),
    CategorySeed(
        "command-line",
        "Command Line",
        "Terminal, shell, and command-line workflow MCP servers.",
        180,
    ),
    CategorySeed(
        "communication",
        "Communication",
        "Messaging, meetings, email, and collaboration MCP servers.",
        190,
    ),
    CategorySeed(
        "conversational-ai",
        "Conversational AI",
        "Chat, voice assistant, and conversational AI MCP servers.",
        200,
    ),
    CategorySeed(
        "cryptography",
        "Cryptography",
        "Cryptography, keys, signing, and secure identity MCP servers.",
        210,
    ),
    CategorySeed(
        "customer-data-platforms",
        "Customer Data Platforms",
        "Customer profiles, CRM data, analytics identity, and CDP MCP servers.",
        220,
    ),
    CategorySeed(
        "databases", "Databases", "Database, SQL, NoSQL, vector store, and query MCP servers.", 230
    ),
    CategorySeed(
        "data-platforms",
        "Data Platforms",
        "Warehouses, lakes, ETL, and business data platform MCP servers.",
        240,
    ),
    CategorySeed(
        "delivery",
        "Delivery",
        "Shipping, logistics, dispatch, and delivery operation MCP servers.",
        250,
    ),
    CategorySeed(
        "developer-tools",
        "Developer Tools",
        "Developer productivity, build, test, and utility MCP servers.",
        260,
    ),
    CategorySeed(
        "data-science-tools",
        "Data Science Tools",
        "Notebook, statistics, ML, and data science workflow MCP servers.",
        270,
    ),
    CategorySeed(
        "data-visualization",
        "Data Visualization",
        "Charting, dashboard, and visualization MCP servers.",
        280,
    ),
    CategorySeed(
        "embedded-system",
        "Embedded system",
        "Embedded systems, hardware, firmware, and IoT MCP servers.",
        290,
    ),
    CategorySeed(
        "education", "Education", "Learning, teaching, academic, and education MCP servers.", 300
    ),
    CategorySeed(
        "e-commerce", "E-Commerce", "Commerce, catalog, orders, and marketplace MCP servers.", 310
    ),
    CategorySeed(
        "environment-nature",
        "Environment & Nature",
        "Environment, nature, climate, and sustainability MCP servers.",
        320,
    ),
    CategorySeed(
        "file-systems",
        "File Systems",
        "Local, remote, object, and document file system MCP servers.",
        330,
    ),
    CategorySeed(
        "finance-fintech",
        "Finance & Fintech",
        "Financial data, fintech, accounting, and crypto MCP servers.",
        340,
    ),
    CategorySeed(
        "gaming", "Gaming", "Games, game services, and interactive entertainment MCP servers.", 350
    ),
    CategorySeed(
        "home-automation",
        "Home Automation",
        "Smart home, home services, and automation MCP servers.",
        360,
    ),
    CategorySeed(
        "knowledge-memory",
        "Knowledge & Memory",
        "Memory, context, notes, and knowledge management MCP servers.",
        370,
    ),
    CategorySeed(
        "legal",
        "Legal",
        "Legal research, contracts, compliance, and case workflow MCP servers.",
        380,
    ),
    CategorySeed(
        "location-services",
        "Location Services",
        "Maps, geocoding, routing, and location intelligence MCP servers.",
        390,
    ),
    CategorySeed(
        "marketing", "Marketing", "Marketing, sales, growth, and brand operation MCP servers.", 400
    ),
    CategorySeed(
        "monitoring",
        "Monitoring",
        "Monitoring, observability, alerting, and telemetry MCP servers.",
        410,
    ),
    CategorySeed(
        "multimedia-process",
        "Multimedia Process",
        "Image, audio, video, and media processing MCP servers.",
        420,
    ),
    CategorySeed(
        "os-automation",
        "OS Automation",
        "Desktop, operating system, and local automation MCP servers.",
        430,
    ),
    CategorySeed(
        "product-management",
        "Product Management",
        "Product, project, roadmap, and task management MCP servers.",
        440,
    ),
    CategorySeed(
        "real-estate", "Real Estate", "Real estate, property, and home service MCP servers.", 450
    ),
    CategorySeed(
        "research",
        "Research",
        "Science, research, papers, and scholarly workflow MCP servers.",
        460,
    ),
    CategorySeed(
        "search-data-extraction",
        "Search & Data Extraction",
        "Search, retrieval, crawling, and data extraction MCP servers.",
        470,
    ),
    CategorySeed(
        "security", "Security", "Security, vulnerability, audit, and identity MCP servers.", 480
    ),
    CategorySeed(
        "social-media",
        "Social Media",
        "Social media, content platform, and community MCP servers.",
        490,
    ),
    CategorySeed(
        "spirituality-esoterica",
        "Spirituality & Esoterica",
        "Spirituality, astrology, esoterica, and reflective MCP servers.",
        500,
    ),
    CategorySeed(
        "sports", "Sports", "Sports data, teams, schedules, and performance MCP servers.", 510
    ),
    CategorySeed(
        "support-service-management",
        "Support & Service Management",
        "Support desk, ITSM, service management, and customer service MCP servers.",
        520,
    ),
    CategorySeed(
        "translation-services",
        "Translation Services",
        "Translation, localization, and multilingual workflow MCP servers.",
        530,
    ),
    CategorySeed(
        "text-to-speech",
        "Text-to-Speech",
        "Speech synthesis and audio generation MCP servers.",
        540,
    ),
    CategorySeed(
        "speech-to-text",
        "Speech-to-Text",
        "Transcription, speech recognition, and voice input MCP servers.",
        550,
    ),
    CategorySeed(
        "travel-transportation",
        "Travel & Transportation",
        "Travel, transit, mobility, and transportation MCP servers.",
        560,
    ),
    CategorySeed(
        "version-control",
        "Version Control",
        "Repository, issue, pull request, and source control MCP servers.",
        570,
    ),
    CategorySeed(
        "workplace-productivity",
        "Workplace & Productivity",
        "Workplace, documents, calendar, and productivity MCP servers.",
        580,
    ),
    CategorySeed(
        "other-tools-integrations",
        "Other Tools and Integrations",
        "Tools and integrations that do not fit an existing primary category.",
        1000,
    ),
)

DEFAULT_CATEGORY_SLUG = "other-tools-integrations"
MCP_SERVERS_CATEGORY_SLUGS = frozenset(category.slug for category in MCP_SERVERS_CATEGORY_SEEDS)
