# Report Generator Framework

Универсальный фреймворк для автоматизации создания отчётов (ВКР, преддипломная практика, производственная практика) по шаблону вуза с ГОСТ-форматированием.

## Структура

```
report-generator/
├── config.json              # Конфигурация (заполнить под свой отчёт)
├── config_practice.json     # Пример конфигурации для отчёта по практике
├── README.md                # Этот файл
├── setup.py                 # Установка окружения
├── run.bat                  # Запуск на Windows
├── run.sh                   # Запуск на Linux/Mac
├── content/                 # Модули содержания для разных типов отчётов
│   ├── __init__.py
│   └── practice_report.py   # Содержание для отчёта по преддипломной практике
├── utils/
│   ├── read_diploma.py      # Чтение и анализ .docx
│   ├── generate_report.py   # Генерация отчёта (основной скрипт)
│   └── verify_gost.py       # Проверка ГОСТ-форматирования
├── templates/               # Шаблон .docx от вуза
├── input/                   # Текущий черновик (если есть)
├── project/                 # Код проекта (для анализа)
│   ├── screenshots/         # Скриншоты
│   └── diagrams/            # UML-диаграммы
└── output/                  # Готовый отчёт
```

## Быстрый старт

### 1. Заполнить config.json

```json
{
    "report_type": "practice_report",
    "report_type_label": "ОТЧЁТ ПО ПРЕДДИПЛОМНОЙ ПРАКТИКЕ",
    "diploma": {
        "author": {
            "full_name": "Иванов Иван Иванович",
            "initials": "И.И.",
            "group": "ИС-21"
        },
        "specialty": "09.02.07 Информационные системы и программирование",
        "theme": "Тема работы",
        "year": 2026
    },
    "project": {
        "name": "Название проекта",
        "type": "Веб-приложение",
        "platform": "Web",
        "language": "Python"
    },
    "section_order": [
        "cover", "introduction", "section1", "section2",
        "section3", "section4", "conclusion", "references", "appendices"
    ]
}
```

### 2. Положить шаблон

Скопировать шаблон вуза в `templates/Шаблон для отчёта.docx`

### 3. Положить код проекта

В `project/` — скрипты, скриншоты, диаграммы

### 4. Установить зависимости

```bash
cd report-generator
pip install python-docx lxml
```

### 5. Запустить

```bash
# Для отчёта по преддипломной практике
python utils/generate_report.py --config config_practice.json --type practice_report

# Для дипломной работы
python utils/generate_report.py --config config.json --type diploma
```

## Типы отчётов

| Тип | Модуль содержания | Описание |
|-----|-------------------|----------|
| `practice_report` | `content/practice_report.py` | Отчёт по преддипломной практике |
| `diploma` | `content/diploma.py` | Выпускная квалификационная работа |

## Как создать новый тип отчёта

1. Создать файл `content/my_report.py`
2. Реализовать функции-генераторы разделов:
   - `generate_introduction(config, project_analysis)`
   - `generate_section1(config, project_analysis)`
   - `generate_section2(config, project_analysis)`
   - `generate_section3(config, project_analysis)`
   - `generate_section4(config, project_analysis)`
   - `generate_conclusion(config, project_analysis)`
   - `generate_references(config)`
   - `generate_appendices(config, project_analysis)`
3. Каждая функция возвращает dict с ключами `title` и `content`
4. Запустить: `python utils/generate_report.py --type my_report`

## Требования

- Python 3.8+
- python-docx
- lxml
