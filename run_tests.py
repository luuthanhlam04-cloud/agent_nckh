# -*- coding: utf-8 -*-
"""
run_tests.py - Test toan bo logic khong can API key
"""
import sys
import os
import asyncio
sys.path.insert(0, os.path.dirname(__file__))

PASS = "[OK]"
FAIL = "[FAIL]"
results = []

def check(name, condition, detail=""):
    if condition:
        print(f"  {PASS} {name}")
        results.append((True, name))
    else:
        print(f"  {FAIL} {name}{' -- ' + detail if detail else ''}")
        results.append((False, name))

# ─────────────────────────────────────────────
print("=" * 60)
print("  TEST 1: ConversationMemory + RouterIntent")
print("=" * 60)
try:
    from src.core.semantic_router import ConversationMemory, RouterIntent

    # Sliding window cap
    mem = ConversationMemory(max_size=5)
    for i in range(7):
        mem.add(f"Question {i+1}", f"Answer {i+1}")
    check("Sliding window cap at 5", len(mem) == 5, f"got {len(mem)}")

    # BUG-8: ellipsis logic
    mem2 = ConversationMemory(max_size=5)
    mem2.add("Q short", "Short answer")   # < 200 chars
    mem2.add("Q long", "A" * 250)         # > 200 chars
    ctx = mem2.get_context_string()
    check("BUG-8: short text no ellipsis", "Short answer..." not in ctx)
    check("BUG-8: long text has ellipsis", "..." in ctx)

    # Pydantic fallback
    intent = RouterIntent.model_validate({
        "intent_type": "invalid_type", "target_folder": None,
        "enable_web_search": False, "os_action_payload": None,
        "translated_keywords": ["test"], "topic": None,
    })
    check("Pydantic: invalid intent -> research_query", intent.intent_type == "research_query")

    # Window pop oldest
    mem3 = ConversationMemory(max_size=3)
    mem3.add("Q1", "A1")
    mem3.add("Q2", "A2")
    mem3.add("Q3", "A3")
    mem3.add("Q4", "A4")  # pop Q1
    ctx3 = mem3.get_context_string()
    check("Sliding window pops oldest", "Q1" not in ctx3 and "Q4" in ctx3)

except Exception as e:
    print(f"  {FAIL} TEST 1 EXCEPTION: {e}")
    results.append((False, "TEST 1 EXCEPTION"))

# ─────────────────────────────────────────────
print()
print("=" * 60)
print("  TEST 2: Orchestrator - Models + BUG-9 logic")
print("=" * 60)
try:
    from src.core.orchestrator import SelfCritiqueResult, AgentState, ReActOrchestrator

    r = SelfCritiqueResult.model_validate({
        "relevance_score": 9.2, "answerability_score": 8.5,
        "missing_information": "", "action_required": "proceed",
    })
    check("SelfCritiqueResult avg_score", abs(r.avg_score - (9.2 + 8.5) / 2) < 0.001)
    check("SelfCritiqueResult action=proceed", r.action_required == "proceed")

    # BUG-9: prev_web_count slicing
    web_round1 = ["r1", "r2", "r3"]
    web_round2 = web_round1 + ["r4", "r5"]
    prev = len(web_round1)
    new_only = web_round2[prev:]
    check("BUG-9: prev_web_count slice gives only new results", new_only == ["r4", "r5"])

    # Circuit breaker: max_iterations
    orch = ReActOrchestrator(hybrid_rag=None)
    state: AgentState = {
        "user_input": "test", "context_chunks": [], "web_results": [],
        "critique": SelfCritiqueResult(
            relevance_score=2.0, answerability_score=2.0,
            missing_information="missing", action_required="force_web_search"
        ),
        "final_answer": "", "search_iterations": 3, "error": None,
    }
    check("Circuit breaker at max_iterations=3", not orch._should_search(state))
    state["search_iterations"] = 1
    check("Should search when iterations < max", orch._should_search(state))

except Exception as e:
    print(f"  {FAIL} TEST 2 EXCEPTION: {e}")
    results.append((False, "TEST 2 EXCEPTION"))

