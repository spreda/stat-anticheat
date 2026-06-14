# TODO — report-generator

## Описание
В этом файле собираются текущие задачи и идеи по рефакторингу пайплайна генерации отчёта.

## Текущие задачи

| Приоритет | Задача | Статус | Оценка | Комментарии |
|---|---|---|---|---|
| High | Завершить поддержку YAML frontmatter в `utils/calc_filter.py` и `utils/gost_filter.lua` | done | 1d | Метаданные cover page должны успешно парситься Pandoc |
| High | Исправить XML-экранирование в Lua cover filter | done | 1d | Текст `<<` / `>>` и другие спецсимволы не должны ломать .docx |
| High | Сделать linter config-aware для placeholder-ов | done | 1d | `project_name`, `institution_short`, `advisor_name` и похожие ключи должны разрешаться по config/data |
| Medium | Добавить поддержку cover template из `templates/practice_report.json` | todo | 2d | Обложка должна генерироваться по шаблону, а не хардкодиться в Lua-фильтре |
| Medium | Стабилизировать имя выходного файла `.docx` и поддержку UTF-8 | todo | 1d | Проверить генерацию имени файла и совместимость с Windows |
| Medium | Сделать unit-тесты для `utils/calc_filter.py` и `utils/lint_filter.py` | todo | 2d | Проверить на примере `report.md` и sample config |
| Low | Добавить документацию по использованию `utils/generate_report.py` и новым опциям | todo | 0.5d | README / comments для разработчика |

## Идеи и улучшения

- Привязать `templates/practice_report.json` к Lua-фильтру так, чтобы `cover_page` конфигурация управляла расположением и форматированием блоков.
- Поддержать `report_label`, `institution_short`, `group`, `advisor_position` в одном месте через flat config / placeholder map.
- Сделать `utils/lint_filter.py` совместимым с пайпами Pandoc и генерацией markdown-checklist.
- Добавить проверку текста `content-md/report.md` на undefined placeholders до расчётов, чтобы не выпускать сломанные документы.
- Добавить задачу по выносу `output/` в `.gitignore`, если ещё не учтено.
- Рассмотреть возможность генерации reference.docx автоматически через `utils/make_reference.py`.
- Добавить поддержку нумерации таблиц и рисунков, а также внутренних ссылок в Markdown, если потребуется.

## Запланированные шаги

1. Обновить Lua-фильтр так, чтобы он читал `cover_page` из JSON-шаблона.
2. Обновить `generate_report.py` для передачи config и шаблона в лентер и Pandoc.
3. Написать тесты на генерацию `expanded.md` и `.docx` по sample config.
4. Проверить работу на Windows с русскими именами файлов.
5. Документировать команду запуска и опции `--verbose`, `--checklist`, `--fix`.
