"""
Система долговременной памяти Джарвиса.
ChromaDB — для семантического поиска похожих разговоров.
SQLite — уже используется для заметок/задач в tools/notes.py.
"""

import hashlib
from datetime import datetime

import config

try:
    import chromadb
    from chromadb.utils import embedding_functions
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False


class JarvisMemory:
    """
    Управляет долговременной памятью Джарвиса.
    Сохраняет разговоры и умеет находить похожие по смыслу.
    """

    def __init__(self):
        self._client = None
        self._collection = None

        if not CHROMA_AVAILABLE:
            print("[Память] ChromaDB не установлена — долговременная память отключена.")
            return

        try:
            self._client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))

            # Используем встроенные эмбеддинги (не требуют API-ключей)
            ef = embedding_functions.DefaultEmbeddingFunction()

            self._collection = self._client.get_or_create_collection(
                name="jarvis_memory",
                embedding_function=ef,
            )
        except Exception as e:
            print(f"[Память] Ошибка инициализации ChromaDB: {e}")
            self._collection = None

    @property
    def is_available(self) -> bool:
        return self._collection is not None

    def save_exchange(self, user_message: str, assistant_response: str) -> None:
        """
        Сохраняет пару (вопрос пользователя → ответ ассистента) в память.
        Вызывается после каждого успешного диалога.
        """
        if not self.is_available:
            return

        try:
            timestamp = datetime.now().isoformat()

            # ID только по содержимому сообщения — upsert предотвращает дубли
            uid = hashlib.md5(user_message.encode()).hexdigest()

            combined = f"Пользователь: {user_message}\nДжарвис: {assistant_response}"

            # upsert: если такой вопрос уже был — обновляем ответ, не дублируем
            self._collection.upsert(
                documents=[combined],
                metadatas=[{
                    "user_msg": user_message[:500],
                    "timestamp": timestamp,
                    "type": "exchange",
                }],
                ids=[uid],
            )
        except Exception as e:
            print(f"[Память] Ошибка сохранения: {e}")

    def get_relevant_memories(self, query: str) -> list[str]:
        """
        Находит воспоминания, семантически похожие на текущий запрос.

        :param query: текущее сообщение пользователя
        :return: список строк с релевантными воспоминаниями
        """
        if not self.is_available:
            return []

        try:
            count = self._collection.count()
            if count == 0:
                return []

            n_results = min(config.MEMORY_TOP_K, count)
            results = self._collection.query(
                query_texts=[query],
                n_results=n_results,
            )

            documents = results.get("documents", [[]])[0]
            return [doc for doc in documents if doc]

        except Exception as e:
            print(f"[Память] Ошибка поиска: {e}")
            return []

    def get_memory_stats(self) -> str:
        """Возвращает статистику памяти для команды /memory."""
        if not self.is_available:
            return "Долговременная память недоступна (ChromaDB не установлена)."

        try:
            count = self._collection.count()
            return f"Сохранено разговоров в памяти: {count}"
        except Exception as e:
            return f"Ошибка получения статистики: {e}"