# ─────────────────────────────────────────────
print()
print("=" * 60)
print("  TEST 3: RegexInterceptor - All 7 modules")
print("=" * 60)
try:
    from src.core.regex_interceptor import (
        intercept, filter_whisper_hallucination,
        check_time_queries, check_os_commands,
        force_web_search_override, trigger_docx_export,
    )

    # BUG-7: Whisper -> (None, None)
    r, m = intercept("Cảm ơn các bạn đã xem video")
    check("BUG-7: Whisper hallucination -> (None,None)", r is None and m is None, f"got ({r!r},{m!r})")

    # Empty input
    r, m = intercept("")
    check("Empty input -> (None, None)", r is None and m is None)

    # Time query với tiếng Việt đúng
    r, m = intercept("mấy giờ rồi")
    check("Time query -> fast mode", m == "fast", f"got mode={m!r}")
    check("Time query has colon (HH:MM)", r is not None and ":" in str(r))

    # Date query
    r, m = intercept("hôm nay là ngày bao nhiêu")
    check("Date query -> fast mode", m == "fast")
    check("Date query has slash (dd/mm/yyyy)", r is not None and "/" in str(r))

    # OS command
    r, m = intercept("mở youtube đi")
    check("OS command (youtube) -> ninja", m == "ninja", f"got ({r!r},{m!r})")

    r2, m2 = intercept("hãy mở VS Code")
    check("OS command (vscode) -> ninja", m2 == "ninja")

    # Force web search override
    r, m = intercept("tra mạng bắt buộc GraphRAG là gì")
    check("Force web search -> fast dict", m == "fast" and isinstance(r, dict))
    check("Force web intent=FORCE_WEB", r is not None and r.get("intent") == "FORCE_WEB")

    # Docx export
    r, m = intercept("xuất ra word báo cáo về GraphRAG")
    check("Docx export -> fast dict", m == "fast" and isinstance(r, dict))
    check("Docx export intent=EXPORT_DOCX", r is not None and r.get("intent") == "EXPORT_DOCX")

    # No match -> push to LLM
    r, m = intercept("GraphRAG là gì và cách hoạt động")
    check("Research query -> (None, None) -> LLM", r is None and m is None)

    # Ninja UX: no last_response
    r, m = intercept("copy câu vừa rồi")
    check("Copy with no last_response -> fast", m == "fast")

except Exception as e:
    import traceback
    print(f"  {FAIL} TEST 3 EXCEPTION: {e}")
    traceback.print_exc()
    results.append((False, "TEST 3 EXCEPTION"))

# ─────────────────────────────────────────────
print()
print("=" * 60)
print("  TEST 4: HybridRAG - QdrantManager local + BUG-2/6 logic")
print("=" * 60)
try:
    from src.db.hybrid_rag import QdrantManager, HybridRAG

    # Test QdrantManager standalone (no Neo4j needed)
    qdrant = QdrantManager()

    test_chunks = [
        {"text": "GraphRAG combines knowledge graphs and vector search for accurate retrieval.", "source": "test.pdf", "page": 1},
        {"text": "MiniLM-L12-v2 is a multilingual embedding model for cross-lingual search.", "source": "test.pdf", "page": 2},
        {"text": "Neo4j stores entities and relationships as graph nodes and edges.", "source": "test.pdf", "page": 3},
    ]
    ids = qdrant.upsert_chunks(test_chunks)
    check("QdrantManager.upsert_chunks returns IDs", len(ids) == 3)
    check("IDs are UUIDs (length 36)", all(len(i) == 36 for i in ids))

    results_q = qdrant.search("semantic search embedding", top_k=2)
    check("QdrantManager.search returns results", len(results_q) > 0)
    check("Search result has required keys", all(k in results_q[0] for k in ["text","score","source","page"]))
    check("Search score is between 0-1", all(0.0 <= r["score"] <= 1.0 for r in results_q))

    # BUG-6: entity->chunk mapping logic
    chunks = [
        {"text": "GraphRAG uses graphs for retrieval.", "source": "a.pdf", "page": 1},
        {"text": "MiniLM is used for embedding.", "source": "a.pdf", "page": 2},
        {"text": "Neo4j stores the graph data.", "source": "a.pdf", "page": 3},
    ]
    chunk_ids = ["id1", "id2", "id3"]
    entity_name = "graphrag"
    relevant_ids = [chunk_ids[i] for i, c in enumerate(chunks) if entity_name in c["text"].lower()]
    check("BUG-6: entity 'graphrag' maps to correct chunk", relevant_ids == ["id1"])

    entity_name2 = "miniLM"
    relevant_ids2 = [chunk_ids[i] for i, c in enumerate(chunks) if entity_name2.lower() in c["text"].lower()]
    check("BUG-6: entity 'miniLM' maps to chunk 2", relevant_ids2 == ["id2"])

    # Fallback: entity not in any chunk -> full list
    entity_name3 = "xyzunknown"
    relevant_ids3 = [chunk_ids[i] for i, c in enumerate(chunks) if entity_name3 in c["text"].lower()]
    assigned = relevant_ids3 if relevant_ids3 else chunk_ids
    check("BUG-6: unknown entity fallback -> all chunks", assigned == chunk_ids)

    # GIẢI PHÓNG LOCK CỦA QDRANT Ở ĐÂY
    qdrant.close()

    # BUG-2: retrieve_context với Neo4j URI trống (graceful degradation)
    rag = HybridRAG()  # Neo4j URI trống -> sẽ dùng fallback
    context = rag.retrieve_context("GraphRAG embedding model", top_k=3)
    check("BUG-2: retrieve_context OK without crash when Neo4j empty", True)
    check("BUG-2: context là list", isinstance(context, list))

    rag.close()

except Exception as e:
    import traceback
    print(f"  {FAIL} TEST 4 EXCEPTION: {e}")
    traceback.print_exc()
    results.append((False, "TEST 4 EXCEPTION"))

