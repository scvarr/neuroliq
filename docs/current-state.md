# Текущее состояние

Этап: M5.1 выполнен — ограниченная проверка периодического эха на графе M4; стенд M4.1 — единый Docker-запускаемый Neuroliq Graph Lab. Roadmap M0–M8 не изменён.

- Core M1 (`Graph`, `Concept`, `Connection`) и математика Activation M2 не изменены. Концепт содержит только UUID; связи нетипизированные, технически неориентированные. Self-loop и дубликаты запрещены.
- Введён отдельный `ExperimentDefinition`: версия JSON, title, концепты с UUID и внешними labels, connections/strength, seeds и параметры. Loader валидирует документ и сохраняет идентичность UUID; save/load возвращает эквивалентное описание. Runtime/trace в файл не входят.
- Единственный `neuroliq.web:app` предоставляет Graph Lab: создание/редактирование/удаление структуры, seeds и параметров, импорт/экспорт JSON, start/step/run/reset, текущую activation, ranking/contributions/full trace выбранного шага. JavaScript только редактирует описание и отображает результаты Python.
- Успешная замена definition целиком строит новый Graph и пустой Activation; старый trace уничтожается. Ошибка валидации оставляет прежнее состояние. Mutating API ради редактора в Graph не добавлен.
- Один контейнер FastAPI и статический frontend, внешний настраиваемый localhost-порт. Серверного хранилища и многопользовательских сессий нет; эксперимент переносится файлом.
- M3/M4 перенесены в `experiments/m3-simple-retrieval.neuroliq.json` и `experiments/m4-two-step-bridge.neuroliq.json` с прежними UUID, топологией, силами и параметрами. Отдельные M3/M4 fixtures/apps удалены; M1/M2 fixtures сохранены для тестов и диагностики.
- M3: 5 концептов, 4 strength=1.0; decay=0.5, max_active=5, max_steps=1. Одиночные СТОЛИЦА/ФРАНЦИЯ дают ничьи ПАРИЖ=0.5 с ЛОНДОНОМ/ЛИОНОМ; совместные дают ПАРИЖ=1.0 против 0.5 через два вклада.
- M4: A—C—X—D—B, C—E, D—F; 7 концептов, 6 strength=1.0; decay=0.5, max_active=7, max_steps=2. Одиночные A/B дают ничью X=0.25; совместные дают X=0.5 против 0.25 через C→X/D→X. Возвраты к seeds сохранены; pruning отсутствует.
- M5.1: `experiments/m5-1-backwave-echo.neuroliq.json` сохраняет структуру/UUID/strength M4, seeds A=B=1.0, decay=0.5, max_active=7; max_steps=6. Неизменный Activation M2 даёт C=D=0.5 на шагах 1/3/5 и X=0.5, A=B=E=F=0.25 на 2/4/6: обратные contributions восстанавливают период 2 без затухания фаз. Полный trace, численное объяснение и 3 прошедших targeted tests: [M5.1](m5-1-experiment.md). Решения M5.2+ не принимались.
- Исследовательские выводы сохранены: [M2](m2-experiment.md), [M3](m3-experiment.md), [M4](m4-experiment.md), [M5.1](m5-1-experiment.md). Подтверждены контролируемые структурные пересечения и периодическое эхо на графе M4 при параметрах M5.1. Маршрутизация, retention/context memory, обучение, языковой слой, MCP и LLM отсутствуют; критерий всего первого исследовательского цикла не выполнен.

Запуск из корня:

```text
docker compose up --build
```

Открыть [Graph Lab](http://127.0.0.1:17890). Порт задаётся `NEUROLIQ_PORT`, default 17890; binding `127.0.0.1:${NEUROLIQ_PORT:-17890}:8000`. Остановка: `docker compose down`.

Формат файла, ручной round-trip, воспроизведение M3/M4 и targeted tests: [Graph Lab](graph-lab.md). Архитектура: [описание](architecture.md).

Проверка M4.1: 75 targeted tests прошли; Docker image собран, localhost binding и изменение host port подтверждены compose-конфигурацией. В браузере выполнены создание графа, скачивание JSON, очистка и импорт файла с сохранением UUID/strength/seeds/параметров, Step/Run и все три сценария M3/M4 с просмотром истории.
