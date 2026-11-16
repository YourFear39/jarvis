"""
Search capabilities + response quality tests for Jarvis.
Tests: DuckDuckGo raw results, Groq synthesis, format/language/relevance.
Run from C:/Projects/Jarvis: python _test_search.py

NOTE: Groq free tier = 30 req/min. Test uses ~15 synthesis calls with 3s delays
      → ~5 req/min — safe margin. Do NOT shorten delays.
"""
import sys, os, time, re
sys.path.insert(0, os.path.dirname(__file__))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import config
from tools.search import web_search, DDGS_AVAILABLE
from llm.groq import GroqSynthesizer
from core.router import classify, Level

PASS = FAIL = SKIP = 0

def ok(label):
    global PASS; PASS += 1
    print(f"  [PASS] {label}")

def fail(label, got=None):
    global FAIL; FAIL += 1
    extra = f"\n         GOT: {repr(got)[:200]}" if got is not None else ""
    print(f"  [FAIL] {label}{extra}")

def skip(label, reason=""):
    global SKIP; SKIP += 1
    print(f"  [SKIP] {label}" + (f" ({reason})" if reason else ""))

def section(title):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")

def has_cyrillic(text: str) -> bool:
    return bool(re.search(r'[а-яёА-ЯЁ]', text))

# Фразы которые не должны быть в ответе
BAD_INTROS = [
    "конечно!", "отличный вопрос", "согласно поиску", "согласно данным",
    "на основании результатов", "исходя из результатов", "по результатам поиска",
    "конечно,", "разумеется,",
]
BAD_PHRASES = [
    "у меня нет информации", "я не могу найти", "недостаточно данных",
    "не могу ответить", "нет данных", "не имею доступа к",
    "к сожалению, не нашёл", "к сожалению, не нашел",
    "результаты поиска не содержат", "к сожалению, результаты",
    "не содержат прямого ответа", "к сожалению,",
]

GROQ_DELAY = 3.0   # секунд между Groq-синтезами → ~20 req/min (лимит 30)
DDG_DELAY  = 1.0   # секунд между DDG-запросами


def check_response(query: str, response: str,
                   keywords: list[str] = None, label: str = "",
                   relaxed: bool = False) -> bool:
    lbl = label or f"'{query[:50]}'"
    low = response.lower()
    passed = True

    if not response or not response.strip():
        fail(f"{lbl} → пустой ответ"); return False

    if response.startswith("Ошибка") or "ничего не найдено" in low:
        fail(f"{lbl} → ошибка поиска", response[:120]); return False

    if len(response) < 40:
        fail(f"{lbl} → слишком короткий ({len(response)} chars)", response); return False

    if len(response) > 2000:
        fail(f"{lbl} → слишком длинный ({len(response)} chars)"); passed = False

    if not has_cyrillic(response):
        fail(f"{lbl} → ответ не на русском"); return False

    bad_intro = next((b for b in BAD_INTROS if b in response[:60].lower()), None)
    if bad_intro:
        fail(f"{lbl} → плохое начало: '{bad_intro}'", response[:80]); passed = False

    bad = next((b for b in BAD_PHRASES if b in low), None)
    if bad:
        fail(f"{lbl} → фраза незнания: '{bad}'", response[:150]); passed = False

    if keywords and not relaxed:
        if not any(kw.lower() in low for kw in keywords):
            fail(f"{lbl} → нет ключевых слов {keywords}", response[:250])
            passed = False

    if passed:
        ok(f"{lbl} → OK ({len(response)} chars)")
    print(f"    ↳ {response[:200].replace(chr(10), ' ')}")
    return passed


# ===========================================================================
# 1. PREREQUISITES
# ===========================================================================
section("1. PREREQUISITES")

if DDGS_AVAILABLE:
    ok("ddgs library available")
else:
    fail("ddgs library missing — pip install ddgs")

GROQ_AVAILABLE = bool(config.GROQ_API_KEY)
if GROQ_AVAILABLE:
    ok("GROQ_API_KEY задан")
