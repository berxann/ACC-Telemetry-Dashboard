"""
ACC Telemetry API
Отдаёт данные из telemetry.db через HTTP, чтобы фронтенд мог их рисовать.

Запуск: uvicorn api:app --reload
Дальше открой http://127.0.0.1:8000/docs — увидишь все эндпоинты и сможешь их потыкать.
"""

import sqlite3
import os
import json
import numpy as np
import anthropic
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_PATH = os.path.join(BASE_DIR, "telemetry.db")

app = FastAPI(title="ACC Telemetry API")

# Ключ берётся из переменной окружения ANTHROPIC_API_KEY — SDK читает её сам.
# Если переменная не выставлена, клиент создастся, но реальный вызов упадёт
# с понятной ошибкой (обрабатываем это ниже в /analyze).
anthropic_client = anthropic.Anthropic()

# Разрешаем фронтенду (даже если он открыт как локальный файл) обращаться к этому API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # чтобы обращаться к колонкам по имени, а не по индексу
    return conn


@app.get("/laps")
def list_laps():
    """Список всех записанных сессий."""
    conn = get_conn()
    rows = conn.execute("SELECT id, session_name, track, car, created_at FROM laps ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/laps/{lap_id}/telemetry")
def get_telemetry(lap_id: int):
    """Вся телеметрия одной сессии (одного запуска логгера)."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT position, speed_kmh, gas, brake, current_lap_time,
               tyre_temp_fl, tyre_temp_fr, tyre_temp_rl, tyre_temp_rr, car_x, car_z
        FROM telemetry WHERE lap_id = ? ORDER BY id
    """, (lap_id,)).fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"Нет данных для lap_id={lap_id}")

    return [dict(r) for r in rows]


def cumulative_distance(x, z):
    """Считает пройденную дистанцию в метрах по координатам — сумма длин отрезков между соседними точками."""
    x, z = np.array(x), np.array(z)
    dx = np.diff(x, prepend=x[0])
    dz = np.diff(z, prepend=z[0])
    step_dist = np.sqrt(dx**2 + dz**2)
    return np.cumsum(step_dist)


def unwrap_position(pos):
    pos = np.array(pos)
    unwrapped = pos.copy()
    for i in range(1, len(pos)):
        if unwrapped[i] < unwrapped[i - 1] - 0.5:
            unwrapped[i:] += 1.0
    return unwrapped


def split_into_laps(rows):
    """Разбивает точки одной сессии на отдельные круги по сбросу current_lap_time (в мс)."""
    boundaries = [0]
    for i in range(1, len(rows)):
        if rows[i]["current_lap_time"] < rows[i - 1]["current_lap_time"] - 1000:
            boundaries.append(i)
    boundaries.append(len(rows))
    return [rows[boundaries[n]:boundaries[n + 1]] for n in range(len(boundaries) - 1)]


def is_full_lap(segment, min_points=50, min_span=0.95):
    """
    Считает круг "полным" (боевым), если он покрывает почти всю дистанцию трассы
    (position от старта почти до финиша), а не является огрызком до/после боевого круга
    (выезд на трассу, доезд до пита и т.п.).
    """
    if len(segment) < min_points:
        return False
    unwrapped = unwrap_position([r["position"] for r in segment])
    span = unwrapped.max() - unwrapped.min()
    return span >= min_span


def get_valid_laps(rows):
    """Возвращает только полные (боевые) круги сессии, отбрасывая огрызки."""
    return [seg for seg in split_into_laps(rows) if is_full_lap(seg)]


@app.get("/laps/{lap_id}/splits")
def get_splits(lap_id: int):
    """Показывает боевые круги сессии (огрызки до/после отброшены)."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT position, current_lap_time FROM telemetry WHERE lap_id = ? ORDER BY id
    """, (lap_id,)).fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"Нет данных для lap_id={lap_id}")

    laps = get_valid_laps(rows)
    result = []
    for n, segment in enumerate(laps):
        result.append({
            "lap_number": n + 1,
            "points": len(segment),
            "duration_sec": segment[-1]["current_lap_time"] / 1000.0,
        })
    return result


