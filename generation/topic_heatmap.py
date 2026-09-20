"""
Topic-frequency heatmap generator for Campus Brain.

Zero LLM calls — extracts topics directly from paper text using keyword
matching and question pattern detection. Fast, reliable, works offline.

Strategy:
1. Split paper into individual questions by detecting Q1/Q2/a)/b) patterns
2. Match each question against a subject-specific keyword dictionary
3. Count how many questions map to each topic
4. Return sorted topic frequency data
"""
import re
from collections import defaultdict

# ── Broad keyword → topic mapping ──────────────────────────────────────────
# Covers common university subjects. Add more as needed.
TOPIC_KEYWORDS = {
    # C / Programming
    "Pointers": ["pointer", "malloc", "calloc", "free(", "address", "dereference", "*ptr", "void *", "null pointer"],
    "Arrays": ["array", "1d array", "2d array", "matrix", "subscript", "index"],
    "Functions": ["function", "recursion", "recursive", "call stack", "return type", "parameter", "argument"],
    "Strings": ["string", "char[]", "strlen", "strcpy", "strcmp", "strcat", "gets(", "puts("],
    "Structures & Unions": ["struct", "union", "typedef", "nested struct", "member"],
    "File Handling": ["file", "fopen", "fclose", "fread", "fwrite", "fprintf", "fscanf", "fgets", "rewind"],
    "Control Flow": ["loop", "for(", "while(", "do while", "if(", "switch", "break", "continue", "goto"],
    "Data Types & Variables": ["data type", "int ", "float ", "char ", "double ", "long ", "variable", "constant", "enum"],
    "Memory Management": ["stack", "heap", "dynamic memory", "memory leak", "allocation", "deallocation"],
    # Data Structures
    "Linked Lists": ["linked list", "node", "head pointer", "singly", "doubly", "circular"],
    "Stacks": ["stack", "push(", "pop(", "peek(", "lifo", "infix", "postfix", "prefix"],
    "Queues": ["queue", "enqueue", "dequeue", "fifo", "circular queue", "priority queue", "deque"],
    "Trees": ["tree", "binary tree", "bst", "binary search tree", "inorder", "preorder", "postorder", "height", "depth", "avl", "b-tree"],
    "Graphs": ["graph", "bfs", "dfs", "breadth first", "depth first", "adjacency", "vertex", "edge", "spanning tree", "dijkstra"],
    "Sorting": ["sort", "bubble sort", "selection sort", "insertion sort", "merge sort", "quick sort", "heap sort", "time complexity"],
    "Searching": ["search", "linear search", "binary search", "hashing", "hash table", "collision"],
    # OS
    "Processes": ["process", "pcb", "context switch", "fork(", "thread", "multithreading"],
    "Scheduling": ["scheduling", "fcfs", "sjf", "round robin", "priority scheduling", "gantt"],
    "Memory Management (OS)": ["paging", "segmentation", "virtual memory", "page fault", "tlb", "frame", "page table"],
    "Deadlock": ["deadlock", "banker", "resource allocation", "mutual exclusion", "hold and wait", "circular wait"],
    "Synchronization": ["semaphore", "mutex", "critical section", "race condition", "monitor", "producer consumer"],
    # DBMS
    "SQL": ["select ", "insert ", "update ", "delete ", "join", "where ", "group by", "having", "query"],
    "Normalization": ["normalization", "1nf", "2nf", "3nf", "bcnf", "functional dependency", "candidate key", "primary key"],
    "Transactions": ["transaction", "acid", "commit", "rollback", "concurrency", "serializability"],
    "ER Model": ["er diagram", "entity", "relationship", "cardinality", "attribute", "weak entity"],
    # Networks
    "OSI Model": ["osi", "layer", "physical layer", "data link", "network layer", "transport layer", "session", "presentation"],
    "TCP/IP": ["tcp", "ip address", "udp", "socket", "three-way handshake", "http", "dns", "ftp", "smtp"],
    "Routing": ["routing", "ospf", "rip", "bgp", "router", "forwarding table", "subnet"],
    # Math / Theory
    "Complexity": ["complexity", "big o", "o(n)", "o(log", "time complexity", "space complexity", "np", "np-complete"],
    "Automata": ["automata", "dfa", "nfa", "regular expression", "grammar", "turing machine", "pushdown"],
    "Probability & Stats": ["probability", "distribution", "mean", "variance", "standard deviation", "bayes"],
}


def _split_into_questions(text: str) -> list:
    """Split paper text into individual question chunks."""
    # Match Q1, Q.1, 1., 1), a), a., (a), (1) etc.
    pattern = re.compile(
        r"(?:^|\n)\s*(?:Q\.?\s*\d+|(?:\d+|[a-zA-Z])[.)]\s+|\([a-zA-Z\d]\)\s+)",
        re.MULTILINE,
    )
    splits = [m.start() for m in pattern.finditer(text)]
    if not splits:
        # Fallback: split by sentences
        return [s.strip() for s in re.split(r"[.?!]\s+", text) if len(s.strip()) > 20]

    chunks = []
    for i, start in enumerate(splits):
        end = splits[i + 1] if i + 1 < len(splits) else len(text)
        chunks.append(text[start:end].strip())
    return chunks


def _score_question(question_text: str) -> dict:
    """Return {topic: score} for a single question based on keyword hits."""
    lower = question_text.lower()
    scores = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw.lower() in lower)
        if hits > 0:
            scores[topic] = hits
    return scores


def generate_topic_heatmap(paper_text: str, cached_summary: str = "") -> dict:
    """Build topic frequency data purely from paper text — no LLM calls.

    Returns {"topics": [{"topic", "questions", "marks", "description"}, ...]}
    Raises ValueError if text is too sparse.
    """
    if not paper_text or len(paper_text.strip()) < 80:
        raise ValueError("Not enough text to analyse topics.")

    questions = _split_into_questions(paper_text)
    if not questions:
        raise ValueError("Could not detect individual questions in this paper.")

    topic_counts = defaultdict(int)
    topic_marks = defaultdict(int)

    # Look for mark annotations: (5 marks), [10M], 5 marks, etc.
    marks_pattern = re.compile(r"\[?(\d+)\s*(?:marks?|M)\]?", re.IGNORECASE)

    for q in questions:
        scores = _score_question(q)
        if not scores:
            continue
        best_topic = max(scores, key=scores.get)
        topic_counts[best_topic] += 1
        # Try to extract marks from this question
        m = marks_pattern.search(q)
        if m:
            topic_marks[best_topic] += int(m.group(1))

    if not topic_counts:
        # Fallback: count keyword frequency across the whole text
        lower = paper_text.lower()
        for topic, keywords in TOPIC_KEYWORDS.items():
            hits = sum(lower.count(kw.lower()) for kw in keywords)
            if hits >= 2:
                topic_counts[topic] = hits

    if not topic_counts:
        raise ValueError(
            "No recognisable topics found in this paper. "
            "The paper may be in an unusual format or language."
        )

    # Sort by frequency, take top 8
    sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    topics = []
    for name, count in sorted_topics:
        desc_keywords = TOPIC_KEYWORDS.get(name, [])
        desc = ", ".join(desc_keywords[:3]) if desc_keywords else name
        topics.append({
            "topic": name,
            "questions": count,
            "marks": topic_marks.get(name, 0),
            "description": desc,
        })

    return {"topics": topics}
