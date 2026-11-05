# cinedigest — вечерний кинодайджест СПб

Раз в день собирает сеансы семи кинотеатров Петербурга («Дом кино», «Родина», «Аврора», «Художественный», «Ленфильм», Out Cinema, «Мираж на Большом») на ближайшую неделю и пишет: одностраничный сайт (`docs/index.html`), текстовую выжимку (`docs/digest.txt`), снимок данных (`docs/screenings.json`, `docs/status.json`) и, если настроено, пушит сводку в Telegram. Всё читается по файлам, тесты не трогают сеть.

Страница живёт на GitHub Pages (ветка `main`, папка `/docs`): Settings → Pages → Deploy from branch → main /docs. Обновляется утренним запуском Actions (09:00 МСК): сеансы с 18:00 по одному списку на день, «весь день» и фильтры по площадкам — чекбоксы без JavaScript, ночные показы стоят под предыдущим днём с бейджем «ночь на чт».

## Команды

```sh
.venv/bin/python -m cinedigest run                  # всё: fetch 7 дней + страница + digest + telegram
.venv/bin/python -m cinedigest run --out docs       # вывод под указанный корень (docs/ и snapshots/ под ним)
.venv/bin/python -m cinedigest run --days 3         # окно в 3 дня
.venv/bin/python -m cinedigest run --date 2026-11-07        # один день
.venv/bin/python -m cinedigest run --only rodina,domkino    # перечисленные площадки
.venv/bin/python -m cinedigest run --no-telegram    # без пуша
.venv/bin/python -m cinedigest run --print          # напечатать текст для Telegram в stdout, не отправляя
.venv/bin/python -m cinedigest render               # пересобрать страницу+digest из сохранённого снимка, без сети
.venv/bin/python -m cinedigest fetch --venue rodina --date 2026-11-07 --save /tmp/raw   # сырые ответы одной площадки
```

Коды выхода: `0` — все площадки ok; `2` — хоть одна не собралась (в т.ч. устаревшие данные с прошлого запуска); `1` — падение. Площадка, у которой ничего не собралось, замещается сеансами предыдущего снимка с пометкой «данные с прошлого запуска».

## Переменные окружения

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — обе заданы → сводка на сегодня уходит в Telegram; иначе шаг пропускается с записью в журнал.
- `CINEDIGEST_PAGE_URL` — последняя строчка телеграм-сообщения (ссылка на страницу).
- `CINEDIGEST_REPO_URL` — ссылка «код» в подвале страницы.

Секреты никогда не попадают в репозиторий; в Actions задаются как secrets.

## Как устроено

- `cinedigest/model.py` — типы `Screening`, `VenueStatus`, `Snapshot`, порядок `VENUES`, вечер с 18:00, ночь до 06:00 сидит под предыдущим днём.
- `cinedigest/venues/<venue>.py` — по модулю на площадку: `ID`/`NAME`/`DAILY` + сетевой `fetch(http, days)` и чистый `parse(raw, days)`. Сырые ответы складываются в `snapshots/<run-id>/<venue>/<label>`.
- `cinedigest/pipeline.py` — одно окно: fetch+parse каждой площадки, политика ошибок (падение площадки не валит страницу), перенос старых данных ≤72 ч, правило «ноль без маркера „сеансов нет“» для ежедневных площадок.
- `cinedigest/render.py` + `templates/index.html.j2` — контекст и одна Jinja-страница (CSS-чекбоксы; JS только для localStorage, приглушения времени и перехода ко дню).
- `cinedigest/render_text.py` — тот же материал в тексте: `digest.txt` и тело Telegram (разбиение по пустым строкам и строкам, части с «(i/n)»).
- `cinedigest/deliver.py` — запись `docs/index.html` и `docs/digest.txt`, Telegram-пуш по частям (plain text, без parse_mode).
- `cinedigest/cli.py` — `run` / `render` / `fetch`.

## Как добавить площадку

1. Скопируйте любой модуль из `cinedigest/venues/` под вашу площадку и заполните `ID` (ключ в `model.VENUES`), `NAME`, `DAILY`.
2. `fetch(http, days)` → список `(label, body)`; только сеть.
3. `parse(raw, days)` → список `Screening`; без сети, падает на неожиданной разметке — её поймает правило «странного нуля».
4. Зарегистрируйте площадку: ключ в `model.VENUES` и модуль в списке `cli.DEFAULT_VENUES`; положите фикстуру ответа в `tests/fixtures/<venue>/` и напишите тест на `parse` по ней.

## Тестирование

```sh
.venv/bin/python -m pytest -q
```

Тесты рендера, конвейера и площадок работают на сохранённых ответах (`tests/fixtures/`), сеть не вызывается.
