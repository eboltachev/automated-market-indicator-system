# News Price Forecaster Service

Минимальный production-ready сервис (FastAPI + React) для прогноза цены по новостям.

## Подготовка модели
```bash
mkdir -p models
cp model_rubert-tiny1.pt models/model_rubert-tiny1.pt
```

## Настройка env
```bash
cp .env.example .env
```

## Запуск
```bash
docker compose up --build -d
```

Frontend: http://localhost:5004

## Примеры curl
```bash
curl http://localhost:8000/health
```
```bash
curl -X POST http://localhost:8000/api/predict -H 'Content-Type: application/json' -d '{"asset":"LKOH","period":7,"news":[{"date":"2026-04-29","text":"текст новости"}]}'
```
```bash
curl -X POST http://localhost:8000/api/update -H 'Content-Type: application/json' -d '{"assets":["LKOH","IMOEX","BZ=F"]}'
```

## Excel формат
Поддерживаются:
- `date` и `text`
- `Unnamed: 0` и `Unnamed: 1`
