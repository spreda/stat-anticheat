# Core Insight: Institutional Document vs Encyclopedia Article

## The problem

AI defaults to "knowledge dump" mode — explain terms, cite brands, verbose code.
The editor rewrites to "institutional compliance" — formal, GOST-style, no English terms.

Root cause: models are trained on an English-heavy corpus where em-dashes, Western brands,
and marketing tone dominate. The model doesn't know it's writing for a Russian university
department — it knows it's writing about a topic and outputs the most probable continuation.

## Quantitative indicators

| Signal | AI (before edit) | Editor (after edit) |
|---|---|---|
| Em-dash (—) | 88 | 0 |
| En-dash (–) | 3 | 86 |
| English terms (3+ letters) | 469 | 310 |
| Bold ratio | 2.9% | 6.9% |
| Paragraph styles | 2 | 7 |
| Avg sentence length | 5.1 words | 5.6 words |

## The fix: change the coordinate system

Not "write about Unity game" but "fill institutional document template per approved structure".

--- 

## Philosophy: one principle

Every decision: does this look like a standard document a department would accept,
or a blog post for developers? If blog → rewrite.

Two modes:

| Mode | Behavior | Result |
|---|---|---|
| Encyclopedia | Demonstrates knowledge, explains terms, cites brands, over-detailed | Marketing article, tutorial, market review |
| Institution | Fills formal document for passing review | GOST, standard, approved template |

**Agent task**: Institution mode.
