# 📋 תוכנית עבודה לפיתוח ה-Backend (`backend_plan.md`)
> **סטטוס:** תוכנית פעולה מודולרית ומנותקת מתלות ענן (Pure Code & Mocked Unit Tests)  
> **בסיס תשתיתי:** נשען על ברירות המחדל הקיימות ב-`main` (Bicep IaC) וחוזי ה-Worker המוגדרים.

---

## 🎯 מטרת העל
הקמת שירות ה-**Backend Agent** (FastAPI) באופן מלא, נקי ועצמאי, המאפשר:
1. מענה קוגניטיבי על קובצי PDF (RAG היברידי מבוסס Azure AI Search + Azure OpenAI).
2. ניהול שיחה רציפה והזרמת תשובות בזמן אמת (SSE Streaming).
3. הפעלת כלי סוכן (Agent Tools) מאומתים למחיקה/החלפה עם דרישת אישור מפורש (Explicit Confirmation).
4. **אפס תלות בתשתיות ענן פעילות בזמן הפיתוח** — כל הרכיבים נבדקים ב-100% כיסוי בדיקות מקומיות באמצעות Mocks.

---

## 🏗️ ארכיטקטורת הייחוס וחוזי המערכת (Context & Contracts)
הבאקאנד פועל בסנכרון מלא מול התשתית שהוגדרה ב-`infrastructure/` ומול ה-`worker/`:

* **משתני סביבה תואמי Bicep:**
  * `BLOB_CONTAINER_NAME` (ברירת מחדל: `pdf-library`)
  * `STORAGE_QUEUE_NAME` (ברירת מחדל: `index-jobs`)
  * `JOB_STATUS_TABLE_NAME` (ברירת מחדל: `jobstatus`)
  * `AZURE_SEARCH_ENDPOINT`, `AZURE_OPENAI_ENDPOINT`
  * `OPENAI_CHAT_DEPLOYMENT` (`gpt-4o`), `OPENAI_EMBEDDING_DEPLOYMENT` (`text-embedding-3-small`)
* **חוזה הודעות מול ה-Worker (`index-jobs`):**
  * `job_id`: מחרוזת UUID ייחודית.
  * `event_type`: אחד מתוך `CREATE`, `UPDATE`, `DELETE`.
  * `blob_name`: שם הקובץ ב-Blob Storage.
  * `document_id`: מזהה מסמך יציב — הקפדה על camelCase: `parentDocumentId` (לא `ParentDocumentID`).
  * `etag`: ETag של הקובץ לבדיקת אידמפוטנטיות.
  * `source_blob_path`: נתיב הקובץ ב-`staging` (אופציונלי, לפעולות `CREATE`/`UPDATE` בהעלאה).

* **סכמת האינדקס ב-AI Search (`pdf-chunks-index`):**
  * שדות: `id`, `parentDocumentId`, `fileName`, `page`, `sourceUrl`, `content`, `text_vector` (1536d).

* ⚡ **עקרון הפרדה קריטי — מי נוגע ב-documents? (סעיף 2.3 — "הצ'אט לא נחסם"):**
  * **רק ה-Worker נוגע ב-`documents` (כולל ה-copy מ-`staging`):** הבקאנד לעולם לא מבצע פעולה חוסמת/כותבת בתוך בקשת ה-confirm או ה-upload עצמה.
  * הבקאנד רק מאמת ומזריק הודעה לתור (`index-jobs`) עם `source_blob_path` — כדי לעמוד בדרישת "הצ'אט לא נחסם" (2.3) בלי יוצא מן הכלל. כל פעולות ה-copy, המחיקה והעדכון מתבצעות אסינכרונית ברקע ע"י ה-Worker בלבד.
  * **מי מחליט CREATE מול UPDATE? ה-Agent בלבד!** הפרונטאנד אינו שולח סוג פעולה אלא רק מצרף קובץ. כלי הסוכן בבקאנד בודק האם הקובץ קיים, ורק אם קיים דורש אישור מפורש להחלפה ומגדיר `UPDATE`.
  * **משמעות סטטוס `SUCCEEDED`:** הקובץ אינו רק מועתק אלא נהיה חיפוש-מוכן (Searchable לאחר סיום ה-Indexer).
  * **שימור רשומות משימה:** רשומות ב-`jobstatus` נשמרות לפחות 24 שעות.

---

## 📋 Breakdown שלבי הפיתוח (Phased Breakdown)

### שלב 0: יישור קו תשתיתי מקומי ותיקוני בסיס (Quickfixes & Baseline)
* [ ] **0.1 תיקון תלויות (`requirements.txt`):**
  * תיקון הבאג הקריטי: החלפת `httpx2` ב-`httpx`.
  * הוספת חבילות ה-AI הנדרשות: `openai>=1.30.0` ו-`azure-search-documents>=11.4.0`.
