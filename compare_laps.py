"""
Сравнивает два круга из последней сессии (lap_id) — строит time delta график:
где именно на трассе ты быстрее/медленнее относительно второго круга.

Круги внутри сессии определяются автоматически по сбросу current_lap_time.
Указываешь номера кругов для сравнения (1-индексация, как в выводе detect_laps.py).

Запуск: python compare_laps.py
"""

import sqlite3
import numpy as np
import matplotlib.pyplot as plt

DB_PATH = "telemetry.db"

# Какие круги сравнивать (номера из detect_laps.py)
LAP_A_NUM = 2  # "базовый" круг
LAP_B_NUM = 3  # круг, который сравниваем с базовым


def load_session(conn):
    lap_id, track, car = conn.execute(
        "SELECT id, track, car FROM laps ORDER BY id DESC LIMIT 1"
    ).fetchone()

    rows = conn.execute("""
        SELECT position, speed_kmh, current_lap_time, gas, brake
        FROM telemetry
        WHERE lap_id = ?
        ORDER BY id
    """, (lap_id,)).fetchall()

    return lap_id, track, car, rows


def split_into_laps(rows):
    boundaries = [0]
    for i in range(1, len(rows)):
        if rows[i][2] < rows[i - 1][2] - 1000:  # сброс времени в мс — новый круг
            boundaries.append(i)
    boundaries.append(len(rows))

    laps = []
    for n in range(len(boundaries) - 1):
        laps.append(rows[boundaries[n]:boundaries[n + 1]])
    return laps


def unwrap_position(pos):
    """Превращает position (который скачет с ~1.0 обратно на 0.0 на финише)
    в монотонно растущую последовательность, начиная с исходного стартового значения."""
    pos = np.array(pos)
    unwrapped = pos.copy()
    for i in range(1, len(pos)):
        if unwrapped[i] < unwrapped[i - 1] - 0.5:  # обнаружили скачок через финиш
            unwrapped[i:] += 1.0
    return unwrapped


def main():
    conn = sqlite3.connect(DB_PATH)
    lap_id, track, car, rows = load_session(conn)
    conn.close()

    laps = split_into_laps(rows)

    if len(laps) < max(LAP_A_NUM, LAP_B_NUM):
        print(f"Недостаточно кругов в сессии (найдено {len(laps)}), нужно минимум {max(LAP_A_NUM, LAP_B_NUM)}")
        return

    lap_a = laps[LAP_A_NUM - 1]
    lap_b = laps[LAP_B_NUM - 1]

    pos_a = unwrap_position([r[0] for r in lap_a])
    time_a = np.array([r[2] for r in lap_a]) / 1000.0  # мс -> сек
    speed_a = np.array([r[1] for r in lap_a])
    gas_a = np.array([r[3] for r in lap_a])
    brake_a = np.array([r[4] for r in lap_a])

    pos_b = unwrap_position([r[0] for r in lap_b])
    time_b = np.array([r[2] for r in lap_b]) / 1000.0
    speed_b = np.array([r[1] for r in lap_b])
    gas_b = np.array([r[3] for r in lap_b])
    brake_b = np.array([r[4] for r in lap_b])

    # Общая сетка позиций — интерполируем оба круга на неё, чтобы сравнивать "в одной точке трассы"
    common_pos = np.linspace(
        max(pos_a.min(), pos_b.min()),
        min(pos_a.max(), pos_b.max()),
        500
    )

    time_a_interp = np.interp(common_pos, pos_a, time_a)
    time_b_interp = np.interp(common_pos, pos_b, time_b)
    speed_a_interp = np.interp(common_pos, pos_a, speed_a)
    speed_b_interp = np.interp(common_pos, pos_b, speed_b)
    gas_a_interp = np.interp(common_pos, pos_a, gas_a)
    gas_b_interp = np.interp(common_pos, pos_b, gas_b)
    brake_a_interp = np.interp(common_pos, pos_a, brake_a)
    brake_b_interp = np.interp(common_pos, pos_b, brake_b)

    delta = time_b_interp - time_a_interp  # + значит круг B медленнее в этой точке, - значит быстрее

    lap_a_total = time_a[-1]
    lap_b_total = time_b[-1]

    fig, (ax1, ax2, ax3, ax4, ax5) = plt.subplots(5, 1, figsize=(12, 16), sharex=True)

    ax1.plot(pos_a, time_a, label=f"Круг {LAP_A_NUM} ({lap_a_total:.2f} сек)", color="tab:blue")
    ax1.plot(pos_b, time_b, label=f"Круг {LAP_B_NUM} ({lap_b_total:.2f} сек)", color="tab:orange")
    ax1.set_ylabel("Время круга, сек")
    ax1.set_title(f"Трасса: {track} | Машина: {car} | Сравнение кругов {LAP_A_NUM} и {LAP_B_NUM}")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2.plot(common_pos, delta, color="tab:red")
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.fill_between(common_pos, delta, 0, where=(delta > 0), color="red", alpha=0.2, label=f"Круг {LAP_B_NUM} медленнее")
    ax2.fill_between(common_pos, delta, 0, where=(delta < 0), color="green", alpha=0.2, label=f"Круг {LAP_B_NUM} быстрее")
    ax2.set_ylabel(f"Дельта (B - A), сек")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    ax3.plot(common_pos, speed_a_interp, label=f"Круг {LAP_A_NUM}", color="tab:blue")
    ax3.plot(common_pos, speed_b_interp, label=f"Круг {LAP_B_NUM}", color="tab:orange")
    ax3.set_ylabel("Скорость, км/ч")
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    ax4.plot(common_pos, gas_a_interp, label=f"Круг {LAP_A_NUM}", color="tab:blue")
    ax4.plot(common_pos, gas_b_interp, label=f"Круг {LAP_B_NUM}", color="tab:orange")
    ax4.set_ylabel("Газ (0-1)")
    ax4.legend()
    ax4.grid(True, alpha=0.3)

    ax5.plot(common_pos, brake_a_interp, label=f"Круг {LAP_A_NUM}", color="tab:blue")
    ax5.plot(common_pos, brake_b_interp, label=f"Круг {LAP_B_NUM}", color="tab:orange")
    ax5.set_ylabel("Тормоз (0-1)")
    ax5.set_xlabel("Позиция на круге (развёрнутая, от старта)")
    ax5.legend()
    ax5.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()

    print(f"Круг {LAP_A_NUM}: {lap_a_total:.3f} сек")
    print(f"Круг {LAP_B_NUM}: {lap_b_total:.3f} сек")
    print(f"Разница: {lap_b_total - lap_a_total:+.3f} сек")


if __name__ == "__main__":
    main()