@app.get("/compare")
def compare(lap_id: int, lap_a: int, lap_b: int):
    """
    Сравнивает два круга внутри одной сессии (lap_id).
    lap_a, lap_b — номера кругов из /laps/{lap_id}/splits (1-индексация).
    Возвращает интерполированные на общую сетку позиции данные для построения графиков на фронте.
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT position, speed_kmh, gas, brake, current_lap_time, steer_angle, rpm,
               tyre_temp_fl, tyre_temp_fr, tyre_temp_rl, tyre_temp_rr, car_x, car_z
        FROM telemetry WHERE lap_id = ? ORDER BY id
    """, (lap_id,)).fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"Нет данных для lap_id={lap_id}")

    laps = get_valid_laps(rows)
    if not laps:
        raise HTTPException(status_code=404, detail="В этой сессии нет ни одного боевого круга")
    if len(laps) < max(lap_a, lap_b):
        raise HTTPException(status_code=400, detail=f"В сессии только {len(laps)} боевых кругов, запрошены {lap_a} и {lap_b}")

    seg_a = laps[lap_a - 1]
    seg_b = laps[lap_b - 1]

    pos_a = unwrap_position([r["position"] for r in seg_a])
    time_a = np.array([r["current_lap_time"] for r in seg_a]) / 1000.0
    speed_a = np.array([r["speed_kmh"] for r in seg_a])
    gas_a = np.array([r["gas"] for r in seg_a])
    brake_a = np.array([r["brake"] for r in seg_a])
    steer_a = np.degrees(np.array([r["steer_angle"] for r in seg_a]))  # ACC отдаёт steer_angle в радианах
    rpm_a = np.array([r["rpm"] for r in seg_a])
    tyre_fl_a = np.array([r["tyre_temp_fl"] for r in seg_a])
    tyre_fr_a = np.array([r["tyre_temp_fr"] for r in seg_a])
    tyre_rl_a = np.array([r["tyre_temp_rl"] for r in seg_a])
    tyre_rr_a = np.array([r["tyre_temp_rr"] for r in seg_a])
    car_x_a = [r["car_x"] for r in seg_a]
    car_z_a = [r["car_z"] for r in seg_a]

    pos_b = unwrap_position([r["position"] for r in seg_b])
    time_b = np.array([r["current_lap_time"] for r in seg_b]) / 1000.0
    speed_b = np.array([r["speed_kmh"] for r in seg_b])
    gas_b = np.array([r["gas"] for r in seg_b])
    brake_b = np.array([r["brake"] for r in seg_b])
    steer_b = np.degrees(np.array([r["steer_angle"] for r in seg_b]))
    rpm_b = np.array([r["rpm"] for r in seg_b])
    tyre_fl_b = np.array([r["tyre_temp_fl"] for r in seg_b])
    tyre_fr_b = np.array([r["tyre_temp_fr"] for r in seg_b])
    tyre_rl_b = np.array([r["tyre_temp_rl"] for r in seg_b])
    tyre_rr_b = np.array([r["tyre_temp_rr"] for r in seg_b])
    car_x_b = [r["car_x"] for r in seg_b]
    car_z_b = [r["car_z"] for r in seg_b]

    # Разрешение сетки подстраивается под реальную плотность записи (обычно ~20 Гц),
    # чтобы карта трассы и графики не теряли детализацию из-за грубой интерполяции
    n_points = min(6000, max(500, len(seg_a), len(seg_b)))

    common_pos = np.linspace(
        max(pos_a.min(), pos_b.min()),
        min(pos_a.max(), pos_b.max()),
        n_points
    )

    time_a_i = np.interp(common_pos, pos_a, time_a)
    time_b_i = np.interp(common_pos, pos_b, time_b)
    delta = time_b_i - time_a_i

    result = {
        "track_position": common_pos.tolist(),
        "lap_a": {
            "number": lap_a,
            "total_time": float(time_a[-1]),
            "time": time_a_i.tolist(),
            "speed": np.interp(common_pos, pos_a, speed_a).tolist(),
            "gas": np.interp(common_pos, pos_a, gas_a).tolist(),
            "brake": np.interp(common_pos, pos_a, brake_a).tolist(),
            "steer": np.interp(common_pos, pos_a, steer_a).tolist(),
            "rpm": np.interp(common_pos, pos_a, rpm_a).tolist(),
            "tyre_fl": np.interp(common_pos, pos_a, tyre_fl_a).tolist(),
            "tyre_fr": np.interp(common_pos, pos_a, tyre_fr_a).tolist(),
            "tyre_rl": np.interp(common_pos, pos_a, tyre_rl_a).tolist(),
            "tyre_rr": np.interp(common_pos, pos_a, tyre_rr_a).tolist(),
        },
        "lap_b": {
            "number": lap_b,
            "total_time": float(time_b[-1]),
            "time": time_b_i.tolist(),
            "speed": np.interp(common_pos, pos_b, speed_b).tolist(),
            "gas": np.interp(common_pos, pos_b, gas_b).tolist(),
            "brake": np.interp(common_pos, pos_b, brake_b).tolist(),
            "steer": np.interp(common_pos, pos_b, steer_b).tolist(),
            "rpm": np.interp(common_pos, pos_b, rpm_b).tolist(),
            "tyre_fl": np.interp(common_pos, pos_b, tyre_fl_b).tolist(),
            "tyre_fr": np.interp(common_pos, pos_b, tyre_fr_b).tolist(),
            "tyre_rl": np.interp(common_pos, pos_b, tyre_rl_b).tolist(),
            "tyre_rr": np.interp(common_pos, pos_b, tyre_rr_b).tolist(),
        },
        "delta": delta.tolist(),
    }

    # Координаты есть только в новых записях (car_x/car_z). Если запись старая — их не будет (None).
    # Также защищаемся от вырожденных координат (все точки совпадают — баг определения своей машины
    # в логгере на некоторых сессиях): в этом случае разброс X/Z близок к нулю, и карту строить нельзя.
    def has_real_coords(xs, zs):
        if not xs or any(v is None for v in xs):
            return False
        spread = max(max(xs) - min(xs), max(zs) - min(zs))
        return spread > 5  # меньше 5 метров разброса за весь круг — заведомо не реальный путь

    has_coords_a = has_real_coords(car_x_a, car_z_a)
    has_coords_b = has_real_coords(car_x_b, car_z_b)

    if has_coords_a:
        dist_a = cumulative_distance(car_x_a, car_z_a)
        result["lap_a"]["distance_m"] = np.interp(common_pos, pos_a, dist_a).tolist()
        result["lap_a"]["car_x"] = np.interp(common_pos, pos_a, car_x_a).tolist()
        result["lap_a"]["car_z"] = np.interp(common_pos, pos_a, car_z_a).tolist()

    if has_coords_b:
        dist_b = cumulative_distance(car_x_b, car_z_b)
        result["lap_b"]["distance_m"] = np.interp(common_pos, pos_b, dist_b).tolist()
        result["lap_b"]["car_x"] = np.interp(common_pos, pos_b, car_x_b).tolist()
        result["lap_b"]["car_z"] = np.interp(common_pos, pos_b, car_z_b).tolist()

    return result


