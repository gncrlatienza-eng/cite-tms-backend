from fastembed import TextEmbedding
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from rank_bm25 import BM25Okapi
from rapidfuzz import fuzz
import numpy as np

_embedding_model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")

_paper_cache = []
_paper_embeddings = None
_bm25 = None
_topic_cache = []
_topic_embeddings = None
_topic_graph = {}

PROGRAM_KEYWORDS = {
    "BSCS": ["bscs", "computer science", "bachelor of science in computer science"],
    "BSIT": ["bsit", "information technology", "bachelor of science in information technology"],
    "BSCpE": ["bscpe", "bscoe", "computer engineering", "bachelor of science in computer engineering"],
    "BSEE": ["bsee", "electrical engineering", "bachelor of science in electrical engineering"],
    "BSEMC": ["bsemc", "entertainment", "multimedia computing", "bachelor of science in entertainment and multimedia computing"],
    "BSIE": ["bsie", "industrial engineering", "bachelor of science in industrial engineering"],
    "BSARCH": ["bsarch", "architecture", "bachelor of science in architecture"],
}


def _encode(texts: list) -> np.ndarray:
    return np.array(list(_embedding_model.embed(texts)))


def _match_program(query: str) -> list[str]:
    q = query.lower()
    for code, aliases in PROGRAM_KEYWORDS.items():
        for alias in aliases:
            threshold = 75 if len(alias) > 20 else 80
            if fuzz.partial_ratio(q, alias) >= threshold:
                return [code]
    return []


def _build_paper_index(papers: list):
    global _paper_cache, _paper_embeddings, _bm25
    _paper_cache = papers
    texts = [f"{p.get('title', '')} {p.get('abstract', '')}" for p in papers]
    _paper_embeddings = _encode(texts)
    _bm25 = BM25Okapi([t.lower().split() for t in texts])


def _build_topic_index(papers: list):
    global _topic_cache, _topic_embeddings
    extracted = []
    programs = []

    if papers:
        texts = [f"{p.get('title', '')} {p.get('abstract', '')}" for p in papers]
        
        vectorizer = TfidfVectorizer(
            ngram_range=(1, 3),
            stop_words="english",
            max_features=200,
        )
        vectorizer.fit(texts)
        extracted = list(vectorizer.get_feature_names_out())
        
        programs = list(set(
            p.get("course_or_program", "")
            for p in papers
            if p.get("course_or_program")
        ))

    _topic_cache = list(set(extracted + programs))
    _topic_embeddings = _encode(_topic_cache)
    print(f"[NLP] Topics: {len(extracted)} extracted, {len(programs)} programs")


def _build_topic_graph(threshold: float = 0.45):
    global _topic_graph
    if not _topic_cache or _topic_embeddings is None:
        return

    similarity_matrix = cosine_similarity(_topic_embeddings, _topic_embeddings)

    _topic_graph = {}
    for i, topic in enumerate(_topic_cache):
        related = [
            _topic_cache[j]
            for j, score in enumerate(similarity_matrix[i])
            if i != j and score >= threshold
        ]
        if related:
            _topic_graph[topic] = related

    print(f"[NLP] Topic graph built: {len(_topic_graph)} nodes")


def _auto_expand_query(query: str) -> str:
    if not _topic_graph or _topic_embeddings is None:
        return query

    q_vec = _encode([query])
    scores = cosine_similarity(q_vec, _topic_embeddings)[0]

    best_idx = int(scores.argmax())
    best_score = float(scores[best_idx])

    if best_score < 0.35:
        return query

    best_topic = _topic_cache[best_idx]
    related = _topic_graph.get(best_topic, [])

    return " ".join([query, best_topic] + related[:5]).strip()


def build_index():
    from app.database import get_supabase
    supabase = get_supabase()
    res = supabase.table("papers").select(
        "id, title, abstract, authors, year, course_or_program, file_path"
    ).execute()
    papers = res.data or []
    _build_paper_index(papers)
    _build_topic_index(papers)
    _build_topic_graph()
    print(f"[NLP] Indexed {len(papers)} papers, {len(_topic_cache)} topics")


def refresh_index():
    build_index()


def suggest_topics(query: str, top_k: int = 8, threshold: float = 0.35) -> list[str]:
    if not _topic_cache or _topic_embeddings is None:
        return [query]

    q_vec = _encode([query])
    scores = cosine_similarity(q_vec, _topic_embeddings)[0]
    ranked = sorted(
        [(i, float(scores[i])) for i in range(len(scores)) if scores[i] >= threshold],
        key=lambda x: x[1], reverse=True,
    )[:top_k]

    suggestions = [_topic_cache[i] for i, _ in ranked]
    if query.lower() not in [s.lower() for s in suggestions]:
        suggestions.insert(0, query)

    return suggestions


def search_papers(query: str, top_k: int = 15, threshold: float = 0.12) -> list:
    if _paper_embeddings is None or not _paper_cache or _bm25 is None:
        return []

    expanded_query = _auto_expand_query(query)

    q_vec = _encode([expanded_query])
    semantic_scores = cosine_similarity(q_vec, _paper_embeddings)[0]

    bm25_raw = np.array(_bm25.get_scores(query.lower().split()))
    bm25_norm = bm25_raw / (bm25_raw.max() + 1e-9)

    query_len = len(query.split())
    sem_weight = 0.75 if query_len <= 2 else 0.5
    hybrid_scores = sem_weight * semantic_scores + (1 - sem_weight) * bm25_norm

    matched_programs = _match_program(query)

    results = []
    for i, score in enumerate(hybrid_scores):
        program = _paper_cache[i].get("course_or_program", "")
        title = _paper_cache[i].get("title", "").lower()

        program_match = any(code == program for code in matched_programs)

        if score < threshold and not program_match:
            continue

        title_boost = 0.10 if fuzz.partial_ratio(query.lower(), title) >= 70 else 0.0
        program_boost = 0.25 if program_match else 0.0

        results.append((i, min(float(score) + title_boost + program_boost, 1.0)))

    ranked = sorted(results, key=lambda x: x[1], reverse=True)[:top_k]
    return [{"relevance_score": round(score, 4), **_paper_cache[i]} for i, score in ranked]