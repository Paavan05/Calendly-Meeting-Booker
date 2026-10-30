import base64
import html
import os
import re
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv

from calendly_client import (
    CalendlyError,
    book_via_api,
    get_available_slots,
    get_event_type,
    prefilled_link,
)
from llm import extract_booking_details
from sarvam_stt import transcribe
from sarvam_tts import tts
from voice_input import voice_bar

load_dotenv(override=True)
TZ_NAME = os.getenv("USER_TZ", "Asia/Kolkata")
TZ = ZoneInfo(TZ_NAME)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DETAIL_KEYS = ("name", "email", "date", "time", "part_of_day")
MIN_AUDIO_BYTES = 6000  # ~0.2 s of 16 kHz speech; anything smaller is treated as empty

st.set_page_config(page_title="Book a meeting", layout="centered")

st.markdown(
    """
    <style>
    /* hide Streamlit chrome */
    [data-testid="stDeployButton"], [data-testid="stMainMenu"], #MainMenu, footer { display: none !important; }
    [data-testid="stMainBlockContainer"], .block-container { padding-top: 3rem; padding-bottom: 140px; }

    /* chat bubbles */
    .chat { display: flex; flex-direction: column; gap: 10px; margin: 6px 0 22px 0; }
    .msg { max-width: 80%; padding: 10px 15px; border-radius: 16px; line-height: 1.5; overflow-wrap: anywhere; }
    .msg.me { align-self: flex-end; background: rgba(128,128,128,.22); border-bottom-right-radius: 5px; }
    .msg.bot { align-self: flex-start; border: 1px solid rgba(128,128,128,.3); border-bottom-left-radius: 5px; }

    /* the input bar (a component iframe) is pinned to the bottom of the page */
    iframe[title*="voice_loop"], iframe[data-voice-bar] {
        position: fixed !important; left: 50% !important; bottom: 22px !important; top: auto !important;
        transform: translateX(-50%) !important;
        width: min(704px, calc(100vw - 32px)) !important; height: 60px !important;
        border: 0 !important; border-radius: 16px !important; z-index: 1000 !important;
        box-shadow: 0 6px 24px rgba(0,0,0,.35);
    }
    [data-testid="stElementContainer"]:has(iframe[title*="voice_loop"]),
    [data-testid="stElementContainer"]:has(iframe[data-voice-bar]),
    .element-container:has(iframe[title*="voice_loop"]) {
        height: 0 !important; min-height: 0 !important; margin: 0 !important;
        opacity: 1 !important; transition: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

voice_slot = st.container()  # the input bar lives here (always the first element, so it is never remounted)

ss = st.session_state
ss.setdefault("messages", [])
ss.setdefault("draft", {k: None for k in DETAIL_KEYS})
ss.setdefault("slot", None)
ss.setdefault("booked", None)
ss.setdefault("pending_confirm", False)
ss.setdefault("lang", "en-IN")
ss.setdefault("speak_event", None)  # one-shot: what to say at the end of the next run
ss.setdefault("last_event_id", None)  # last event already handled from the input bar
ss.setdefault("ack_id", None)  # last event taken in (lets the bar carry on)
ss.setdefault("fail_count", 0)  # consecutive failed transcriptions

speak_now = None
slot_issue = None


# ---------- text helpers ----------
def clean_email(raw):
    """'John at the rate Gmail dot com' -> 'john@gmail.com'"""
    if not raw:
        return None
    e = " " + raw.strip().lower() + " "
    for phrase in (" at the rate of ", " at the rate ", " at-the-rate ", " attherate "):
        e = e.replace(phrase, "@")
    if "@" not in e:
        e = re.sub(r"\s+at\s+", "@", e)
    e = re.sub(r"\s+dot\s+", ".", e)
    e = re.sub(r"\s+(underscore|under score)\s+", "_", e)
    e = re.sub(r"\s+(dash|hyphen)\s+", "-", e)
    e = re.sub(r"\s+", "", e)
    return e.strip(".,;:!?") or None


def local(slot):
    return datetime.fromisoformat(slot["start"].replace("Z", "+00:00")).astimezone(TZ)


def minutes(hhmm):
    try:
        h, m = map(int, hhmm.split(":")[:2])
        return h * 60 + m
    except Exception:
        return None


def spoken_email(e):
    return e.replace("@", " at ").replace(".", " dot ").replace("_", " underscore ").replace("-", " dash ")


def when_text(slot):
    dt = local(slot)
    return f"{dt.day} {dt:%B %Y}", dt.strftime("%I:%M %p").lstrip("0")


def readback_text(name, email, slot, lang):
    d, t = when_text(slot)
    if lang == "hi-IN":
        return f"{name} के लिए मीटिंग। ईमेल आईडी {spoken_email(email)}। तारीख {d}, समय {t}। बुक करने के लिए कन्फर्म बोलिए।"
    return f"Meeting for name {name}, mail ID {spoken_email(email)}, on {d} at {t}. Say confirm to book it."


def booked_text(name, email, slot, lang):
    d, t = when_text(slot)
    if lang == "hi-IN":
        return f"आपकी मीटिंग बुक हो गई है। नाम {name}, ईमेल आईडी {spoken_email(email)}, तारीख {d}, समय {t}।"
    return f"Your meeting is booked for name {name}, mail ID {spoken_email(email)}, on {d} at {t}."


LABELS = {
    "en-IN": {"name": "your name", "email": "your email address", "date": "the date", "time": "the time"},
    "hi-IN": {"name": "आपका नाम", "email": "आपका ईमेल", "date": "तारीख", "time": "समय"},
}
ISSUES = {
    "en-IN": {
        "past_date": "That date has already passed.",
        "bad_date": "I couldn't understand the date.",
        "no_slots": "There are no open slots for that day or time.",
        "time_unavailable": "That time isn't available. Please pick one of the open slots shown on the screen.",
        "bad_email": "That email address doesn't look valid.",
    },
    "hi-IN": {
        "past_date": "यह तारीख बीत चुकी है।",
        "bad_date": "मैं तारीख समझ नहीं पाया।",
        "no_slots": "उस दिन या समय के लिए कोई स्लॉट खाली नहीं है।",
        "time_unavailable": "वह समय उपलब्ध नहीं है। कृपया स्क्रीन पर दिखाए गए स्लॉट में से चुनें।",
        "bad_email": "यह ईमेल सही नहीं लग रहा।",
    },
}
PHRASES = {
    "en-IN": {
        "change_time": "Sure. Please pick a new time from the open slots, or tell me the time you want.",
        "llm_error": "Sorry, I couldn't understand that. Please try again.",
        "heard_nothing": "Sorry, I couldn't hear that clearly. Please try again.",
        "trouble": "I'm having trouble hearing you. Tap the mic when you're ready, or type your message.",
        "booking_failed": "Sorry, the booking didn't go through. Please try again in a moment.",
        "new_meeting": "Okay. Tell me the details for the new meeting.",
    },
    "hi-IN": {
        "change_time": "ठीक है। कृपया खाली स्लॉट में से नया समय चुनिए, या बताइए कि आपको कौन सा समय चाहिए।",
        "llm_error": "माफ़ कीजिए, मैं समझ नहीं पाया। कृपया दोबारा कोशिश कीजिए।",
        "heard_nothing": "माफ़ कीजिए, मैं साफ़ सुन नहीं पाया। कृपया दोबारा बोलिए।",
        "trouble": "मुझे आपकी आवाज़ सुनने में दिक्कत हो रही है। तैयार होकर माइक दबाइए, या अपना संदेश टाइप कीजिए।",
        "booking_failed": "माफ़ कीजिए, बुकिंग नहीं हो पाई। कृपया थोड़ी देर बाद फिर कोशिश कीजिए।",
        "new_meeting": "ठीक है। नई मीटिंग की जानकारी बताइए।",
    },
}


def join_items(items, lang):
    if len(items) == 1:
        return items[0]
    word = " और " if lang == "hi-IN" else " and "
    return ", ".join(items[:-1]) + word + items[-1]


def status_text(slot_issue, lang):
    """Full read-back if everything is ready; otherwise say what is wrong or missing."""
    d = ss.draft
    name = (d["name"] or "").strip()
    email = clean_email(d["email"]) if d["email"] else None

    parts, missing = [], []
    if slot_issue in ISSUES[lang]:
        parts.append(ISSUES[lang][slot_issue])
    if not name:
        missing.append("name")
    if not email:
        missing.append("email")
    elif not EMAIL_RE.match(email):
        parts.append(ISSUES[lang]["bad_email"])
    if not d["date"] or slot_issue in ("past_date", "bad_date"):
        missing.append("date")
    if ss.slot is None and not d["time"]:
        missing.append("time")

    if not missing and not parts and ss.slot is not None:
        return readback_text(name, email, ss.slot, lang)

    sentence = " ".join(parts)
    if missing:
        items = [LABELS[lang][m] for m in missing]
        if lang == "hi-IN":
            sentence += f" मुझे अभी {join_items(items, lang)} चाहिए।"
        else:
            sentence += f" I still need {join_items(items, lang)}."
    return sentence.strip() or ("कृपया विवरण बताइए।" if lang == "hi-IN" else "Please tell me the meeting details.")


# ---------- speech ----------
def build_speech():
    """Turn the queued speak_event into audio for the input bar (or None)."""
    ev = speak_now
    if not ev:
        return None
    lang = ss.lang
    if ev["kind"] == "status":
        text = status_text(slot_issue, lang)
    elif ev.get("text"):
        text = ev["text"]
    else:
        text = PHRASES[lang][ev["key"]]
    try:
        wav = tts(text, lang)
    except Exception:
        return None
    return {"id": uuid.uuid4().hex, "audio": base64.b64encode(wav).decode(), "final": bool(ev.get("final"))}


def finish():
    """Render the input bar once per run, with whatever it should say."""
    payload = build_speech()
    with voice_slot:
        voice_bar(speak=payload, ack=ss.ack_id, tick=len(ss.messages))


# ---------- data ----------
@st.cache_resource
def load_event_type():
    return get_event_type()


@st.cache_data(ttl=60)
def load_slots(event_uri, day_iso, tz_name):
    return get_available_slots(event_uri, date.fromisoformat(day_iso), ZoneInfo(tz_name))


def screen_state():
    if ss.booked:
        return "A meeting was just booked."
    if ss.slot is not None:
        return f"A slot is selected: {local(ss.slot):%A %d %B %Y at %I:%M %p}."
    return "No time slot is selected yet."


def reset_booking():
    ss.draft = {k: None for k in DETAIL_KEYS}
    ss.slot = None
    ss.booked = None


def handle_message(text):
    ss.messages.append({"role": "user", "content": text})
    try:
        result = extract_booking_details(text, datetime.now(TZ), TZ_NAME, ss.draft, screen_state())
    except Exception as e:
        ss.messages.append({"role": "assistant", "content": f"Sorry, I couldn't understand that ({e}). Please try again."})
        ss.speak_event = {"kind": "text", "key": "llm_error"}
        return

    action = result.get("action") or "none"
    reply = result.get("reply") or "Got it."
    if result.get("language") in ("en-IN", "hi-IN"):
        ss.lang = result["language"]

    # After a finished booking: new details start a fresh booking, anything else is ignored.
    if ss.booked:
        if any(result.get(k) for k in DETAIL_KEYS) and action != "confirm":
            reset_booking()
        else:
            ss.messages.append({"role": "assistant", "content": reply})
            return

    # "confirm" only makes sense if a slot is already selected
    if action == "confirm" and ss.slot is None:
        action = "none"

    for key in DETAIL_KEYS:
        value = result.get(key)
        if not value:
            continue
        if key == "email":
            value = clean_email(value)
            if not value:
                continue
        if action == "confirm" and key in ("date", "time", "part_of_day"):
            continue  # confirming must never move the selected slot
        if key in ("date", "time", "part_of_day") and value != ss.draft[key]:
            ss.slot = None
        ss.draft[key] = value

    # a new exact time replaces an old part-of-day, and the other way round
    if action != "confirm":
        if result.get("time"):
            ss.draft["part_of_day"] = None
        elif result.get("part_of_day"):
            ss.draft["time"] = None

    # "change the time" with no new time -> show all slots again
    if action == "change_time" and not (result.get("time") or result.get("part_of_day") or result.get("date")):
        ss.slot = None
        ss.draft["time"] = None
        ss.draft["part_of_day"] = None

    if action == "confirm":
        ss.pending_confirm = True
        reply = "Confirming your booking."
    else:
        ss.speak_event = {"kind": "status"}  # read back the details, or say what is missing

    ss.messages.append({"role": "assistant", "content": reply})


def bubble(m):
    cls = "me" if m["role"] == "user" else "bot"
    body = html.escape(m["content"]).replace("\n", "<br>")
    return f'<div class="msg {cls}">{body}</div>'


# ---------- page header ----------
st.title("Book a meeting")

try:
    event = load_event_type()
except CalendlyError as e:
    st.error(str(e))
    finish()
    st.stop()

st.caption(f"{event['duration']}-minute meeting · {TZ_NAME}")

# ---------- events from the input bar ----------
voice_wav = None
typed = ""
vv = ss.get("voice_bar")  # the bar's latest event (set by the browser before this run started)
if isinstance(vv, dict) and vv.get("id") and vv["id"] != ss.last_event_id:
    ss.last_event_id = vv["id"]
    ss.ack_id = vv["id"]  # mark as taken in immediately, so it can never be processed twice
    if vv.get("event") == "text":
        typed = (vv.get("text") or "").strip()
    elif vv.get("event") == "audio" and vv.get("b64"):
        try:
            voice_wav = base64.b64decode(vv["b64"])
        except Exception:
            voice_wav = b""

# ---------- handle what you said ----------
if voice_wav is not None:
    spoken, err = None, None
    if len(voice_wav) < MIN_AUDIO_BYTES:
        err = f"The recording was empty or too short ({len(voice_wav)} bytes)."
    else:
        with st.spinner("Transcribing"):
            try:
                spoken = transcribe(voice_wav)
            except Exception as e:
                err = str(e)
        if not spoken and not err:
            err = "No speech was detected in the recording."
    if spoken:
        ss.fail_count = 0
        handle_message(spoken)
    else:
        ss.fail_count += 1
        ss.messages.append({"role": "assistant", "content": f"I couldn't use that recording. {err}"})
        if ss.fail_count >= 2:  # stop the listen-fail-listen loop in a noisy room
            ss.fail_count = 0
            ss.speak_event = {"kind": "text", "key": "trouble", "final": True}
        else:
            ss.speak_event = {"kind": "text", "key": "heard_nothing"}

if typed:
    handle_message(typed)

# ---------- conversation ----------
if ss.messages:
    st.markdown(f'<div class="chat">{"".join(bubble(m) for m in ss.messages)}</div>', unsafe_allow_html=True)

# Consume one-shot flags right away so they can never fire in a later run.
speak_now = ss.speak_event
ss.speak_event = None
confirm_requested = ss.pending_confirm
ss.pending_confirm = False
slot_issue = None

# ---------- booking panel ----------
d = ss.draft

if ss.booked:
    st.success("Your meeting is booked. A confirmation has been sent to your email.")
    links = []
    if ss.booked.get("reschedule_url"):
        links.append(f"[Reschedule]({ss.booked['reschedule_url']})")
    if ss.booked.get("cancel_url"):
        links.append(f"[Cancel]({ss.booked['cancel_url']})")
    if links:
        st.markdown(" · ".join(links))
    if st.button("Book another meeting"):
        reset_booking()
        ss.speak_event = {"kind": "text", "key": "new_meeting"}
        st.rerun()
    finish()
    st.stop()

if d["date"]:
    try:
        day = date.fromisoformat(d["date"])
    except ValueError:
        day = None

    if day is None:
        slot_issue = "bad_date"
        st.warning("I couldn't read that date. Please tell me the date again.")
    elif day < datetime.now(TZ).date():
        slot_issue = "past_date"
        st.warning("That date has already passed. Please choose another day.")
    else:
        try:
            slots = load_slots(event["uri"], day.isoformat(), TZ_NAME)
        except CalendlyError as e:
            st.error(str(e))
            slots = []

        ranges = {"morning": (0, 12), "afternoon": (12, 17), "evening": (17, 24)}
        if d["part_of_day"] in ranges:
            lo, hi = ranges[d["part_of_day"]]
            slots = [s for s in slots if lo <= local(s).hour < hi]

        wanted = minutes(d["time"]) if d["time"] else None
        if wanted is not None:
            slots.sort(key=lambda s: abs(local(s).hour * 60 + local(s).minute - wanted))
            if ss.slot is None:
                for s in slots:
                    if local(s).hour * 60 + local(s).minute == wanted:
                        ss.slot = s
                        break

        if ss.slot is None:
            if not slots:
                slot_issue = "no_slots"
                st.info(f"No open slots on {day:%A}, {day.day} {day:%B}. Please try another day or time.")
            else:
                if wanted is not None:
                    slot_issue = "time_unavailable"
                st.markdown(f"**Available times on {day:%A}, {day.day} {day:%B}**")
                cols = st.columns(4)
                for i, s in enumerate(slots):
                    label = local(s).strftime("%I:%M %p").lstrip("0")
                    if cols[i % 4].button(label, key=f"slot{i}{s['start']}"):
                        ss.slot = s
                        ss.speak_event = {"kind": "status"}
                        st.rerun()
        else:
            slot = ss.slot
            dt = local(slot)
            with st.container(border=True):
                st.markdown(
                    f"**{dt:%A}, {dt.day} {dt:%B %Y}** at **{dt.strftime('%I:%M %p').lstrip('0')}** "
                    f"({event['duration']} minutes)"
                )
                name = st.text_input("Name", value=d["name"] or "").strip()
                email = clean_email(st.text_input("Email", value=d["email"] or "")) or ""
                email_ok = bool(EMAIL_RE.match(email))
                if email and not email_ok:
                    st.warning("That email address doesn't look valid.")

                # keep the saved details in sync with what is in the boxes
                ss.draft["name"] = name or None
                ss.draft["email"] = email or None

                c1, c2 = st.columns(2)
                change = c1.button("Change time")
                clicked = c2.button("Confirm booking", type="primary")

            if change:
                ss.slot = None
                ss.draft["time"] = None
                ss.draft["part_of_day"] = None
                ss.speak_event = {"kind": "text", "key": "change_time"}
                st.rerun()

            if clicked or confirm_requested:
                if not (name and email_ok):
                    st.warning("Please add a name and a valid email first.")
                    speak_now = {"kind": "status"}  # say out loud what is missing
                else:
                    with st.spinner("Booking your meeting"):
                        ok, info = book_via_api(
                            event["uri"], slot["start"], name, email, TZ_NAME, event["locations"]
                        )
                    if ok:
                        ss.booked = info
                        ss.speak_event = {
                            "kind": "text",
                            "text": booked_text(name, email, slot, ss.lang),
                            "final": True,  # the mic pauses after the booking is announced
                        }
                        st.rerun()
                    st.error(f"The booking could not be completed: {info}")
                    speak_now = {"kind": "text", "key": "booking_failed"}
                    if slot.get("url"):
                        st.link_button("Finish on Calendly", prefilled_link(slot["url"], name, email))

# ---------- draw the input bar (and speak, once per run) ----------
finish()