def build_sector_summary(result, n_sectors=20):
    """
    Сжимает результат /compare (тысячи интерполированных точек) в N секторов трассы.
    Для каждого сектора — средняя скорость/газ/тормоз/руль по обоим кругам, средняя
    температура шин и накопленная дельта времени на конец сектора (где именно
    выигрывается/теряется время). Компактный JSON, который можно скормить LLM целиком.
    """
    pos = np.array(result["track_position"])
    edges = np.linspace(pos.min(), pos.max(), n_sectors + 1)
    bucket = np.clip(np.digitize(pos, edges[1:-1]), 0, n_sectors - 1)

    a, b = result["lap_a"], result["lap_b"]
    delta = np.array(result["delta"])
    speed_a, speed_b = np.array(a["speed"]), np.array(b["speed"])
    gas_a, gas_b = np.array(a["gas"]), np.array(b["gas"])
    brake_a, brake_b = np.array(a["brake"]), np.array(b["brake"])
    steer_a, steer_b = np.array(a["steer"]), np.array(b["steer"])
    tyre_a = (np.array(a["tyre_fl"]) + np.array(a["tyre_fr"]) + np.array(a["tyre_rl"]) + np.array(a["tyre_rr"])) / 4
    tyre_b = (np.array(b["tyre_fl"]) + np.array(b["tyre_fr"]) + np.array(b["tyre_rl"]) + np.array(b["tyre_rr"])) / 4

    sectors = []
    for i in range(n_sectors):
        mask = bucket == i
        if not mask.any():
            continue
        sectors.append({
            "sector": i + 1,
            "speed_avg_kmh": {"lap1": round(float(speed_a[mask].mean()), 1), "lap2": round(float(speed_b[mask].mean()), 1)},
            "gas_avg_pct": {"lap1": round(float(gas_a[mask].mean()) * 100, 0), "lap2": round(float(gas_b[mask].mean()) * 100, 0)},
            "brake_avg_pct": {"lap1": round(float(brake_a[mask].mean()) * 100, 0), "lap2": round(float(brake_b[mask].mean()) * 100, 0)},
            "steer_avg_deg": {"lap1": round(float(np.abs(steer_a[mask]).mean()), 1), "lap2": round(float(np.abs(steer_b[mask]).mean()), 1)},
            "tyre_temp_avg_c": {"lap1": round(float(tyre_a[mask].mean()), 1), "lap2": round(float(tyre_b[mask].mean()), 1)},
            "cumulative_delta_s": round(float(delta[mask][-1]), 3),  # lap2 - lap1, накопительно
        })
    return sectors


