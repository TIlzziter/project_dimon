# Журнал дежурной смены

Локальный сайт по спеке `docs/features/duty-journal/spec.md`. Один процесс, база в файле, браузер.

## Запуск

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py seed-demo
.\.venv\Scripts\python.exe run.py
```

Сайт открывается на http://127.0.0.1:8080

Демо-входы после `seed-demo`:

| Кто | Логин | Пароль |
| --- | --- | --- |
| Администратор | admin | admin |
| Дежурный | duty1 | duty1 |
| Второй дежурный | duty2 | duty2 |
| Бригадир | brig | brig |

Инструкция для читателей: http://127.0.0.1:8080/instruction и файл `docs/features/duty-journal/instruction.html`.

Презентация демо: `docs/features/duty-journal/demo.html`. План ведущего: `docs/features/duty-journal/demo-plan.md`.

Проверка сценария: `.\.venv\Scripts\python.exe -m pytest -q`

Чтобы начать с пустой базы, остановите программу и удалите папку `data`.

## Как это поедет на виртуалку

Сейчас процесс слушает только этот компьютер. На бета-сервер уезжает тот же код. Меняются настройки окружения, не экраны:

| Переменная | Сейчас | На виртуалке |
| --- | --- | --- |
| HOST | 127.0.0.1 | 0.0.0.0 |
| PORT | 8080 | порт, который откроет файрвол |
| DATA_DIR | папка data рядом с программой | отдельный диск, например /var/lib/duty-journal |
| SECRET_KEY | local-dev-only | длинная случайная строка |
| COOKIE_SECURE | не задана | 1, когда перед сайтом появится https |
| PDF_FONT | Arial, если он найден | путь к DejaVu или Liberation Sans |

Пароли уже хранятся не открытым текстом. Перед белым адресом администратор меняет пароль `admin` в разделе «Управление».

В эту версию сознательно не входят прокси, сертификат, файрвол, ограничение попыток входа и защита форм. Их ставят снаружи процесса, когда появится бета. Проверка, что процесс жив: `GET /health` отвечает `ok`.
