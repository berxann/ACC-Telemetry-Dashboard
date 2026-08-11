"""
Смотрит последнюю записанную сессию (lap_id) и разбивает её на отдельные круги,
находя моменты, когда current_lap_time падает обратно к нулю (= начался новый круг).

Запуск: python detect_laps.py
"""

import sqlite3

DB_PATH = "telemetry.db"


def main():
    conn = sqlite3.connect(DB_PATH)

    lap_id, track, car = conn.execute(
        "SELECT id, track, car FROM laps ORDER BY id DESC LIMIT 1"
    ).fetchone()

    rows = conn.execute("""
        SELECT id, position, current_lap_time
        FROM telemetry
        WHERE lap_id = ?
        ORDER BY id
    """, (lap_id,)).fetchall()

    conn.close()

    print(f"Сессия lap_id={lap_id} | трасса={track} | машина={car}")
    print(f"Всего точек телеметрии: {len(rows)}")

    if not rows:
        print("Данных нет.")
        return

    # Находим моменты сброса current_lap_time (новый круг начался)
    lap_boundaries = [0]  # индексы начала каждого круга в списке rows
    for i in range(1, len(rows)):
        prev_time = rows[i - 1][2]
        curr_time = rows[i][2]
        if curr_time < prev_time - 1.0:  # время резко упало — новый круг
            lap_boundaries.append(i)

    lap_boundaries.append(len(rows))  # конец последнего круга

    print(f"\nНайдено кругов: {len(lap_boundaries) - 1}")
    for n in range(len(lap_boundaries) - 1):
        start = lap_boundaries[n]
        end = lap_boundaries[n + 1]
        segment = rows[start:end]
        pos_start = segment[0][1]
        pos_end = segment[-1][1]
        duration = segment[-1][2]
        print(f"  Круг {n+1}: точек={len(segment)}, position от {pos_start:.3f} до {pos_end:.3f}, время={duration:.2f} сек")


if __name__ == "__main__":
    main()