class AnalyzeRequest(BaseModel):
    lap_id: int
    lap_a: int
    lap_b: int
    setup_text: str = ""


@app.post("/analyze")
def analyze_setup(req: AnalyzeRequest):
    """
    Сравнивает круг 1 и круг 2 (обычно: текущий заезд vs личный лучший), сжимает
    телеметрию в сектора и просит Claude проанализировать, где теряется время
    и что стоит поменять в сетапе, с учётом описания сетапа от пользователя.
    """
    result = compare(req.lap_id, req.lap_a, req.lap_b)  # переиспользуем логику /compare напрямую
    sectors = build_sector_summary(result)

    system_prompt = (
        "Ты — инженер по сетапам в симрейсинге Assetto Corsa Competizione. "
        "Тебе дают посекторное сравнение двух кругов одной сессии (lap1 и lap2: скорость, "
        "газ, тормоз, угол руля, температура шин, накопленная дельта времени) и описание "
        "текущего сетапа машины от пилота. Проанализируй, в каких секторах и почему теряется "
        "или выигрывается время (недостаточная скорость в повороте, позднее/раннее торможение, "
        "перегрев/недогрев шин и т.д.), и дай конкретные рекомендации по настройке "
        "(антиролл-бары, дифференциал, давление и развал шин, аэродинамика, тормозной баланс). "
        "Каждую рекомендацию обосновывай конкретными цифрами из данных. Отвечай по-русски, "
        "структурированно, без общих фраз."
    )
    user_content = (
        f"Сектора (lap1 = круг {req.lap_a}, lap2 = круг {req.lap_b}):\n"
        f"{json.dumps(sectors, ensure_ascii=False)}\n\n"
        f"Текущий сетап машины:\n{req.setup_text or '(не указан)'}"
    )

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=500, detail="Anthropic API ключ не найден или неверный. Проверь переменную окружения ANTHROPIC_API_KEY.")
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Ошибка обращения к Anthropic API: {e}")

    text = "".join(block.text for block in response.content if block.type == "text")
    return {"analysis": text, "sectors": sectors}


# Отдаём фронтенд-файлы (папку static/) прямо через тот же сервер
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
