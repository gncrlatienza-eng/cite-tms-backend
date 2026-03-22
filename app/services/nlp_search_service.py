from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# Loaded once at startup — not per request (performance optimization)
_model = SentenceTransformer("all-MiniLM-L6-v2")

# Tailored to CITE department thesis topics
THESIS_TOPICS = [
    # CS / IT core
    "cybersecurity", "network defense", "ethical hacking", "penetration testing",
    "machine learning", "neural network", "deep learning", "artificial intelligence",
    "web development", "REST API", "frontend", "backend", "full stack",
    "mobile development", "android", "flutter", "react native",
    "database", "SQL", "data modeling", "normalization",
    "computer vision", "image recognition", "object detection",
    "natural language processing", "text classification", "sentiment analysis",
    "software engineering", "system design", "agile", "SDLC",
    "networking", "TCP/IP", "routing", "protocols", "IoT",
    "cloud computing", "virtualization", "containerization", "docker",
    # CITE-specific programs
    "BSCS", "BSIT", "BSEMC", "information technology", "computer science",
]

def expand_query(query: str, threshold: float = 0.35) -> list[str]:
    """
    Expands a search query with semantically similar thesis topics.
    threshold: lower = more results, higher = stricter match
    """
    query_embedding = _model.encode([query])
    topic_embeddings = _model.encode(THESIS_TOPICS)

    scores = cosine_similarity(query_embedding, topic_embeddings)[0]

    expanded = [
        THESIS_TOPICS[i]
        for i, score in enumerate(scores)
        if score >= threshold
    ]

    # Always include the original query term
    if query.lower() not in [t.lower() for t in expanded]:
        expanded.insert(0, query)

    return expanded