# Voice Meeting Booker

A web app that books Calendly meetings from a typed or spoken request. Say or type something like *"Book a meeting on 3 November at 4 pm, my name is Om and my email is om@gmail.com"*, and the app checks Calendly for open slots, reads the details back to you, and books the meeting once you confirm.

It understands English, Hindi and Hinglish, and it answers out loud.

## Features

- **Type or talk.** One input bar with a text field, a mic button and a send button.
- **Hands-free voice.** Tap the mic once. The app listens, sends your sentence when you stop talking, speaks its reply, and starts listening again by itself. Clicking into the text field turns the mic off.
- **English, Hindi and Hinglish.** Speech is transcribed with Sarvam AI. Relative dates such as "kal" or "next Monday" are understood.
- **Real availability.** Open slots are read from your Calendly event type, so only free times can be booked.
- **Spoken read-back.** After every message the app reads out the full details, or says exactly which field is missing (name, email, date or time).
- **Voice commands.** Say "make it 3 pm" to change the time, or "confirm" to book.
- **Clean email handling.** Spoken emails such as "john at the rate gmail dot com" become `john@gmail.com`, lowercase with no spaces. Invalid emails block booking.
- **Fallback link.** If Calendly's booking API refuses the request, the app offers a prefilled Calendly link for that exact slot.

## How it works

```
 type or speak
      |
      v
 Sarvam speech-to-text  (voice only)
      |
      v
 Groq LLM extracts name, email, date, time and intent (confirm / change time)
      |
      v
 Calendly API: available times for that day
      |
      v
 Read-back of the details (Sarvam text-to-speech)
      |
      v
 "Confirm"  ->  Calendly API creates the booking  ->  spoken confirmation
```

## Tech stack

| Part | Technology |
| --- | --- |
| UI and app logic | Python, [Streamlit](https://streamlit.io) |
| Input bar (mic, voice activity detection, text field) | Custom Streamlit component in plain JavaScript (Web Audio API) |
| Speech-to-text and text-to-speech | [Sarvam AI](https://www.sarvam.ai) |
| Language understanding | [Groq](https://groq.com) (Llama models) |
| Scheduling | [Calendly API](https://developer.calendly.com) |

## Project structure

```
meeting-booker/
├── app.py                    # Streamlit app: conversation, booking panel, speech
├── voice_input.py            # Python wrapper for the custom input-bar component
├── voice_component/
│   └── index.html            # Input bar: text field, mic, send, voice activity detection
├── calendly_client.py        # Calendly API: event type, available slots, booking
├── sarvam_stt.py             # Sarvam speech-to-text
├── sarvam_tts.py             # Sarvam text-to-speech
├── llm.py                    # Groq: turns a message into structured booking details
├── requirements.txt
├── .env.example
└── README.md
```

## Getting started

### Prerequisites

- Python 3.10 or newer
- A Calendly account with at least one active event type
- A [Sarvam AI](https://www.sarvam.ai) API key
- A [Groq](https://console.groq.com) API key

### Installation

```bash
git clone https://github.com/Paavan05/calendly-meeting-booker.git
cd calendly-meeting-booker

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

`requirements.txt`:

```
streamlit>=1.40
requests
python-dotenv
groq
```

### Configuration

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

| Variable | Required | Description |
| --- | --- | --- |
| `CALENDLY_TOKEN` | Yes | Calendly Personal Access Token |
| `SARVAM_API_KEY` | Yes | Sarvam AI API key (used for speech-to-text and text-to-speech) |
| `GROQ_API_KEY` | Yes | Groq API key |
| `GROQ_MODEL` | No | Groq model name. Default: `llama-3.3-70b-versatile` |
| `USER_TZ` | No | Timezone for dates and times. Default: `Asia/Kolkata` |
| `SARVAM_TTS_MODEL` | No | Text-to-speech model. Default: `bulbul:v3` |
| `SARVAM_TTS_SPEAKER` | No | Text-to-speech voice. Default: `shubh` |

Example `.env`:

```dotenv
CALENDLY_TOKEN=your_calendly_personal_access_token
SARVAM_API_KEY=your_sarvam_key
GROQ_API_KEY=your_groq_key
GROQ_MODEL=openai/gpt-oss-120b
USER_TZ=Asia/Kolkata
```

**Getting a Calendly token:** log in to Calendly, open **Integrations**, then **API and webhooks**, and generate a Personal Access Token under *Personal Access Tokens*. Copy it straight away, because Calendly does not show it again. The token is a long string that starts with `eyJ`. It is not your booking page URL.

### Run

```bash
streamlit run app.py
```

Open the app at `http://localhost:8501`.

## Usage

1. Tap the mic button and speak, or type in the text field and press Enter.
2. Give the meeting details in one sentence or over several. The app tells you what is still missing.
3. When everything is filled in, the app reads the details back. Say or type **confirm**, or press **Confirm booking**.
4. The app announces the booking. Reschedule and cancel links are shown on screen.

Useful phrases:

| You say | What happens |
| --- | --- |
| "Book a meeting tomorrow at 4 pm" | Finds and selects the 4 pm slot |
| "Make it 5 pm" / "Change the time" | Changes the slot, or shows all open slots |
| "Confirm" / "Book it" | Books the selected slot |
| "कल दोपहर 3 बजे मीटिंग बुक करो" | Works in Hindi too |

## Calendly plan notes

- Booking through the API (`POST /invitees`) is limited to paid Calendly plans. Calendly documents that free-plan accounts receive a `403 Forbidden` response. When the API refuses a booking, the app shows the error and a **Finish on Calendly** button that opens a prefilled link for the chosen slot.
- Reading open times works with a Personal Access Token.
- Calendly rate-limits the booking endpoint. If you see a `429` error, wait and try again.
- The app uses the first active event type on the account and passes its configured location (Google Meet, Zoom, phone and so on) when booking.

## Troubleshooting

| Problem | Likely cause and fix |
| --- | --- |
| `401 The access token is invalid` | `CALENDLY_TOKEN` is wrong, cut off, or still a placeholder. Generate a new token and paste the whole string. |
| `403 Invalid or missing authentication credentials` from Sarvam | `SARVAM_API_KEY` is wrong or inactive. |
| The mic does not start | Allow microphone access for `localhost` in your browser. The page must be served from `localhost` or HTTPS. The input bar shows the browser's error name when this fails. |
| No sound from the app | Some browsers block audio until you have interacted with the page. Click the page once and try again. |
| `Specified location kind is not configured for this event type` | Restart the app so the event type's location is reloaded. |
| `429` when booking | Calendly rate limit reached. Wait before retrying. |
| The mic cuts you off or picks up background noise | Adjust `SILENCE_MS` and `MIN_ON` at the top of the script in `voice_component/index.html`. |
| Changes to `.env` are not picked up | Fully stop and restart Streamlit. |

## Limitations

- One Calendly event type (the first active one) is supported.
- A single voice recording is limited to about 30 seconds, which is Sarvam's REST limit.
- Speech recognition can misspell names and emails. Always check the read-back, and edit the name and email boxes if needed.
- Use headphones if possible, so the microphone does not hear the app's own voice.

## Security

- Never commit your `.env` file. Add it to `.gitignore`:

  ```
  .env
  .venv/
  __pycache__/
  ```

- If a key or token is ever exposed, revoke it in the provider's dashboard and create a new one.

## Contributing

Issues and pull requests are welcome. For larger changes, please open an issue first to discuss what you would like to change.
