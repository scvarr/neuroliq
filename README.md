# Neuroliq

**[Проектная документация: канонический навигатор](docs/README.md)** — роли документов и маршруты чтения по типу задачи.

Исследовательский проект представления и обработки знаний через граф концептов. Core хранит непрозрачные UUID и нетипизированные числовые связи; Graph Lab позволяет наблюдать активацию и trace. Текущая фаза — исследование L0/bootstrap после bounded-проверки M6.3; semantic L0 и факторизация пока не реализованы. Границы и фокус — в [current-state.md](docs/current-state.md), маршруты чтения — в [навигаторе](docs/README.md).

Запуск из корня проекта с Docker Desktop:

```bat
docker compose up --build
```

Открыть [Neuroliq Graph Lab](http://127.0.0.1:17890). Создавайте эксперимент, редактируйте структуру и параметры, сохраняйте/загружайте `*.neuroliq.json`, изучайте Python activation и trace. Файлы M3/M4 находятся в `experiments/`. Остановка:

```bat
docker compose down
```

Внешний порт задаёт `NEUROLIQ_PORT`, по умолчанию 17890, доступ только с localhost. [Запуск, формат и воспроизведение](docs/graph-lab.md), [актуальное состояние](docs/current-state.md), [архитектура](docs/architecture.md), [исследовательская основа](docs/foundation.md).