* [ ] **0.2 יצירת `Dockerfile` תקין:**
  * מחיקת תיקיית `Dockerfile` השגויה ויצירת קובץ `Dockerfile` תקין (מבוסס `python:3.11-slim`, port 8000, הרצת Uvicorn).
* [ ] **0.3 הוספת תמיכת CORS (`main.py`):**
  * הגדרת `CORSMiddleware` ב-FastAPI לתמיכה ב-`localhost:5173` (פיתוח מקומי) וב-Azure Static Web Apps.
* [ ] **0.4 סנכרון משתני סביבה (`core/config.py`):**
  * יישור שמות השדות ב-Settings לשמות המדויקים שמוזרקים מקובץ ה-Bicep (`BLOB_CONTAINER_NAME`, `STORAGE_QUEUE_NAME`, וכו').

---

### שלב 1: שירותי Retrieval ו-AI עם שכבת Mocking (Retrieval & AI Services)
* [ ] **1.1 שירות החיפוש באינדקס (`services/azure_search.py`):**
  * מימוש חיפוש היברידי (Hybrid Search) המשלב שאילתת טקסט מלא (BM25) יחד עם חיפוש וקטורי (`text_vector`).
  * תמיכה ב-Semantic Reranker ובסינון לפי `fileName` או `parentDocumentId`.
  * חילוץ תוצאות מובנה הכולל: `content`, `fileName`, `page`, וציון רלוונטיות.
* [ ] **1.2 שירות Azure OpenAI (`services/azure_openai.py`):**
  * יצירת Client מול מודל `gpt-4o` עם תמיכה ב-Chat Completions וב-Tool Calling (Function Calling).
  * יצירת Client מול `text-embedding-3-small` לייצור וקטורים (1536 ממדים) עבור שאילתות החיפוש.
  * מימוש מנגנון Streaming (Generators) להזרמת טוקנים חיים.
* [ ] **1.3 בדיקות שירותי ה-AI (`tests/test_search_retrieval.py`):**
  * כתיבת בדיקות יחידה מלאות עם Mocks לקריאות החיפוש וה-Embeddings (בדיקת חילוץ תוצאות ומקורות ללא רשת).

---

### שלב 2: סכמות וכלי סוכן מאומתים (Agent Tools & Confirmation System)
* [ ] **2.1 סכמות Pydantic לכלים (`schemas/tools.py`):**
  * `SearchDocumentsInput`: פרמטרי שאילתה, סינון לפי קובץ, ומספר תוצאות מקסימלי.
  * `DeleteDocumentInput`: שם הקובץ ומזהה הקובץ למחיקה.
  * `ReplaceDocumentInput`: שם הקובץ ומזהה הקובץ להחלפה.
  * `ActionConfirmation`: מודל ייעודי להחזרת בקשת אישור מפורשת מהמשתמש.
* [ ] **2.2 מימוש כלי הסוכן (`agent/tools/`):**
  * `search_tool.py`: עטיפת שירות החיפוש והחזרת ציטוטים מובנים לסוכן.
  * `validator.py`: **מנגנון הגנה קריטי** — חסימת ביצוע של פעולת `DELETE` או `REPLACE` ללא אישור מפורש שנוקב במפורש בשם הקובץ המדויק.
  * `document_tool.py`: הזרקת משימה לא חוסמת ל-`job_manager.py` (יצירת Job ב-Queue ועדכון ב-Table בלבד). **אין נגיעה ישירה ב-documents או ב-Blob הראשי** — הכל מועבר לטיפול ה-Worker ברקע.
* [ ] **2.3 בדיקות כלי סוכן (`tests/test_agent_tools.py`):**
  * בדיקה שהכלי מסרב למחוק מסמך ללא אישור.
  * בדיקה שאישור שגוי/חלקי נדחה.
  * בדיקה שאישור תקין מייצר משימת `DELETE` ב-Table וב-Queue.

---

### שלב 3: מנוע הסוכן והנחיות מערכת (Agent Runner & Prompt Engine)
* [ ] **3.1 הגדרת הנחיות הסוכן (`agent/prompts.py`):**
  * ניסוח System Prompt קפדני:
    * חובת ביסוס תשובות אך ורק על המידע שנשלף מהאינדקס.
    * ציטוט מדויק של מקורות (שם מסמך ועמוד).
    * מניעת הטיות, הזיות ו-Prompt Injections מתוך תוכן ה-PDF.
    * דרישת אישור מפורש מול המשתמש לפני כל פעולת שינוי ספרייה.
* [ ] **3.2 לולאת הסוכן (`agent/runner.py`):**
  * מימוש לולאת הסוכן מבוססת Function Calling:
    1. קבלת הודעת משתמש והיסטוריית שיחה.
    2. שליחה ל-LLM לקבלת תשובה או החלטה על הפעלת כלי.
    3. הרצת הכלי הרלוונטי והזנת התוצאה חזרה לשיחה.
    4. החזרת תשובה סופית או בקשת אישור לפרונטאנד.
* [ ] **3.3 בדיקות מנוע הסוכן (`tests/test_agent_runner.py`):**
  * סימולציה מלאה של שיחת RAG רב-שלבית ובדיקת ניתוב הכלים באמצעות Mocks.

---

### שלב 4: ממשק הצ'אט והזרמת תשובות בזמן אמת (Chat API & SSE Streaming)
* [ ] **4.1 סכמות API לצ'אט (`schemas/chat.py`):**
  * `ChatMessage`, `ChatRequest`, `ChatResponseStreamEvent`, `CitationSource`.
* [ ] **4.2 מימוש Endpoint צ'אט (`api/v1/endpoints/chat.py`):**
  * תמיכה ב-Server-Sent Events (SSE) בפורמט `text/event-stream`.
  * הזרמת טוקנים חיים למשתמש, אירועי ביניים (כגון "מחפש במסמכים..."), ומערך מקורות/ציטוטים בסיום התשובה.
* [ ] **4.3 רישום ב-Router הראשי (`api/v1/router.py`):**
  * שילוב נתיב `/chat` תחת ה-API המרכזי.
* [ ] **4.4 בדיקות ממשק הצ'אט (`tests/test_chat_api.py`):**
  * בדיקת קבלת זרם SSE תקין, שמירה על חוזה הנתונים וטיפול בשגיאות.

---

### שלב 5: אבטחה, עמידות וטלמטריה (Security, Resilience & Observability)
* [ ] **5.1 מודול אימות JWT מול Entra ID (`core/security.py`):**
  * אימות Bearer Token (בדיקת חתימת JWT מול JWKS של Microsoft, ללא Easy Auth).
  * ערכים נעולים סופית:
    * `iss`: `https://login.microsoftonline.com/6fc8a795-8bcb-4e52-8b36-41c1971e6816/v2.0`
    * `aud`: תמיכה בשתי הצורות: `7267f8e7-50eb-4247-88b7-da2cc3adf6f6` ו-`api://7267f8e7-50eb-4247-88b7-da2cc3adf6f6`
    * `scp`: `access_as_user`
    * `JWKS`: `https://login.microsoftonline.com/6fc8a795-8bcb-4e52-8b36-41c1971e6816/discovery/v2.0/keys`
  * תמיכה ב-**Local Dev Mode**: כאשר משתני ה-Entra ריקים או בסביבת local, עקיפה מאובטחת וחילוץ משתמש ברירת מחדל כדי לא לחסום פיתוח מקומי.
  * חילוץ זהות המשתמש (`oid` / `upn` / `email`) והזרקתו לשדה `requested_by` ב-Jobs.
* [ ] **5.2 שיפור עמידות ב-`documents.py`:**
  * זיהוי קובץ קיים והחזרת שגיאת `HTTP 409 Conflict` ברורה במקום שגיאת 500 בלתי צפויה.
* [ ] **5.3 טלמטריה ולוגים מובנים (`core/telemetry.py`):**
  * הגדרת לוגר מרכזי מובנה (Structured Logging) עם Correlation ID למעקב אחרי בקשות.

---

## 🧪 אסטרטגיית אימות ובדיקות (Verification Plan)
כל שורת קוד שתיכתב בתוכנית זו תיבדק ותאושר מקומית ללא עלות וללא צורך ברשת:
1. **הרצת בדיקות מקומיות:**
   ```bash
   pytest backend/tests -v
   ```
2. **אימות חוזים מול ה-Worker:**
   * וידוא שהודעות ה-Queue וה-Table המיוצרות ב-`job_manager.py` תואמות 1-ל-1 את מודלי ה-Worker ב-`feature/worker-pipeline`.
3. **בדיקת בריאות כוללת של השרת:**
   * הרצת FastAPI ב-Uvicorn מקומית ווידוא שכל ה-Endpoints עולים ללא חריגות.
> **מסמך היסטורי.** זו תכנית טרום-מימוש; תיבות לא מסומנות אינן backlog נוכחי. ה-backend, הסוכן, האימות וה-SSE ממומשים. למצב העדכני ראו [README.md](README.md) ו-[SUMMARY.md](SUMMARY.md).
