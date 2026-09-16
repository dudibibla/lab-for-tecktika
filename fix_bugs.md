# היסטוריית בעיות ותיקונים

זהו יומן מסכם של התקלות המרכזיות שהתגלו בבנייה ובהפעלה אמיתית. למצב הנוכחי ראו [README.md](README.md); מסמך זה אינו backlog.

| תחום | הבעיה שנצפתה | הסיבה | הפתרון |
|---|---|---|---|
| CORS | הצ'אט וה-history נחסמו בדפדפן | מקור ה-Static Web App לא הורשה ב-backend | נוספה תצורת CORS ותוקנה הזרקת כתובת ה-API ל-build |
| Repo migration | deploy חיפש image במאגר הישן | namespace של GHCR נשאר ישן | Bicep ו-workflows הועברו ל-`dudibibla/lab-for-tecktika` ונוסף GHCR credential |
| Worker | פריסה הצליחה אך נטענו 0 functions | חבילות Python לא נארזו | vendoring בתוך image תואם Azure Functions |
| Worker | `GLIBC_2.33 not found` | wheels נבנו על runner חדש יותר | בניית dependencies בתוך runtime image |
| Infra deploy | Worker איבד את הקוד אחרי Bicep | `WEBSITE_RUN_FROM_PACKAGE` נדרס | capture/restore ב-workflow |
| Auth | backend החזיר 503 | secret ריק דרס client ID | overrides נשלחים רק כשיש ערך |
| Search | החיפוש השתמש בשדות לא קיימים | contract לא תאם schema של האינדקס | יישור שמות השדות ובדיקות |
| History | טעינת דף החזירה 422 | `conversationId` הוגדר כחובה | history ללא ID מחזיר שיחה ריקה |
| PDF extraction | מסמכים מורכבים איבדו מבנה | חילוץ בסיסי לא שמר layout | Document Intelligence Layout Skill |
| DI output | indexer נכשל או קיבל ערך ריק | output name/path לא קיים | שימוש ב-`content` וב-output הנכון של skill |
| Indexer | Job סומן הצלחה למרות כשל מסמך | נבדק רק status כללי | בדיקת item-level failures ושמירת פירוט |
| OpenAI | 429 ותשובות איטיות | capacity/API/model לא מתאימים | מעבר ל-`gpt-5-mini`, API חדש ו-retry/backoff |
| SSE | הופיעו מקורות בלי תשובה | tool calls הגיעו ב-stream ולא עובדו במלואם | איסוף tool calls והגנה מפני תשובה ריקה |
| RAG | הרבה citations לא רלוונטיים | semantic config לא הופעל וסינון חלש | `document-content-semantic`, query tuning ומקורות מהחיפוש האחרון |
| עובדות | נבחר ערך סביר אך לא קשור | similarity לבדו לא מוכיח קשר | evidence adjudicator עם clear/ambiguous/insufficient |
| Follow-up | “הצג שאלה א'” איבד את המבחן | שם המסמך לא נשמר בין תורות | active document context מהעלאה ומ-citations |
| Delete | שם מדויק דווח כ-not found | המודל שינה/חתך שם עברי או השתמש בהיסטוריה | resolver קנוני ומסלול delete דטרמיניסטי |
| Replace | attachment נשכח בתור הבא | pending attachment לא נשמר | שמירה ב-Table עד שימוש או אישור |
| Conversations | New conversation חזר לשיחה קודמת | state ישן נטען מחדש | יצירת ID חדש ואיפוס session מתאים |

## עקרונות שנקבעו בעקבות התקלות

- הצלחת HTTP או deployment אינה הוכחה שהרכיב עובד; בודקים host, trigger, indexer ותוצאה עסקית.
- שמות קבצים לפעולה הרסנית נפתרים מול Storage ולא לפי טקסט שהמודל החזיר.
- במקרה של כמה תשובות סבירות המערכת מציגה אפשרויות עם מקור במקום לבחור בעצמה.
- שאלה עוקבת יורשת מסמך פעיל, אך בקשה כללית עדיין יכולה לחפש בכל הספרייה.
- תיעוד מצב נוכחי נשמר ב-`README.md`, `ARCHITECTURE.md`, `SUMMARY.md` ו-`LIMITATIONS.md`; מסמכי plan הישנים נשמרים כהיסטוריה בלבד.