else:
    skip("Groq-синтез", "GROQ_API_KEY не задан — будет raw fallback")


# ===========================================================================
# 2. RAW DDG SEARCH — релевантность сырых результатов
# ===========================================================================
section("2. RAW DDG SEARCH — relevance check (5 queries)")

raw_tests = [
    ("кто такой Илон Маск",               ["tesla", "spacex", "маск", "musk"]),
    ("столица Бразилии",                   ["бразилиа", "brasília", "brasilia", "brazil"]),
    ("когда основали Google",              ["1998", "1997", "google"]),
    ("что такое блокчейн",                 ["блокч", "blockchain", "крипт"]),
    ("сколько планет в солнечной системе", ["8", "планет", "солнечн", "mercury"]),
]
for query, kw in raw_tests:
    result = web_search(query)
    low = result.lower()
    if "ошибка" in low[:30] or "ничего не найдено" in low:
        fail(f"DDG '{query[:40]}' → нет результатов", result[:120])
    elif any(k in low for k in kw):
        ok(f"DDG '{query[:40]}' → релевантно")
    else:
        fail(f"DDG '{query[:40]}' → нет ключевых слов {kw}", result[:200])
    time.sleep(DDG_DELAY)


# ===========================================================================
# 3. GROQ SYNTHESIS — 15 запросов, 3с между ними (≈5 req/min)
# ===========================================================================
section("3. GROQ SYNTHESIS — качество ответа (15 запросов)")

# Полный список: [query, keywords, category, relaxed]
synthesis_tests = [
    # ── Факты ────────────────────────────────────────────────────────────────
    ("кто такой Илон Маск",
     ["tesla", "spacex", "маск", "musk"], "fact", False),

    ("столица Бразилии",
     ["бразилиа", "brasília", "brasilia"], "fact", False),

    ("где находится озеро Байкал",
     ["сибирь", "байкал", "россия", "иркутск", "siberia", "russia"], "fact", False),

    # ── История ──────────────────────────────────────────────────────────────
    ("когда родился Пушкин",
     ["1799", "пушкин", "pushkin"], "history", False),

    ("кто изобрёл телефон",
     ["белл", "bell", "телефон"], "history", False),

    ("когда закончилась Вторая мировая война",
     ["1945", "война", "war", "капитул", "победа"], "history", False),

    # ── Объяснения ───────────────────────────────────────────────────────────
    ("почему небо синее",
     ["рассеив", "атмосфер", "свет", "синий", "голуб", "цвет", "rayleigh", "рэлей"], "explain", False),

    ("как работает интернет",
     ["сеть", "протокол", "tcp", "данн", "сервер", "network", "router"], "explain", False),

    ("расскажи о Python",
     ["программирован", "язык", "python", "гвидо"], "explain", False),

    # ── Сравнения ────────────────────────────────────────────────────────────
    ("что лучше Python или Java",
     ["python", "java"], "compare", False),

    ("чем отличается RAM от ROM",
     ["ram", "rom", "памят", "оперативн", "постоянн", "memory"], "compare", False),

    # ── Рекорды ──────────────────────────────────────────────────────────────
    ("какой самый высокий горный пик",
     ["эверест", "everest", "8848", "вершин", "гималаи", "himalaya"], "super", False),

    ("какая самая большая страна в мире",
     ["россия", "russia"], "super", False),

    # ── Актуальные (relaxed) ─────────────────────────────────────────────────
    ("сколько стоит iPhone 15",
     ["iphone", "цена", "стоит", "price"], "current", True),

    ("новости технологий",
     ["технолог", "ai", "компани", "новост", "tech"], "current", True),
]

