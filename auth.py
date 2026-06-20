import hashlib
import os
import re
import streamlit as st
from database import create_user, get_user, get_user_security, update_password

SECURITY_QUESTIONS = [
    "What was the name of your first pet?",
    "What is your mother's maiden name?",
    "What city were you born in?",
    "What was the name of your first school?",
    "What is your oldest sibling's middle name?",
]

# ── Password hashing ──────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return salt.hex() + ":" + key.hex()

def verify_password(plain_password: str, stored_hash: str) -> bool:
    try:
        salt_hex, key_hex = stored_hash.split(":")
        salt = bytes.fromhex(salt_hex)
        key = hashlib.pbkdf2_hmac("sha256", plain_password.encode(), salt, 100000)
        return key.hex() == key_hex
    except Exception:
        return False

# ── Input validation ──────────────────────────────────────────

def validate_username(username: str) -> tuple:
    username = username.strip().lower()
    if len(username) < 3:
        return False, "Username must be at least 3 characters"
    if len(username) > 20:
        return False, "Username must be under 20 characters"
    if " " in username:
        return False, "Username cannot contain spaces"
    if not re.match(r'^[a-z0-9_-]+$', username):
        return False, "Username can only contain letters, numbers, underscores, and hyphens"
    return True, username

def validate_password(password: str) -> tuple:
    if len(password) < 6:
        return False, "Password must be at least 6 characters"
    if len(password) > 72:
        return False, "Password must be under 72 characters"
    return True, ""

# ── Brute force protection ────────────────────────────────────

def get_failed_attempts(username: str) -> int:
    key = f"failed_attempts_{username}"
    return st.session_state.get(key, 0)

def increment_failed_attempts(username: str):
    key = f"failed_attempts_{username}"
    st.session_state[key] = st.session_state.get(key, 0) + 1

def reset_failed_attempts(username: str):
    key = f"failed_attempts_{username}"
    st.session_state[key] = 0

def is_locked_out(username: str) -> bool:
    return get_failed_attempts(username) >= 5

# ── Core auth functions ───────────────────────────────────────

def register_user(username: str, password: str, security_question: str, security_answer: str) -> tuple:
    valid, result = validate_username(username)
    if not valid:
        return False, result
    clean_username = result

    valid, error = validate_password(password)
    if not valid:
        return False, error

    if not security_answer or len(security_answer.strip()) < 2:
        return False, "Please provide a security answer"

    password_hash = hash_password(password)
    answer_hash = hash_password(security_answer.strip().lower())

    success = create_user(clean_username, password_hash, security_question, answer_hash)

    if success:
        return True, f"Account created! Welcome, {clean_username}"
    else:
        return False, "Username already taken. Try a different one."

def login_user(username: str, password: str) -> tuple:
    if not username or not password:
        return False, "Please enter both username and password"

    clean_username = username.strip().lower()

    if is_locked_out(clean_username):
        return False, "Too many failed attempts. Close and reopen the app to try again."

    user = get_user(clean_username)
    if not user:
        increment_failed_attempts(clean_username)
        return False, "Invalid username or password"

    stored_username, stored_hash = user

    if verify_password(password, stored_hash):
        reset_failed_attempts(clean_username)
        return True, stored_username
    else:
        increment_failed_attempts(clean_username)
        attempts_left = 5 - get_failed_attempts(clean_username)
        if attempts_left <= 0:
            return False, "Too many failed attempts. Close and reopen the app to try again."
        return False, f"Invalid username or password. {attempts_left} attempts remaining."

def get_security_question(username: str) -> tuple:
    clean_username = username.strip().lower()
    row = get_user_security(clean_username)
    if not row:
        return False, "Username not found"
    return True, row[0]

def reset_password(username: str, security_answer: str, new_password: str) -> tuple:
    clean_username = username.strip().lower()

    row = get_user_security(clean_username)
    if not row:
        return False, "Username not found"

    _, stored_answer_hash = row

    if not verify_password(security_answer.strip().lower(), stored_answer_hash):
        return False, "Security answer is incorrect"

    valid, error = validate_password(new_password)
    if not valid:
        return False, error

    new_hash = hash_password(new_password)
    success = update_password(clean_username, new_hash)

    if success:
        return True, "Password updated successfully. Please log in."
    else:
        return False, "Something went wrong. Try again."