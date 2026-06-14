# Style Rules — Report Generator

Generic writing rules for academic .md reports. No project-specific content.

## Typography

- `--` (два дефиса) **ONLY** for dashes in .md. Zero em-dash (—, U+2014) or en-dash (–, U+2013). Pandoc converts `--` to the correct typographic dash in .docx.
- Quotes: «ёлочки», not "лапки".
- Thousand separator: non-breaking space ("1 200 руб.").
- Decimal separator: comma ("123,45").
- Minimum brackets. If info matters → separate sentence. If not → remove.
- After dash — space on both sides.
- Space between number and unit ("210 ч", "76 000 руб").

## Language

- Formal academic Russian: «была разработана», «были решены».
- **NO** first person («я», «мы», «мой», «наш»). Impersonal only.
- **NO** AI-slang/marketing: «погрузимся», «давайте рассмотрим», «копнём», «пошагово»,
  «вишенка на торте», «краеугольный», «стоит отметить», «важно понимать».
- **NO** English verbs: debug (отладка), merge (слияние), commit, deploy, refactor.
- **NO** parenthetical brackets explaining terms: «(F=ma)», «(A = B)».
- Exception: «(от англ. ...)» only for abbreviations and direct anglicisms (API, XGBoost, AUC). NOT for Russian translations of foreign concepts (обучение с учителем, обнаружение аномалий, кросс-валидация).
- **NO** formula in brackets — rewrite as prose.
- **NO** unnecessary brackets in tables and headings. If info matters → separate column or rewrite without brackets. If not → remove.
- Terms in Russian. English only if no Russian equivalent (API, UI, SDK) or established abbreviation.
- **Список литературы:** Для англоязычных источников -- авторы и название статьи на английском, журнал/конференция на английском, P. вместо С. Для русскоязычных -- как есть. Для книг на английском -- без «пер. с англ.», указывать ISBN и издательство.
- Minimum evaluative adjectives: not «стремительный рост» → «рост».
- Short sentences: 5–7 words. One thought per sentence.
- Avoid: chains of subordinate clauses («который...», «где...»).

## Structure

- One type of list per document (bullet **OR** numbered, except references).
- Every list needs an introductory paragraph before it.
- No single-item list — merge into paragraph text.
- List items end with `;` (semicolon), last item ends with `.` (period).
- **NO** capital letter at the start of a list item. After `1. ` or `- ` use lowercase.
  Exception: proper names (ГОСТ, Windows, Unity) and established abbreviations retain uppercase.
- **NO** semicolons in body text (prose paragraphs). Semicolons (`;`) allowed only in list items,
  term definitions (`ТЗ -- техническое задание;`), and code blocks. In prose, use periods.
- No hardcoded counts («все 27 скриптов») — use {var=...} or remove.
- No operator-directed comments («скриншоты не включены») — remove section entirely.
- Class names only when necessary. Prefer Russian description
  («в методе фиксированного обновления» over «в методе FixedUpdate()»).
- Code snippets: no longer than 5–10 lines.
- **No English variable names in formulas/code**. Write `доход = цена * копии`, not
  `income = price * copies`. Use the same name style as prose.
- Formulas and code use the same styling (font, size, spacing) as regular text.
- Each paragraph: one complete thought. No bullet-point definitions inline.
- **Cross-references required**: every captioned element (figure, table, appendix) must have a
  text reference in the preceding paragraph. No figure or table without an inline citation.

## Verification checklist

1. No em-dash (—) or en-dash (–) -- only `--` in .md.
2. Every list has an intro paragraph.
3. No single-item lists.
4. Cross-references to tables/figures match reality.
5. No brittle numbers («все N требований»).
6. Tables promised in text actually exist.
7. No operator comments («скриншоты не включены»).

## Post-generation linter

Run: `python -m lint.lint content-md/report.md --level error,warning`
