import json
import os

from groq import Groq

_client = None

PROMPT = """You are the understanding layer of a meeting-booking assistant.
Today is {today} ({weekday}). User timezone: {tz}.
Details known so far (JSON): {draft}
Screen state: {state}

The user may write in English, Hindi (Devanagari) or Hinglish. Resolve relative dates
("kal" = tomorrow, "parso" = day after tomorrow, "next Monday") into YYYY-MM-DD.

Return ONLY a JSON object with these keys:
- "action": one of
        "confirm" -> ONLY if the screen state says a slot is already selected AND the message is just an
                     approval (e.g. "confirm", "book it", "yes go ahead", "haan book kar do").
                     A message that gives a date or time (e.g. "Book a meeting at 3 PM on 29 October")
                     is NOT confirm, even though it contains the word "book".
    "change_time" -> the user wants a different time or date ("change the time", "make it 3 pm",
                     "another slot", "kal rakho", "samay badlo")
    "none"        -> anything else, including a first request to book a meeting
- "name": string or null
- "email": string or null. Spoken "riya at gmail dot com" -> riya@gmail.com. Always lowercase, no spaces.
- "date": "YYYY-MM-DD" or null
- "time": "HH:MM" in 24-hour format, or null
- "part_of_day": "morning" | "afternoon" | "evening" | null
- "language": "hi-IN" if the user wrote or spoke Hindi/Hinglish, otherwise "en-IN"
- "reply": one or two friendly sentences in the user's own language. Say what you understood and
  ask for what is still missing (date first, then time).

Only fill name/email/date/time/part_of_day if the user stated or changed it in THIS message;
otherwise null. Never invent values. Return JSON only.

User message: {message}"""


def extract_booking_details(message, now, tz_name, draft, state):
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    prompt = PROMPT.format(
        today=now.strftime("%Y-%m-%d"),
        weekday=now.strftime("%A"),
        tz=tz_name,
        draft=json.dumps(draft),
        state=state,
        message=message,
    )
    resp = _client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(resp.choices[0].message.content.strip())