synth = GroqSynthesizer()
prev_category = ""
for query, keywords, category, relaxed in synthesis_tests:
    if category != prev_category:
        cats = {
            "fact": "─── Факты",
            "history": "─── История",
            "explain": "─── Объяснения",
            "compare": "─── Сравнения",
            "super": "─── Рекорды",
            "current": "─── Актуальные (relaxed)",
        }
        print(f"\n  {cats.get(category, category)}")
        prev_category = category

    raw = web_search(query)
    time.sleep(DDG_DELAY)
    resp = synth.synthesize(query, raw)
    check_response(query, resp, keywords, relaxed=relaxed)
    time.sleep(GROQ_DELAY)


# ===========================================================================
# 4. FORMAT AUDIT — детальная инспекция 3 ответов
# ===========================================================================
section("4. FORMAT AUDIT — тон, стиль, полный ответ")

format_queries = [
    "кто такой Альберт Эйнштейн",
    "как работает квантовый компьютер",
    "что такое искусственный интеллект",
]
for query in format_queries:
    raw = web_search(query)
    time.sleep(DDG_DELAY)
    resp = synth.synthesize(query, raw)
    low = resp.lower()
    lbl = f"«{query}»"

    bad_intro = next((b for b in BAD_INTROS if b in resp[:60].lower()), None)
    if bad_intro:
        fail(f"format {lbl} → плохое начало '{bad_intro}'")
    else:
        ok(f"format {lbl} → чистое начало")

    bad = next((b for b in BAD_PHRASES if b in low), None)
    if bad:
        fail(f"format {lbl} → фраза незнания '{bad}'")
    else:
        ok(f"format {lbl} → нет отказных фраз")

    if 40 <= len(resp) <= 2000:
        ok(f"format {lbl} → длина {len(resp)} chars — норма")
    else:
        fail(f"format {lbl} → длина {len(resp)} chars вне нормы [40-2000]")

    print(f"\n  --- Полный ответ на {lbl} ---")
    print(f"  {resp}")
    print()
    time.sleep(GROQ_DELAY)


# ===========================================================================
# 5. ROUTER — все поисковые запросы → Level.SEARCH
# ===========================================================================
section("5. ROUTER — Level.SEARCH classification")

must_be_search = [
    # Факты
    "что такое блокчейн", "кто такой Илон Маск", "где находится Байкал",
    "сколько стоит iPhone 15", "новости сегодня", "курс доллара сегодня",
    "когда основали Google", "столица Бразилии",
    # Объяснения
    "расскажи о Python", "как работает интернет", "почему небо синее",
    "как установить Python", "расскажи про блокчейн",
    # Сравнения
    "что лучше Python или Java", "чем отличается RAM от ROM",
    "в чём разница между TCP и UDP",
    # Рекорды
    "расскажи о динозаврах", "какой самый высокий горный пик",
    "какая самая длинная река в мире", "какая самая большая страна",
    # История
    "когда родился Пушкин", "кто изобрёл телефон",
    "когда закончилась Вторая мировая война",
    "кто написал Войну и мир",
    "когда полетел первый человек в космос",
    # Прочее
    "погода в Питере завтра",
]
for q in must_be_search:
    level = classify(q)
    if level == Level.SEARCH:
        ok(f"SEARCH ✓  '{q[:55]}'")
    else:
        fail(f"→ AI  (должен SEARCH)  '{q[:55]}'")

must_be_ai = [
    "запомни купить молоко",
    "добавь задачу позвонить врачу",
    "напиши план обучения Python",
    "составь план путешествия",
    "придумай рецепт супа",
    "помоги написать письмо",
    "удали задачу 5",
    "прочитай файл C:\\notes.txt",
]
for q in must_be_ai:
    level = classify(q)
    if level == Level.AI:
        ok(f"AI    ✓  '{q[:55]}'")
    else:
        fail(f"→ SEARCH (должен AI)  '{q[:55]}'")


# ===========================================================================
# SUMMARY
# ===========================================================================
print(f"\n{'='*65}")
print(f"  RESULTS: {PASS} passed, {FAIL} failed, {SKIP} skipped")
print(f"  Total: {PASS+FAIL+SKIP}")
print(f"{'='*65}")
if FAIL > 0:
    sys.exit(1)
