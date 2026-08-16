"""Pure account validation, PIN hashing, and short-login token helpers."""

import hashlib
import hmac
import re
import secrets
import time


def normalized_hero_name(name):
    return name.casefold()


def validate_public_hero_name(name, blocked_words):
    if not name:
        return "請輸入勇者名稱。"
    if not re.fullmatch(r"[A-Za-z0-9\u3400-\u4DBF\u4E00-\u9FFF]+", name):
        return "勇者名稱只能使用中文、英文字母與數字，不能包含空格或符號。"
    normalized = normalized_hero_name(name)
    if any(word in normalized for word in blocked_words):
        return "此勇者名稱含有不適合公開顯示的文字，請更換名稱。"
    return None


def student_code_for_number(number):
    group = (number - 1) // 999
    if group >= 26:
        raise ValueError("學生編號已超過 A001～Z999 的容量")
    letter = chr(ord("A") + group)
    sequence = (number - 1) % 999 + 1
    return f"{letter}{sequence:03d}"


def pin_digest(pin, salt_hex):
    return hashlib.scrypt(
        pin.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1
    ).hex()


def make_pin_hash(pin):
    salt = secrets.token_bytes(16).hex()
    return salt, pin_digest(pin, salt)


def create_short_login_token(student_code, secret, lifetime_seconds, now=None):
    current_time = int(time.time() if now is None else now)
    expires_at = current_time + int(lifetime_seconds)
    payload = f"{student_code}.{expires_at}"
    signature = hmac.new(
        str(secret).encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{signature}"


def validate_short_login_token(token, secret, player_exists, now=None):
    try:
        student_code, expires_text, signature = token.rsplit(".", 2)
        payload = f"{student_code}.{expires_text}"
        expected = hmac.new(
            str(secret).encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        current_time = int(time.time() if now is None else now)
        if not hmac.compare_digest(signature, expected) or int(expires_text) < current_time:
            return None
        if student_code == "__TEACHER__":
            return None
        return student_code if player_exists(student_code) else None
    except (AttributeError, TypeError, ValueError):
        return None