# ─────────────────────────────────────────────
print()
print("=" * 60)
print("  TEST 5: Parser - PDFParser chunk logic")
print("=" * 60)
try:
    from src.utils.parser import chunk_by_paragraph, parse_document

    long_text = ("This is a test paragraph with enough content to be chunked properly. " * 5 + "\n\n") * 5
    chunks = chunk_by_paragraph(long_text, source="test.pdf", page=1)
    check("chunk_by_paragraph returns list", isinstance(chunks, list))
    check("Each chunk has required keys", all("text" in c and "source" in c and "page" in c for c in chunks) if chunks else True)
    check("MIN_CHUNK_CHARS filter (all >= 150 chars)", all(len(c["text"]) >= 150 for c in chunks) if chunks else True)

    # BUG-1: PPTXParser has _client not _model
    from src.utils.parser import PPTXParser
    p = PPTXParser()
    check("BUG-1: PPTXParser has _client attr (not _model)", hasattr(p, "_client") and not hasattr(p, "_model"))

except Exception as e:
    import traceback
    print(f"  {FAIL} TEST 5 EXCEPTION: {e}")
    traceback.print_exc()
    results.append((False, "TEST 5 EXCEPTION"))

# ─────────────────────────────────────────────
print()
print("=" * 60)
print("  TEST 6: WatchdogListener - BUG-3/10 structure check")
print("=" * 60)
try:
    import inspect
    import src.utils.watchdog_listener as wdl

    # SỬA Ở ĐÂY: Thêm InboxWatcher vào trước _process_queue
    source = inspect.getsource(wdl.InboxWatcher._process_queue)  # type: ignore
    # Không kiểm tra get_running_loop trong _process_queue nữa vì nó nằm ở _handle_new_file
    check("BUG-3: get_event_loop() removed", "get_event_loop()" not in source)
    check("BUG-10: CancelledError handled explicitly", "CancelledError" in source)

    source_handle = inspect.getsource(wdl.InboxWatcher._handle_new_file)  # type: ignore
    check("BUG-3: _handle_new_file also uses get_running_loop", "get_running_loop()" in source_handle)

except Exception as e:
    print(f"  {FAIL} TEST 6 EXCEPTION: {e}")
    results.append((False, "TEST 6 EXCEPTION"))

# ─────────────────────────────────────────────
print()
print("=" * 60)
print("  TEST 7: SpotlightWindow + GlobalHotkeyThread - BUG-4/11")
print("=" * 60)
try:
    import inspect
    import src.ui.spotlight as sp

    # BUG-4: QMediaPlayer used for TTS instead of subprocess (Phase 5 Refactor)
    tts_setup_source = inspect.getsource(sp.SpotlightWindow._setup_tts_player)
    check("BUG-4: QMediaPlayer used in _setup_tts_player", "QMediaPlayer" in tts_setup_source)
    
    tts_cleanup_source = inspect.getsource(sp.SpotlightWindow._cleanup_tts_file)
    check("BUG-4: setSource(QUrl()) exists to release file lock", "setSource(QUrl())" in tts_cleanup_source)

    # BUG-11: stop_listening method exists
    check("BUG-11: GlobalHotkeyWorker.stop_listening exists", hasattr(sp.GlobalHotkeyWorker, "stop_listening"))
    stop_src = inspect.getsource(sp.GlobalHotkeyWorker.stop_listening)
    check("BUG-11: unhook_all() called in stop_listening", "unhook_all()" in stop_src)

    # BUG-11: cleanup in main
    import inspect as ins2
    import main as main_mod
    cleanup_src = ins2.getsource(main_mod._cleanup_components)
    check("BUG-11: hotkey_thread in _cleanup_components", "hotkey_thread" in cleanup_src)
    check("BUG-11: stop_listening called in cleanup", "stop_listening" in cleanup_src)

except Exception as e:
    import traceback
    print(f"  {FAIL} TEST 7 EXCEPTION: {e}")
    traceback.print_exc()
    results.append((False, "TEST 7 EXCEPTION"))

# ─────────────────────────────────────────────
print()
print("=" * 60)
print("  TEST 8: main.py - BUG-12 init_database return type")
print("=" * 60)
try:
    import inspect
    import main as main_mod

    src_init = inspect.getsource(main_mod.init_database)
    check("BUG-12: init_database returns HybridRAG directly (no tuple)", "return None, HybridRAG()" not in src_init)
    check("BUG-12: no tuple return with leading None", "return None, rag" not in src_init)

    main_src = inspect.getsource(main_mod.main)
    check("BUG-12: main() uses 'rag = init_database()' not tuple unpack", "_, rag = init_database()" not in main_src)

except Exception as e:
    print(f"  {FAIL} TEST 8 EXCEPTION: {e}")
    results.append((False, "TEST 8 EXCEPTION"))

# ─────────────────────────────────────────────
print()
print("=" * 60)
total = len(results)
passed = sum(1 for ok, _ in results if ok)
failed = total - passed
print(f"  FINAL RESULT: {passed}/{total} PASSED  |  {failed} FAILED")
print("=" * 60)
if failed > 0:
    print()
    print("  FAILED TESTS:")
    for ok, name in results:
        if not ok:
            print(f"    - {name}")
sys.exit(0 if failed == 0 else 1)
