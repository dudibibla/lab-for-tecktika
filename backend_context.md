# 🧭 תמונת מצב וקונטקסט: Backend Agent (`backend_context.md`)

קובץ זה מתעד את המצב האמיתי של קוד הבאקאנד (נכון לענף `feature/backend-agent`), מה קיים בפועל, מה חסר לחלוטין, ומה הצעדים הבאים — לעבודה מהירה ומדויקת בכל מעבר בין בראנצ'ים.

---

## 1. שורה תחתונה
* **מצב נוכחי:** כ-**25%–30%** מוכנות.
* **הקיים:** תשתית של העלאת קבצים (Upload PDF), שמירתם ב-Blob Storage, רישום ישות ב-Table Storage ודחיפה לתור Queue עבור ה-Worker, ושאילתת סטטוס ג'וב לפי ID.
* **החסר:** כל עולם ה-Agent, הצ'אט (SSE Streaming), האינטגרציה ל-Azure OpenAI ו-Azure AI Search, כלי הסוכן (Tools), אימות משתמשים (Entra ID), וטלמטריה.

---

## 2. מיפוי קבצים: קיים מול ריק (0B)

###  רכיבים קיימים ועובדים
1. **`app/api/v1/endpoints/documents.py`**:
   * נתיב `POST /api/v1/documents`: קליטת קובץ PDF, אימות גודל (עד 50MB), העלאה ל-Blob, יצירת ג'וב ב-Table ושליחת הודעה ל-Queue.
2. **`app/api/v1/endpoints/jobs.py`**:
   * נתיב `GET /api/v1/jobs/{job_id}`: שליפת ישות סטטוס מ-Table Storage (החזרת 404 אם אינו קיים).
3. **`app/services/`**:
   * `blob_service.py`: פונקציית `upload_document` להעלאה ל-`pdf-library` עם metadata של `document_id`.
   * `job_manager.py`: מיפוי סוג פעולה (`ADD`/`REPLACE`/`DELETE`), יצירת Job ID, רישום בטבלה ודחיפה לתור.
   * `queue_service.py`: שליחת `QueueMessage` לתור `index-jobs`.
   * `table_service.py`: יצירת ישות ושליפת ישות מטבלת `jobstatus`.
4. **`app/schemas/jobs.py`**: מודלי Pydantic ל-`QueueMessage`, `JobEntity`, `JobStatus`, ו-`JobOperation`.
5. **`app/azure_clients.py`**: יצירת Clients מול Blob, Queue, ו-Table מבוססי `DefaultAzureCredential`.
6. **`tests/`**: בדיקות יחידה עם Mocks ב-`test_jobs_api.py` ו-`test_documents_api.py`.

---

### ❌ רכיבים שטרם נכתבו (קבצים ריקים - 0 Bytes)
1. **עולם ה-AI והסוכן (`app/agent/`):**
   * `runner.py`: לולאת הסוכן וניהול השיחה (Reasoning & Function Calling).
   * `prompts.py`: ה-System Prompts, כללי ביסוס ומניעת הזיות/הזרקות.
   * `tools/base.py`, `search_tool.py`, `validator.py`: כלי חיפוש, מחיקה/החלפה, ומנגנון אימות אישור מפורש מהמשתמש.
2. **שירותי חיפוש ומודל (`app/services/`):**
   * `azure_openai.py`: קריאות ל-`gpt-4o` (Chat/Streaming) ו-`text-embedding-3-small`.
   * `azure_search.py`: ביצוע Hybrid Search (Semantic Reranker + BM25 + וקטור).
3. **צ'אט וממשק משתמש:**
   * `app/api/v1/endpoints/chat.py`: הזרמת תשובות ב-SSE (`/chat`).
   * `app/schemas/chat.py`, `app/schemas/tools.py`: סכמות Pydantic להודעות, אירועי סטרימינג וכלים.
4. **אבטחה וטלמטריה:**
   * `app/core/security.py`: אימות Bearer Token מול Entra ID וחילוץ זהות המשתמש.
   * `app/core/telemetry.py`: לוגים מובנים ו-App Insights.
5. **בדיקות סוכן:**
   * `tests/test_agent_tools.py`, `tests/test_search_retrieval.py`.

---

## 3. באגים ופערים קריטיים בקוד הקיים לתשומת לב
* **`requirements.txt`**: שגיאת כתיב `httpx2` במקום `httpx` (חוסם `pip install`).
* **`Dockerfile`**: נוצרה תיקייה בשם `Dockerfile` במקום קובץ טקסט.
* **CORS**: חסר `CORSMiddleware` ב-`main.py` (הפרונטאנד ייחסם מקומית ובענן).
* **משתני סביבה**: שמות המשתנים ב-`core/config.py` צריכים להתיישר ל-Bicep (`BLOB_CONTAINER_NAME`, `STORAGE_QUEUE_NAME`, וכו').
* **טיפול בכפילויות קבצים**: העלאת קובץ קיים ב-`blob_service.py` זורקת 500 במקום להחזיר 409 Conflict.
* **זהות משתמש**: כרגע מוקשח `requested_by="local-dev"`.
* **אי-עמידה בעיקרון Non-blocking (סעיף 2.3)**: הקוד הקיים ב-`documents.py` כותב ישירות ל-`documents` הראשי. לפי הארכיטקטורה, הבקאנד לעולם לא חוסם ב-confirm/upload: רק ה-Worker נוגע ב-`documents` (כולל ה-copy מ-`staging`), והבקאנד רק מאמת ומזריק הודעה לתור עם `source_blob_path`.
* **מי מחליט CREATE מול UPDATE?** ה-Agent בלבד (לפי בדיקת קיום קובץ בספרייה). הפרונטאנד אינו שולח סוג פעולה.
* **תיקון Casing קריטי:** יש לנעול על `parentDocumentId` (camelCase) ולא `ParentDocumentID`.
* **אימות Entra ID (נעול v2):** `iss = .../v2.0`, `aud = 7267f8e7-50eb-4247-88b7-da2cc3adf6f6` (או עם `api://`), `scp = access_as_user`.
* **משמעות SUCCEEDED:** הקובץ חיפוש-מוכן (Searchable לאחר סיום ה-Indexer), שמירת רשומות ל-24 שעות לפחות.

---

## 4. מפת הדרכים להמשך (ראו פירוט מלא ב-`backend_plan.md`)
1. **שלב 0:** תיקון `requirements.txt`, יצירת `Dockerfile`, הוספת CORS ויישור שמות משתני סביבה.
2. **שלב 1:** מימוש `azure_search.py` (חיפוש היברידי) ו-`azure_openai.py` (צ'אט וסטרימינג) עם Unit Tests מבוססי Mocks.
3. **שלב 2:** סכמות Pydantic לכלים ואימות אישור מפורש (`validator.py`) לפני מחיקה.
4. **שלב 3:** בניית מנוע הסוכן (`runner.py`) והנחיות ה-Prompt.
5. **שלב 4:** מימוש Endpoint צ'אט חי ב-SSE (`api/v1/endpoints/chat.py`).
6. **שלב 5:** אימות משתמשים (כולל Dev Bypass מקומי), טלמטריה וטיפול ב-Conflict.
> **מסמך היסטורי.** תמונת מצב זו נכתבה בתחילת פיתוח ה-backend וכבר אינה נכונה. אין להשתמש באחוזי המוכנות, ברשימת הקבצים החסרים או ב-`gpt-4o` שמתוארים בה. למצב הנוכחי ראו [README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md) ו-[SUMMARY.md](SUMMARY.md).
