"""Question generation for every math unit.

This module deliberately has no Streamlit or database imports. Keeping question
generation pure makes it easier to test answers and add future units safely.
"""

import math
import random


def make_question(unit_id):
    if unit_id == "5-1":
        while True:
            common = random.randint(1, 30)
            left_factor, right_factor = random.sample(range(1, 16), 2)
            if math.gcd(left_factor, right_factor) != 1:
                continue
            left, right = common * left_factor, common * right_factor
            if left <= 200 and right <= 200:
                return {
                    "text": f"（{left}，{right}）的最大公因數 ＝ ?",
                    "answer": common,
                }
    if unit_id == "5-2":
        while True:
            left, right = random.sample(range(2, 51), 2)
            answer = math.lcm(left, right)
            if answer <= 200:
                return {
                    "text": f"（{left}，{right}）的最小公倍數 ＝ ?",
                    "answer": answer,
                }
    if unit_id == "5-3":
        while True:
            answer_numerator = random.randint(1, 50)
            answer_denominator = random.randint(2, 50)
            if math.gcd(answer_numerator, answer_denominator) != 1:
                continue
            max_factor = min(100 // answer_numerator, 100 // answer_denominator)
            if max_factor < 2:
                continue
            factor = random.randint(2, max_factor)
            numerator = answer_numerator * factor
            denominator = answer_denominator * factor
            return {
                "text": f"{numerator}／{denominator} ＝（　）／（　）",
                "answer": answer_numerator / answer_denominator,
                "question_numerator": numerator,
                "question_denominator": denominator,
                "answer_numerator": answer_numerator,
                "answer_denominator": answer_denominator,
                "fraction": True,
            }
    if unit_id == "4-1":
        a_tenths, multiplier = random.randint(1, 99), random.randint(2, 9)
        return {"text": f"{a_tenths / 10:.1f} × {multiplier} ＝ ?", "answer": round(a_tenths * multiplier / 10, 2)}
    if unit_id == "4-2":
        a_tenths, b_tenths = random.randint(1, 99), random.randint(1, 9)
        return {"text": f"{a_tenths / 10:.1f} × {b_tenths / 10:.1f} ＝ ?", "answer": round(a_tenths * b_tenths / 100, 2)}
    if unit_id == "4-3":
        divisor = random.randint(2, 9)
        quotient_tenths = random.randint(1, 50)
        dividend_tenths = divisor * quotient_tenths
        return {"text": f"{dividend_tenths / 10:.1f} ÷ {divisor} ＝ ?", "answer": round(quotient_tenths / 10, 2)}
    if unit_id == "4-4":
        divisor_tenths = random.randint(1, 9)
        quotient = random.randint(1, max(1, 99 // divisor_tenths))
        dividend_tenths = divisor_tenths * quotient
        return {"text": f"{dividend_tenths / 10:.1f} ÷ {divisor_tenths / 10:.1f} ＝ ?", "answer": quotient}
    if unit_id == "3-1":
        add = random.choice([True, False])
        a = random.randint(10, 199) / 10
        b = random.randint(1, 99) / 10 if unit_id == "3-1" else random.randint(1, 999) / 100
        if not add and b > a:
            a, b = b, a
        answer = a + b if add else a - b
        symbol = "＋" if add else "－"
        a_text = f"{a:.1f}"
        b_text = f"{b:.1f}" if unit_id == "3-1" else f"{b:.2f}"
        return {"text": f"{a_text} {symbol} {b_text} ＝ ?", "answer": round(answer, 2)}
    if unit_id == "3-2":
        add = random.choice([True, False])
        # Integer hundredths keep the displayed values and answer identical.
        a_hundredths = random.randint(10, 199) * 10
        max_b = 999 if add else min(999, a_hundredths)
        # Avoid a zero hundredths digit (for example 1.10 or 8.60).
        b_hundredths = random.choice(
            [value for value in range(1, max_b + 1) if value % 10 != 0]
        )
        answer_hundredths = (
            a_hundredths + b_hundredths if add else a_hundredths - b_hundredths
        )
        symbol = "+" if add else "−"
        return {
            "text": (
                f"{a_hundredths / 100:.1f} {symbol} "
                f"{b_hundredths / 100:.2f} = ?"
            ),
            "answer": answer_hundredths / 100,
        }
    if unit_id == "2-1":
        a, b = random.randint(10, 99), random.randint(2, 9)
        return {"text": f"{a} × {b} ＝ ?", "answer": a * b}
    if unit_id == "2-2":
        divisor = random.randint(2, 9)
        quotient = random.randint(math.ceil(10 / divisor), math.floor(99 / divisor))
        dividend = divisor * quotient
        return {"text": f"{dividend} ÷ {divisor} ＝ ?", "answer": quotient}
    if unit_id == "2-3":
        a, b = random.randint(100, 999), random.randint(2, 9)
        return {"text": f"{a} × {b} ＝ ?", "answer": a * b}
    if unit_id == "2-4":
        divisor = random.randint(2, 9)
        quotient = random.randint(math.ceil(100 / divisor), math.floor(999 / divisor))
        dividend = divisor * quotient
        return {"text": f"{dividend} ÷ {divisor} ＝ ?", "answer": quotient}
    add = random.choice([True, False])
    if unit_id == "1-1":
        a, b = random.randint(10, 99), random.randint(1, 9)
    elif unit_id == "1-2":
        a, b = random.randint(10, 99), random.randint(10, 99)
    else:
        a, b = random.randint(100, 999), random.randint(10, 99)
    if add:
        return {"text": f"{a} ＋ {b} ＝ ?", "answer": a + b}
    a, b = max(a, b), min(a, b)
    return {"text": f"{a} － {b} ＝ ?", "answer": a - b}
