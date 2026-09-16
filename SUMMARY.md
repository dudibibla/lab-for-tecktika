# סיכום התפתחות הפרויקט

מסמך זה מסכם את 153 הקומיטים שנוצרו בין 31 באוגוסט ל-16 בספטמבר 2026 ואת הבעיות המרכזיות שנפתרו בדרך.

## התוצאה הנוכחית

המערכת פועלת מקצה לקצה בענן: משתמש נכנס עם Entra ID, מעלה PDF, ה-Worker מחלץ ומאנדקס אותו, והצ'אט עונה מתוך המסמכים עם מקורות. אפשר להחליף ולמחוק קבצים באישור מפורש ולעקוב אחר סטטוס העבודה.

הפרויקט עבר מהמאגר הישן למאגר `dudibibla/lab-for-tecktika`. משאבי Azure אינם “שייכים לריפו”; הקישור לריפו נמצא ב-workflows, ב-GHCR וב-secrets/variables של GitHub. לאחר המעבר עודכנו image namespace, הרשאות ופריסות בלי להחליף את Storage.

## שלבי הפיתוח

### 1. תכנון ותשתית

נוצרו שלד הפרויקט, דרישות, Bicep וארכיטקטורת API/Worker/Frontend. נפרסו Storage, AI Search, Azure OpenAI, Container Apps, Functions, Static Web Apps, Entra ID ו-Application Insights.

בפריסה אמיתית התגלו מגבלות שלא הופיעו ב-compile: זמינות SKU לפי אזור, מגבלת אורך שם Container App, אזורים מוגבלים ל-Static Web Apps, עיכוב replication ב-Entra ומבנה subject מיוחד ל-GitHub OIDC. הסקריפטים עודכנו להיות idempotent ולפתור את המזהים בפועל.

### 2. Worker ואינדוקס

נבנה Queue Worker לפעולות ADD/REPLACE/DELETE, עם Table Storage לסטטוס ו-AI Search ל-indexer. נוספו idempotency, בדיקות ETag, מחיקת chunks לפי מסמך והמתנה לסיום indexer.

הפריסה הראשונה “הצליחה” אך Azure Functions טען 0 פונקציות כי חבילות Python לא נכללו. vendoring מקומי יצר אחר כך חבילות עם glibc לא תואם. הפתרון היה להתקין את התלויות בתוך image של Azure Functions בזמן CI. פריסת Bicep גם מחקה את `WEBSITE_RUN_FROM_PACKAGE`; ה-workflow שומר ומשחזר אותו.

חילוץ PDF בסיסי לא הספיק למסמכים סרוקים ול-layout מורכב. נוסף Azure AI Document Intelligence. בהמשך תוקנו שמות outputs שגויים (`content` במקום scalar שלא קיים) וחיבור resource billing ל-skillset. ה-Worker בודק גם שגיאות ברמת פריט ולא רק סטטוס כללי של ה-indexer.

### 3. Backend וסוכן

נבנו FastAPI, אימות JWT, SSE, כלים לחיפוש/רשימה/ניהול קבצים, שמירת שיחות ואישורים אטומיים. מודל השיחה עבר דרך ניסויי capacity ל-`gpt-5-mini` עם API `2025-04-01-preview`; embeddings נשארו `text-embedding-3-small`.

CORS חסם את ה-frontend כי מקור Static Web Apps לא הופיע בתגובה ל-preflight. הגדרת המקורות ותצורת הפריסה תוקנו. תוקנו גם mismatch בין שדות האינדקס לקוד, history שהחזיר 422 ללא `conversationId`, rate limits, אירועי tool-call שמגיעים ב-stream, ותשובות ריקות שנראו למשתמש כמקורות ללא תשובה.

### 4. איכות RAG ושאלות המשך

החיפוש הראשוני החזיר לעיתים הרבה מקורות לא רלוונטיים, והמודל בחר עובדה סבירה שלא ענתה על השאלה. נוסף semantic configuration, שופרה שאילתת החיפוש והמקורות המוצגים הוגבלו לתוצאות העדכניות.

לשאלות שבהן נמצאו כמה ערכים אפשריים נוספה שכבת evidence adjudication:
- `clear` — ראיה אחת מקשרת במפורש בין הישות, התכונה והערך.
- `ambiguous` — מוצגות 2–3 אפשרויות עם מקור והמשתמש בוחר.
- `insufficient` — המערכת אומרת שאין ראיה מספקת.

שאלות המשך כגון “מה עם ים סוף?” או “הצג את שאלה א'” איבדו את המסמך שעליו דובר. נוסף active document context הנשמר מהעלאה ומה-citations, התאמת שמות fuzzy וביטול adjudication עבור בקשות ניווט/הצגת סעיף שאינן שאלת fact יחיד.

### 5. מחיקה והחלפה

המודל שינה לעיתים את שם הקובץ, ערבב שם ישן מהיסטוריית השיחה או דרש ניסוח מדויק באופן בלתי סביר. סדרת תיקונים הוסיפה:
- שימוש בשם מההודעה הנוכחית.
- חיפוש התאמה חלקית כאשר היא חד-משמעית.
- canonicalization מול רשימת ה-Blobs.
- מסלול דטרמיניסטי למחיקה מפורשת לפני קריאה למודל.
- אישור המכיל את שם הקובץ המדויק ו-`confirmationId` חד-פעמי.

כך נמנעה תלות ביכולת המודל להעתיק שם עברי ארוך במדויק.

### 6. Frontend ו-CI/CD

נבנה ממשק React מלא עם MSAL, Markdown, citations, שיחות, העלאה בבלוקים, אישורים, polling ומגש עבודות. תוקנו גלילה, session state, שחזור אישורים, שיחה חדשה, CORS וכתובת backend בפריסת Static Web Apps.

נוספו workflows נפרדים לכל שכבה. מעבר הריפו דרש החלפת namespace של GHCR והוספת credential מפורש ל-Container App. משתני Entra ריקים הוגנו כדי שלא ימחקו תצורת אימות קיימת.

## מצב בדיקות ופריסה

- Backend: 143 בדיקות עברו בריצה האחרונה.
- Worker ו-Frontend נבדקים ב-workflows שלהם לפני פריסה.
- ה-backend שנבדק אחרון רץ ב-Container App revision `ca-backend-ragpoc-dev-qelri355pi--0000036`.
- סביבת העבודה הייתה נקייה בקומיט `a8b0a67` לפני עדכון התיעוד הנוכחי.

## מה עדיין פתוח

הפער הגדול ביותר הוא שאין עדיין חיבור ישיר ל-SharePoint/Graph ואין ACL trimming לפי הרשאות SharePoint. קיימות גם מגבלות OCR/layout, תלות ב-indexer משותף, rate limits ושונות טבעית של מודל שפה. הרשימה המלאה נמצאת ב-[LIMITATIONS.md](LIMITATIONS.md).
